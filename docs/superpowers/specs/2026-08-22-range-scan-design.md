# FreqChecker v1.5 — Range Scan Mode: Design Spec

Date: 2026-08-22
Status: Approved concept (Approach A), pending implementation
Prior version: v1.3 (commit 2ba9e49)

---

## 1. Purpose

A new **Range Scan** mode that lets the user pick a frequency band (e.g. 250–1000 Hz),
plays tones across it, and pinpoints **exactly where perceived response drops out** —
reported as a precise defect boundary such as *"435–472 Hz, accuracy ±5 Hz"* —
integrated into the standard session report, exports, and cross-channel comparison.

Result semantics (user decision): **precise defect boundary** (suspected speaker/driver
anomaly location), *not* a personal hearing-threshold map. Existing safeguards
(anchor-relative classification, roll-off shielding, hearing-limit guards) apply unchanged.

## 2. Non-Goals (deliberately excluded)

- Frequencies above 20,000 Hz. Rationale: Windows shared-mode output is 48 kHz
  (Nyquist 24 kHz, safe tone ceiling ≈ 22 kHz); laptop speakers roll off above
  ~15–20 kHz; human hearing ends ~16–20 kHz; FxSound publishes no 30–40 kHz capability.
  Tones beyond 20 kHz would be unproducible or inaudible on target hardware.
- No ML, no auto-started scans, no microphone input, no new audio-engine capabilities.

## 3. User Flow

1. **Setup lives on the Wizard page** (right column, below the mode selector):
   `Start Hz` / `End Hz` boxes, channel selector (`Both L→R` / `Left` / `Right`),
   and a **Start Range Scan** button. Inline red validation when
   `20 ≤ start < end ≤ 20000` is violated; warning (non-blocking) when span > 3 octaves.
   *(Deviation note: earlier sketch said "new page"; setup-on-Wizard + reuse of the
   Testing view gives identical behavior without duplicating the entire rating UI.
   Scanning itself happens in the existing Testing view; results appear in the
   standard Results dashboard.)*
2. **Scanning** reuses the Testing view unchanged: 2 s tones, `Y/N`, `0–10/T` clarity
   pills, distortion slider, `R` replay, `Z` undo, `Esc` stop with partial save,
   blind-mode support, live plot restricted to the scanned band.
3. **Results**: detected silent zones become normal Regions on the Results dashboard,
   HTML/CSV/JSON exports, and cross-channel differential.

## 4. Algorithm (pure logic, `diagnostic_core.py`)

New class `RangeScanScheduler` exposing the same interface as `TestScheduler`
(`get_current_test`, `record_measurement`, `handle_phase_transition`,
`active_measurements`, `test_queue`, `current_idx`, `undo_last_measurement`,
`manual_mode`) so the existing Testing view drives it with minimal glue.

### Constants
| Constant | Value | Meaning |
|---|---|---|
| `BAND_MIN_HZ` | 20.0 | lowest scannable frequency |
| `BAND_MAX_HZ` | 20000.0 | highest scannable frequency |
| `COARSE_MAX_POINTS` | 24 | coarse probes per pass |
| `MIN_STEP_HZ` | 5.0 | smallest probe spacing |
| `REFINE_PROBES_PER_ROUND` | 3 | inserted at 25% / 50% / 75% of each open bracket |
| `MAX_ROUNDS_PER_BRACKET` | 7 | termination bound per transition |
| `MAX_REFINE_PROBES_TOTAL` | 60 | global safety cap |
| `BRACKET_CLOSE_WIDTH_HZ` | 10.0 | bracket considered resolved at ≤ 10 Hz (±5 Hz) |

### Phases
1. **Coarse pass** — `step = max(span / (COARSE_MAX_POINTS − 1), MIN_STEP_HZ)`;
   enqueue evenly spaced probes from start to end inclusive, rounded to 0.1 Hz.
2. **Classification** — per point, reuse `DiagnosticController.effective_classification`.
   Within a scan the personal anchor is the median quality of heard probes once ≥ 4
   exist (band probes are Stage.RANGE, so the coarse-grid fallback tiers of
   `rating_anchor` do not apply), else the 8.0 nominal. GOOD vs BAD/BORDERLINE
   defines the perceived boundary. *(Amended during implementation to match code.)*
3. **Band-silent shortcut** — after the coarse pass, if fewer than 20% of probes are
   effectively GOOD, skip refinement and emit one whole-band region with evidence
   *"entire band inaudible — verify volume/output device"* (prevents dozens of pointless
   probes when output is muted).
4. **Transition refinement** — for every adjacent GOOD↔NOT-GOOD pair, repeatedly insert
   3 probes at 25/50/75% of the bracket (skipping any within 1 Hz of an already-rated
   point), keep the tightest cross-bracket pair, until width ≤ 10 Hz, round cap, or
   global budget exhaustion. Multiple dips refine independently; adjacent NOT-GOOD runs
   merge into one region.
5. **Region building** — each NOT-GOOD run becomes a `Region`:
   - `f_low`/`f_high`: measured NOT-GOOD extremes;
   - `start_estimate`/`end_estimate`: midpoints of the final closing brackets
     (±half final step); band-edge sides marked `lower/upper_boundary_open`;
   - `uncertainty_pct`: `bracket_width / center × 100`, clamped 3–50;
   - category: `PERCEIVED_ANOMALY_HIGH_CONFIDENCE` with ≥ 3 confirming interior
     points, else `MEDIUM_CONFIDENCE`; roll-off and HF-hearing guards applied via
     existing `is_low_rolloff` / threshold predicates;
   - evidence string: `"range scan: N probes, boundary ±X Hz"`.

### Termination guarantee
Every refinement round strictly shrinks each open bracket; round caps (7/bracket) and
the global 60-probe budget bound total probes at ≈ 84 worst case (24 coarse + 60 fine).
Property tests assert termination for arbitrary rater sequences.

## 5. Data Model Changes (`models.py`)

- `Stage.RANGE = "range"` constant.
- `Session.mode = "range_scan"` accepted by `from_dict`/report headers (mode label only).
- No new `RegionCategory` — existing categories + rich evidence strings avoid
  report/plot rendering changes.

## 6. Application Layer (`app.py`)

- Wizard: `QDoubleSpinBox` × 2 (Start 20–19 990, End 30–20 000, 1 decimal), channel
  combo, Start button; `_start_range_scan()` validates and swaps in a
  `RangeScanScheduler` (like sweep-retest swaps schedulers today).
- `_record_current_response`: early dead-output guard skipped for range scans
  (the band-silent shortcut replaces it); everything else unchanged.
- Live plot: `set_data` filtered to `[start, end]`.
- Undo: inherited from the shared interface; refine probes refund nothing (same
  enqueue-time-budget rule as v1.3 bisection).

## 7. Error Handling

- Invalid band: Start button disabled + inline message; no partial states reachable.
- Playback failure during scan: existing `last_playback_ok` gate blocks submission
  until replay succeeds (already built in v1.3).
- Device change mid-scan: engine sample-rate adaptation applies; tones re-validated
  against Nyquist (band ≤ 20 kHz always safe at ≥ 44.1 kHz rates).

## 8. Testing Plan (`test_diagnostic.py`, target ≥ 60 total)

- Coarse queue construction: spacing, inclusive endpoints, bounds clamping.
- Transition detection + refinement convergence: synthetic notch rater (dip planted at
  435–470 Hz inside 250–1000) → reported boundaries within ±6 Hz; asserts termination.
- Multi-dip band → two independent regions; adjacent runs merged.
- Band-edge cases: dip touching start/end → open-boundary flags set correctly.
- Band-silent shortcut fires at < 20% heard and skips refinement.
- Caps: adversarial alternating rater terminates within budget.
- Property fuzz: arbitrary raters → termination, all probes within band,
  no duplicate probes (±1 Hz), regions sorted and non-overlapping.
- Full existing suite stays green.

## 9. Docs & Versioning

- README: Features bullet + Changelog v1.5 entry + Usage Guide section.
- TECH_SPECS: new §1.9 "Range Scan Boundary Refinement" with constants table.
- Test count references updated (50 → N).

## 10. Open Defaults (chosen, adjustable before implementation)

- Refinement style: shrinking 25/50/75% probes to ±5 Hz (user did not answer the
  refinement question; recommended default applied).
- Tone duration 2 s (matches diagnostic modes).
- Blind mode supported (reuses Testing-view toggle).
