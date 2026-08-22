# FreqChecker: Technical Architecture, Algorithms, and System Optimization

This document provides a comprehensive technical breakdown of **FreqChecker**, detailing the underlying mathematical algorithms, technology stack, concurrency architecture, and performance characteristics.

---

## 1. Algorithms & Mathematical Specifications

FreqChecker is built around rigorous psychoacoustic and signal-processing principles designed to maximize diagnostic accuracy while eliminating false alarms.

### 1.1 Logarithmic Frequency Grid
- **Principle**: Human hearing and speaker acoustics operate on a logarithmic scale. A linear frequency sweep (e.g., 100, 200, 300 Hz) skips entire octaves at the low end and wastes dozens of tests in high-frequency regions.
- **Implementation**: FreqChecker uses standard ISO 1/3-octave center frequencies:
  $$\{63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000\} \text{ Hz}$$
- **Efficiency**: Reduces full-spectrum coarse scanning to just **25 points per channel** (or **6 points** in Quick Mode — 7 with the optional sub-bass toggle) instead of hundreds in a linear scan.

### 1.2 Structural Bass Roll-Off Predicate
- **Problem**: Small laptop speaker drivers physically roll off below $\sim 150 - 250 \text{ Hz}$. Naive frequency-band checks either trigger false alarms or misclassify deep roll-offs.
- **Implementation**: A region is classified under `EXPECTED_LOW_ROLLOFF` if:
  1. $f_{\text{high}} \le 250 \text{ Hz}$, and
  2. Clean reproduction recovers within one octave above the region ($\min(f_{\text{good\_above}}) \le 2 \times f_{\text{high}}$).
- **Benefit**: Naturally covers 63–250 Hz and 160–200 Hz roll-offs while correctly preserving genuine broadband woofer faults (e.g. extending to 600 Hz) as actionable anomalies.

### 1.3 Periodic Control-Tone Stability Check
- **Algorithm**: Injects a fixed **1 kHz control tone** every 8–10 tests.
- **Purpose**: Verifies whether the user shifted system volume, encountered sudden ambient noise, or suffered auditory fatigue. If variation exceeds 3 clarity points ($\Delta > 3$), confidence ratings are adjusted downward and a user warning is issued.

### 1.4 Single-Point Outlier Protection & Small-Region Verification
- **Isolated Outliers**: If a single coarse test point is `BAD` or `BORDERLINE` while its neighbors are `GOOD`, an automatic single retest is scheduled:
  - If retest is `GOOD` $\rightarrow$ Marked as `input_error = True` and discarded.
  - If retest is `BAD` $\rightarrow$ Retained for bisection refinement.
- **Small-Region Retest**: If a run contains fewer than 3 effective bad points with no retest (e.g., double accidental mispress), the worst point is automatically verified before refinement.
- **Confidence Caps**:
  - Single unverified bad point: Anomaly confidence is capped at $\le 35\%$ (`INCONCLUSIVE`).
  - Single verified bad point: Anomaly confidence is capped at $\le 55\%$ (`PERCEIVED_ANOMALY_LOW_CONFIDENCE`).

### 1.5 Local Geometric Midpoint Bisection Refinement
- **Algorithm**: For transitions between a good anchor frequency $f_{\text{good}}$ and a bad anchor $f_{\text{bad}}$, the engine calculates the **geometric midpoint**:
  $$f_{\text{mid}} = \sqrt{f_{\text{good}} \times f_{\text{bad}}}$$
- **Stop Condition**: Bisection stops when the interval width satisfies the 1/12th-octave resolution condition:
  $$\frac{f_{\text{high}}}{f_{\text{low}}} \le 2^{1/12} \approx 1.05946 \quad (\pm 3\% \text{ resolution})$$
  or when a maximum of 6 edge tests have completed.

### 1.6 Boundary Estimation
Rather than reporting raw measured extremes, FreqChecker calculates geometric boundary estimates:
$$f_{\text{start\_est}} = \sqrt{f_{\text{good\_below}} \times f_{\text{bad\_first}}}$$
$$f_{\text{end\_est}} = \sqrt{f_{\text{bad\_last}} \times f_{\text{good\_above}}}$$
- If no good anchor exists at grid edges, boundaries are marked as `lower_boundary_open` or `upper_boundary_open`.

### 1.7 Global Abort & Early Dead-Output Guard
- **Three-way abort** at the coarse→refine transition: `GLOBAL_OUTPUT_FAILURE` (< 25% of mid/high coarse tones heard), `GLOBAL_OUTPUT_UNCERTAIN` (25–75% heard with poor quality), and `RATING_SCALE_LOW`.
- **Anchor-relative scale check**: `RATING_SCALE_LOW` fires only when the personal anchor is $\le 4.0$ or *no* point is effectively GOOD relative to that anchor. A rater whose personal scale never reaches 7 but who anchors consistently (e.g. uniform 6.5 with dips still visible relative to their own baseline) is **not** aborted — anchor-relative classification is the point of the calibration tone.
- **Early guard (mid-coarse)**: after 6 rated coarse tones above 200 Hz with *none* heard, the channel aborts immediately as `GLOBAL_OUTPUT_FAILURE` instead of dragging the user through the remaining coarse pass. Sub-bass tones (≤ 200 Hz) and control tones never count toward this guard, so expected low-frequency roll-off cannot trigger it.

### 1.8 Dual Confidence Scoring
1. **Anomaly Confidence ($0 - 95\%$)**:
   $$\text{AnomalyConf} = 35\% \cdot S_{\text{consistency}} + 25\% \cdot S_{\text{depth}} + 20\% \cdot S_{\text{retest}} + 10\% \cdot S_{\text{control}} + 10\% \cdot S_{\text{plausibility}}$$
2. **Hardware Attribution Confidence ($0 - 95\%$)**:
   - Applies multipliers based on physical constraints:
     - Normal bass roll-off ($\le 250 \text{ Hz}$) $\rightarrow \times 0.20$
     - Active DSP/Enhancements detected $\rightarrow \times 0.30$
     - Control tone instability $\rightarrow \times 0.60$
     - Symmetrical dual-channel dip $\rightarrow \times 0.45$ (Identifies DSP/room standing waves)
     - Asymmetrical single-channel dip $\rightarrow \times 1.15$ (Identifies physical speaker driver fault)

---

## 2. Technology Stack & Concurrency Architecture

| Layer | Technology | Role & Rationale |
|---|---|---|
| **Core Runtime** | Python 3.11+ | Clean standard library with native high-performance C-extensions. |
| **Numerical Processing** | NumPy 2.x | Vectorized array synthesis for instantaneous sine generation, DC offset removal, and raised-cosine ramps. |
| **Audio Pipeline** | PortAudio / `sounddevice` | Native low-latency streaming via Windows **WASAPI** and **DirectSound**. |
| **GUI Framework** | PySide6 (Qt 6) | Hardware-accelerated desktop UI with custom anti-aliased logarithmic plot. |
| **Concurrency Safety** | `AudioSignalBridge` (QObject Signals) | Marshals background audio thread events to the Qt GUI event loop, eliminating cross-thread GUI crashes. |
| **Playback Lifecycle** | Generation Counter & Worker Thread Join | Incremental `_generation` tracking and thread timeouts prevent play/stop race conditions. |
| **Packaging** | PyInstaller 6.x | Standalone single-file executable (`freqchecker.exe`) with pruned unused Qt submodules. |

---

## 3. Resource & Performance Analysis

### 3.1 Memory Footprint
- **Audio Buffers**: Transient memory per 2.0-second stereo float32 tone is $\sim 3\text{ MB}$ during vectorization, freeing immediately upon garbage collection.
- **Resident RAM (RSS)**: Stays between **60 MB and 110 MB** (standard for PySide6 desktop applications with pruned submodules).
- **Zero Memory Leaks**: Verified clean lifecycle across hundreds of consecutive tones.

### 3.2 CPU & Concurrency
- **Idle CPU**: **0.0%** load while waiting for user input.
- **Active Tone Synthesis**: Takes **$< 2\text{ ms}$** of CPU time per tone.
- **Stop Latency**: Abort latency is **$< 25\text{ ms}$** via `Event.is_set()` polling.

---

## 4. System Requirements

- **Operating System**: Windows 10 / Windows 11 (64-bit).
- **Processor**: Intel Celeron / Core i3 / AMD Athlon / Ryzen 3 or higher.
- **RAM**: Minimum 512 MB.
- **Disk Space**: 60 MB for standalone `freqchecker.exe`.
- **Audio Output**: Any standard built-in PC speaker, Realtek HD Audio, USB DAC, or headphone output.
