"""
models.py - Data structures and persistence models for FreqChecker.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import datetime
import json
import csv
import io


class Classification:
    GOOD = "GOOD"
    BORDERLINE = "BORDERLINE"
    BAD = "BAD"


class Stage:
    COARSE = "coarse"
    CONTROL = "control"
    RETEST = "retest"
    REFINE = "refine"
    MANUAL = "manual"
    SWEEP = "sweep"


class RegionCategory:
    NO_ISSUE = "NO_ISSUE"
    EXPECTED_LOW_ROLLOFF = "EXPECTED_LOW_ROLLOFF"
    PERCEIVED_ANOMALY_LOW_CONFIDENCE = "PERCEIVED_ANOMALY_LOW_CONFIDENCE"
    PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE = "PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE"
    PERCEIVED_ANOMALY_HIGH_CONFIDENCE = "PERCEIVED_ANOMALY_HIGH_CONFIDENCE"
    LIKELY_LEVEL_DEPENDENT_DISTORTION = "LIKELY_LEVEL_DEPENDENT_DISTORTION"
    LIKELY_DSP_OR_ENHANCEMENT_EFFECT = "LIKELY_DSP_OR_ENHANCEMENT_EFFECT"
    GLOBAL_OUTPUT_PROBLEM = "GLOBAL_OUTPUT_PROBLEM"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class Measurement:
    frequency_hz: float
    channel: str  # "left", "right", "both"
    stage: str  # coarse, control, retest, refine, region_verify, manual, sweep
    heard: bool
    clarity: int  # 0 to 10
    distortion: Optional[int] = None  # 0 to 10
    quality: float = 0.0
    classification: str = Classification.GOOD
    effective_classification: Optional[str] = None
    is_retest: bool = False
    is_control: bool = False
    input_error: bool = False
    verified_suspicious: bool = False
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    volume_level: float = 0.4
    measurement_id: str = ""

    def __post_init__(self):
        if not self.measurement_id:
            self.measurement_id = f"{int(self.frequency_hz)}_{self.channel}_{self.timestamp}"
        
        # Clamp inputs
        self.clarity = max(0, min(10, int(self.clarity))) if self.clarity is not None else 0
        if self.distortion is not None:
            self.distortion = max(0, min(10, int(self.distortion)))
            
        if not self.heard:
            self.quality = 0.0
            self.clarity = 0
            self.classification = Classification.BAD
        else:
            if self.distortion is not None and self.distortion > 0:
                self.quality = max(0.0, float(self.clarity) - 0.4 * float(self.distortion))
            else:
                self.quality = float(self.clarity)
            
            if self.quality >= 7.0:
                self.classification = Classification.GOOD
            elif self.quality >= 4.0:
                self.classification = Classification.BORDERLINE
            else:
                self.classification = Classification.BAD


def practical_round_freq(f: float) -> float:
    """
    Perceptually meaningful frequency rounding to prevent false precision.
    """
    if f <= 0:
        return 0.0
    if f < 100.0:
        return float(round(f))
    if f < 1000.0:
        return float(5.0 * round(f / 5.0))
    if f < 5000.0:
        return float(10.0 * round(f / 10.0))
    if f < 10000.0:
        return float(50.0 * round(f / 50.0))
    return float(100.0 * round(f / 100.0))


@dataclass
class Region:
    region_id: str
    channel: str
    f_low: float
    f_high: float
    center_frequency: float
    min_quality: float
    baseline_quality: float
    depth: float
    effective_bad_count: float
    anomaly_confidence: int  # 0 to 95%
    hardware_confidence: int  # 0 to 95%
    category: str
    evidence: str
    worst_frequency: float = 0.0
    avg_quality: float = 0.0
    severity: str = "Uncertain"
    uncertainty_pct: float = 3.0
    start_estimate: float = 0.0
    end_estimate: float = 0.0
    lower_boundary_open: bool = False
    upper_boundary_open: bool = False
    is_point_anomaly: bool = False
    points: List[Measurement] = field(default_factory=list)

    def __post_init__(self):
        if self.start_estimate == 0.0:
            self.start_estimate = self.f_low
        if self.end_estimate == 0.0:
            self.end_estimate = self.f_high
        if self.worst_frequency == 0.0:
            if self.points:
                # Deterministic tie-breaking: lowest quality -> largest deviation from baseline -> lowest frequency
                self.worst_frequency = min(
                    self.points,
                    key=lambda p: (p.quality, -(self.baseline_quality - p.quality), p.frequency_hz)
                ).frequency_hz
            else:
                self.worst_frequency = self.center_frequency
        if self.avg_quality == 0.0 and self.points:
            self.avg_quality = round(sum(p.quality for p in self.points) / float(len(self.points)), 1)


@dataclass
class ChannelResult:
    channel: str
    measurements: List[Measurement] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)
    avg_clarity: float = 0.0
    rating_anchor: float = 8.0
    is_global_problem: bool = False
    global_problem_type: str = ""  # "GLOBAL_OUTPUT_FAILURE", "GLOBAL_OUTPUT_UNCERTAIN", "RATING_SCALE_LOW"
    is_control_unstable: bool = False
    status_summary: str = ""


@dataclass
class Session:
    schema_version: int = 2
    session_id: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    mode: str = "detailed"  # quick, detailed, manual, sweep
    sample_rate: int = 48000
    duration_per_tone: float = 2.0
    peak_level: float = 0.4
    fxsound_disabled: bool = True
    enhancements_disabled: bool = True
    output_device_name: str = "Default Audio Device"
    channel_mode: str = "both"  # left, right, both
    notes: str = ""
    channel_results: Dict[str, ChannelResult] = field(default_factory=dict)
    cross_channel_findings: str = ""
    elapsed_seconds: float = 0.0
    sweep_marks_hz: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        from dataclasses import fields as get_fields

        def _filter_kwargs(target_cls, d: Dict[str, Any]) -> Dict[str, Any]:
            valid_keys = {f.name for f in get_fields(target_cls)}
            return {k: v for k, v in d.items() if k in valid_keys}

        session_kwargs = _filter_kwargs(cls, data)
        # Handle field conversions if any
        session_kwargs.pop("channel_results", None)

        session = cls(**session_kwargs)
        
        channel_results = {}
        for ch, ch_data in data.get("channel_results", {}).items():
            meas_list = [
                Measurement(**_filter_kwargs(Measurement, m))
                for m in ch_data.get("measurements", [])
            ]
            reg_list = []
            for r in ch_data.get("regions", []):
                r_copy = dict(r)
                r_pts = [
                    Measurement(**_filter_kwargs(Measurement, p))
                    for p in r_copy.pop("points", [])
                ]
                filtered_kwargs = _filter_kwargs(Region, r_copy)
                reg_list.append(Region(points=r_pts, **filtered_kwargs))
            
            ch_kwargs = _filter_kwargs(ChannelResult, ch_data)
            ch_kwargs["channel"] = ch
            ch_kwargs["measurements"] = meas_list
            ch_kwargs["regions"] = reg_list
            channel_results[ch] = ChannelResult(**ch_kwargs)

        session.channel_results = channel_results
        return session

    def export_csv_string(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "session_id", "timestamp", "channel", "frequency_hz", "stage",
            "heard", "clarity", "distortion", "quality",
            "classification", "is_retest", "is_control", "input_error"
        ])
        for ch, res in self.channel_results.items():
            for m in res.measurements:
                writer.writerow([
                    self.session_id, m.timestamp, m.channel, f"{m.frequency_hz:.1f}", m.stage,
                    1 if m.heard else 0, m.clarity, m.distortion if m.distortion is not None else "",
                    f"{m.quality:.2f}", m.classification,
                    1 if m.is_retest else 0, 1 if m.is_control else 0, 1 if m.input_error else 0
                ])
        return output.getvalue()

    def generate_report(self) -> str:
        lines = []
        lines.append("=" * 66)
        lines.append("        FreqChecker - SPEAKER FREQUENCY DIAGNOSTIC REPORT")
        lines.append("=" * 66)
        lines.append(f"Session ID:         {self.session_id}")
        lines.append(f"Date & Time:        {self.created_at}")
        lines.append(f"Mode:               {self.mode.title()} Test")
        lines.append(f"Output Device:      {self.output_device_name}")
        enh_status = "Disabled (Standard Pure Output)" if (self.fxsound_disabled and self.enhancements_disabled) else "Active / Potentially Altered"
        lines.append(f"Audio Enhancements: {enh_status}")
        
        total_tests = sum(len(res.measurements) for res in self.channel_results.values())
        lines.append(f"Total Tests Run:    {total_tests}")
        minutes = int(self.elapsed_seconds // 60)
        seconds = int(self.elapsed_seconds % 60)
        lines.append(f"Elapsed Time:       {minutes} min {seconds} s")
        lines.append("-" * 66)

        all_regions = []
        for ch, res in self.channel_results.items():
            if ch == "sweep":
                ch_name = "SWEEP MARKER RETESTS"
            else:
                ch_name = ch.upper() + " SPEAKER CHANNEL"
            lines.append(f"\n--- [{ch_name}] ---")
            lines.append(f"Average Perceived Clarity:  {res.avg_clarity:.1f} / 10")
            lines.append(f"Rater Calibration Baseline: {res.rating_anchor:.1f} / 10 (calibrated from 1 kHz reference controls)")
            if res.rating_anchor < 5.0 and not res.is_global_problem:
                lines.append("  [Note]: Calibration anchor is low (< 5.0). Thresholds clamped to 5.0 nominal floor to avoid detection collapse.")
            
            if res.is_global_problem:
                if res.global_problem_type == "RATING_SCALE_LOW":
                    lines.append("  [*] LOW RATING SCALE BASELINE DETECTED")
                    lines.append("      All test tones were audible but consistently rated low (good_count = 0).")
                    lines.append("      Interpretation: This usually indicates nominal playback volume was set too low or")
                    lines.append("      the rating scale was used conservatively — it does NOT indicate hardware failure.")
                    lines.append("      Recommendation: Increase volume, replay the 1 kHz calibration tone, and re-run.")
                elif res.global_problem_type == "GLOBAL_OUTPUT_UNCERTAIN":
                    lines.append("  [?] GLOBAL OUTPUT AUDIBILITY UNCERTAIN")
                    lines.append("      Partial or inconsistent audibility detected across the spectrum (25%–75% heard).")
                    lines.append("      Possible causes: Low nominal volume, ambient room noise, listener hearing variation,")
                    lines.append("      or intermittent audio driver filtering.")
                    lines.append("      Recommendation: Verify playback volume, test with headphones to rule out acoustic limits, and re-run.")
                else:
                    lines.append("  [!] GLOBAL OUTPUT FAILURE DETECTED")
                    lines.append("      Mid-range and high test frequencies were inaudible or severely degraded (< 25% heard).")
                    lines.append("      Possible causes: Muted volume, incorrect playback device, driver crash, or active heavy filter.")
                continue

            if res.is_control_unstable:
                lines.append("  [*] Note: Inconsistent responses detected on periodic 1 kHz control tones.")
                lines.append("      Confidence is moderately reduced (possible listener fatigue or volume shift).")

            if ch == "sweep":
                if not res.measurements:
                    lines.append("  [OK] No sweep marker retests were recorded.")
                else:
                    lines.append("  Subjective ratings at user-marked sweep anomaly frequencies:")
                    for m in res.measurements:
                        verdict = "audible" if m.heard else "NOT audible"
                        lines.append(
                            f"    - ~{practical_round_freq(m.frequency_hz):,.0f} Hz: {verdict}"
                            + (f", clarity {m.clarity}/10" if m.heard else "")
                        )
                    lines.append("  [Note] Markers reflect subjective impressions during a fast sweep;")
                    lines.append("         ratings above are calibrated re-tests at those exact frequencies.")
                continue

            if not res.regions:
                lines.append("  [OK] No significant frequency response anomalies detected.")
                lines.append("    Perceived playback is clean across the tested spectrum.")
            else:
                for reg in res.regions:
                    all_regions.append(reg)
                    start_disp = practical_round_freq(reg.start_estimate)
                    end_disp = practical_round_freq(reg.end_estimate)
                    worst_disp = practical_round_freq(reg.worst_frequency if reg.worst_frequency > 0 else reg.center_frequency)
                    unc_val = reg.uncertainty_pct if reg.uncertainty_pct > 0 else 3.0
                    unc_str = f"±{unc_val:.0f}%"

                    if reg.is_point_anomaly or reg.f_low == reg.f_high or start_disp >= end_disp:
                        range_str = f"~{worst_disp:.0f} Hz (Narrow Point Anomaly)"
                        uncertainty_display = f"Bracket precision {unc_str}"
                    elif reg.lower_boundary_open:
                        range_str = f"< {end_disp:.0f} Hz (extends below tested range)"
                        uncertainty_display = "Lower boundary unknown; anomaly may extend below tested range"
                    elif reg.upper_boundary_open:
                        range_str = f"> {start_disp:.0f} Hz (extends above tested range)"
                        uncertainty_display = "Upper boundary unknown; anomaly may extend above tested range"
                    else:
                        range_str = f"≈{start_disp:.0f} – {end_disp:.0f} Hz"
                        uncertainty_display = f"Boundary bracket uncertainty {unc_str}"

                    lines.append(f"\n  • Affected Frequency Range: {range_str}")
                    lines.append(f"    Worst Measured Point:     ~{worst_disp:.0f} Hz (Quality: {reg.min_quality:.1f} / 10)")
                    lines.append(f"    Average Quality in Dip:   {reg.avg_quality:.1f} / 10")
                    lines.append(f"    Local Baseline Quality:   {reg.baseline_quality:.1f} / 10  (Depth: {reg.depth:.1f} points)")
                    lines.append(f"    Boundary Uncertainty:     {uncertainty_display}")
                    if reg.f_high > 0 and reg.f_low > 0 and (reg.f_high / reg.f_low > 2.0):
                        lines.append("    Resolution Caveat:        Wide region (>1 octave); true acoustic dip minimum may lie within ±1/3 octave of measured points.")
                    lines.append(f"    Severity:                 {reg.severity}")
                    lines.append(f"    Anomaly Confidence:       {reg.anomaly_confidence}%")
                    lines.append(f"    Hardware Attribution:     {reg.hardware_confidence}%")
                    lines.append(f"    Category:                 {reg.category.replace('_', ' ').title()}")
                    lines.append(f"    Evidence:                 {reg.evidence}")

        if self.cross_channel_findings:
            lines.append("\n" + "-" * 66)
            lines.append("--- [CROSS-CHANNEL DIFFERENTIAL ANALYSIS] ---")
            lines.append(self.cross_channel_findings)

        lines.append("\n" + "=" * 66)
        lines.append("DIAGNOSTIC GUIDANCE & INTERPRETATION:")
        lines.append("1. 'Perceived Anomaly' reflects what was audible under current test conditions.")
        lines.append("2. Acoustic roll-off below 160–250 Hz is standard physical limitation for small laptop drivers.")
        lines.append("3. Inaudibility at extreme high frequencies (>= 10 kHz) commonly reflects human hearing thresholds.")
        lines.append("4. If both channels dip at the identical frequency, active EQ/DSP or room acoustic")
        lines.append("   notches are significantly more likely than two identical speaker hardware faults.")
        lines.append("5. For single-channel dips, verify with headphones to rule out one-sided hearing differences.")
        lines.append("=" * 66)
        return "\n".join(lines)

    def generate_html_report(self) -> str:
        """Premium HTML report — FxSound-inspired, print-ready, no external assets."""
        import html as _html
        def _esc(s: Any) -> str:
            return _html.escape(str(s))
        def _sev_color(sev: str) -> str:
            s = sev.lower()
            if s == "strong": return "#d51535"
            if s == "moderate": return "#fa8c16"
            if s == "minor": return "#faad14"
            if s == "uncertain": return "#8c8c8c"
            if "roll-off" in s.lower(): return "#595959"
            if "no significant" in s.lower(): return "#52c41a"
            return "#595959"
        def _cat_label(cat: str) -> str:
            return cat.replace("_", " ").title()
        def _cat_style(cat: str) -> str:
            if cat == RegionCategory.EXPECTED_LOW_ROLLOFF: return "background:#f5f5f5; color:#595959; border:1px solid #e8e8e8;"
            if cat == RegionCategory.PERCEIVED_ANOMALY_HIGH_CONFIDENCE: return "background:#fff1f0; color:#a8071a; border:1px solid #ffccc7;"
            if cat == RegionCategory.PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE: return "background:#fff7e6; color:#ad4e00; border:1px solid #ffd591;"
            if cat == RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE: return "background:#fffbe6; color:#ad6800; border:1px solid #ffe58f;"
            if cat == RegionCategory.LIKELY_DSP_OR_ENHANCEMENT_EFFECT: return "background:#f9f0ff; color:#391085; border:1px solid #d3adf7;"
            if cat == RegionCategory.LIKELY_LEVEL_DEPENDENT_DISTORTION: return "background:#fff2e8; color:#873800; border:1px solid #ffbb96;"
            if cat == RegionCategory.INCONCLUSIVE: return "background:#f5f5f5; color:#595959; border:1px solid #d9d9d9;"
            return "background:#f5f5f5; color:#595959; border:1px solid #d9d9d9;"

        total_tests = sum(len(res.measurements) for res in self.channel_results.values())
        minutes = int(self.elapsed_seconds // 60)
        seconds = int(self.elapsed_seconds % 60)
        enh_ok = self.fxsound_disabled and self.enhancements_disabled
        enh_label = "Clean — Enhancements Disabled" if enh_ok else "Active / Potentially Altered"
        enh_dot = "#52c41a" if enh_ok else "#faad14"
        enh_bg = "#f6ffed" if enh_ok else "#fffbe6"
        enh_bd = "#b7eb8f" if enh_ok else "#ffe58f"
        mode_label = self.mode.title() + " Test"
        # Build channel HTML
        channels_html = ""
        for ch, res in self.channel_results.items():
            if ch == "sweep":
                header_accent = "#722ed1"
                ch_title = "Sweep Marker Retests"
                ch_icon = "S"
            elif ch == "left":
                header_accent = "#d51535"
                ch_title = "Left Speaker"
                ch_icon = "L"
            elif ch == "right":
                header_accent = "#1ac1ff"
                ch_title = "Right Speaker"
                ch_icon = "R"
            else:
                header_accent = "#595959"
                ch_title = _esc(ch.title())
                ch_icon = "•"
            avg = f"{res.avg_clarity:.1f} / 10"
            anchor = f"{res.rating_anchor:.1f} / 10"
            # status badge
            if res.is_global_problem:
                if res.global_problem_type == "RATING_SCALE_LOW":
                    status_html = '<span class="badge warn">Low Rating Scale</span><p class="callout warn">All tones audible but rated low — volume too low or conservative rating. Not a hardware failure. Increase volume and replay 1 kHz calibration.</p>'
                elif res.global_problem_type == "GLOBAL_OUTPUT_UNCERTAIN":
                    status_html = '<span class="badge warn">Uncertain Output</span><p class="callout warn">Partial audibility 25–75% with low quality. Check volume, room noise, or test with headphones.</p>'
                else:
                    status_html = '<span class="badge danger">Output Failure</span><p class="callout danger">Mid/high frequencies inaudible &lt;25% heard. Check mute, device, driver or heavy filter.</p>'
                regions_block = ""
            else:
                if res.is_control_unstable:
                    status_html = '<span class="badge warn">Control Drift</span><p class="hint">1 kHz control tones varied — possible fatigue or volume shift. Confidence slightly reduced.</p>'
                elif not res.regions:
                    status_html = '<span class="badge ok">Clean</span><p class="hint">No significant anomalies. Playback is uniform across the tested spectrum.</p>'
                    regions_block = ""
                else:
                    status_html = f'<span class="badge danger">{len(res.regions)} anomaly{"s" if len(res.regions)!=1 else ""} detected</span>'
                    regions_block = ""
                if not res.is_global_problem and ch != "sweep":
                    if not res.regions:
                        regions_block = '<div class="empty">No anomalies — response is flat.</div>'
                    else:
                        for reg in res.regions:
                            start_disp = practical_round_freq(reg.start_estimate)
                            end_disp = practical_round_freq(reg.end_estimate)
                            worst_disp = practical_round_freq(reg.worst_frequency if reg.worst_frequency > 0 else reg.center_frequency)
                            unc = f'{reg.uncertainty_pct:.0f}%' if reg.uncertainty_pct else '3%'
                            if reg.is_point_anomaly or reg.f_low == reg.f_high or start_disp >= end_disp:
                                range_str = f'~{worst_disp:.0f} Hz <span class="sub">Narrow point anomaly</span>'
                                bracket_note = f'Bracket ±{unc}'
                            elif reg.lower_boundary_open:
                                range_str = f'&lt; {end_disp:.0f} Hz <span class="sub">extends below range</span>'
                                bracket_note = 'Lower open'
                            elif reg.upper_boundary_open:
                                range_str = f'&gt; {start_disp:.0f} Hz <span class="sub">extends above range</span>'
                                bracket_note = 'Upper open'
                            else:
                                range_str = f'{start_disp:.0f} – {end_disp:.0f} Hz'
                                bracket_note = f'±{unc} bracket'
                            sev_c = _sev_color(reg.severity)
                            cat_style = _cat_style(reg.category)
                            anom_w = max(4, min(100, reg.anomaly_confidence))
                            hard_w = max(4, min(100, reg.hardware_confidence))
                            regions_block += f'''
                            <div class="region">
                              <div class="region-head">
                                <div class="range">{range_str} <span class="bracket">{_esc(bracket_note)}</span></div>
                                <span class="severity" style="background:{sev_c}; color:#fff;">{_esc(reg.severity)}</span>
                              </div>
                              <div class="region-grid">
                                <div><span class="k">Worst point</span><span class="v">~{worst_disp:.0f} Hz · {reg.min_quality:.1f}/10</span></div>
                                <div><span class="k">Average in dip</span><span class="v">{reg.avg_quality:.1f}/10</span></div>
                                <div><span class="k">Local baseline</span><span class="v">{reg.baseline_quality:.1f}/10 <span class="depth">depth {reg.depth:.1f}</span></span></div>
                                <div><span class="k">Points</span><span class="v">{len(reg.points)} measured</span></div>
                              </div>
                              <div class="bars">
                                <div class="bar-row"><span class="bar-label">Anomaly</span><div class="bar-track"><div class="bar-fill" style="width:{anom_w}%; background:{sev_c};"></div></div><span class="bar-val">{reg.anomaly_confidence}%</span></div>
                                <div class="bar-row"><span class="bar-label">Hardware</span><div class="bar-track"><div class="bar-fill" style="width:{hard_w}%; background:#595959;"></div></div><span class="bar-val">{reg.hardware_confidence}%</span></div>
                              </div>
                              <div class="cat" style="{cat_style} padding:4px 10px; border-radius:999px; display:inline-block; font-size:11px; font-weight:700;">{_esc(_cat_label(reg.category))}</div>
                              <div class="evidence">{_esc(reg.evidence)}</div>
                            </div>
                            '''
                if ch == "sweep":
                    if not res.measurements:
                        regions_block = '<div class="empty">No sweep markers retested.</div>'
                    else:
                        rows = "".join(f'<tr><td>~{practical_round_freq(m.frequency_hz):,.0f} Hz</td><td>{"audible" if m.heard else "<b>NOT audible</b>"}</td><td>{"%d/10"%m.clarity if m.heard else "—"}</td></tr>' for m in res.measurements)
                        regions_block = f'<table class="sweep-table"><thead><tr><th>Frequency</th><th>Result</th><th>Clarity</th></tr></thead><tbody>{rows}</tbody></table><p class="hint">Markers are subjective impressions during fast sweep — rows above are calibrated retests.</p>'
            channels_html += f'''
            <section class="channel-card" style="border-top: 4px solid {header_accent};">
              <div class="channel-head">
                <div class="ch-badge" style="background:{header_accent};">{ch_icon}</div>
                <div>
                  <h3>{_esc(ch_title)}</h3>
                  <p class="ch-meta">Avg clarity {avg} · Anchor {anchor}</p>
                </div>
                <div class="ch-status">{status_html}</div>
              </div>
              {regions_block}
            </section>
            '''

        cc_html = ""
        if self.cross_channel_findings:
            cc_esc = _esc(self.cross_channel_findings).replace("\n", "<br>")
            cc_html = f'<section class="cc-card"><h3>Cross-Channel Differential</h3><div class="cc-body">{cc_esc}</div></section>'

        # guidance
        guidance = [
            "'Perceived Anomaly' reflects what was audible under current conditions.",
            "Acoustic roll-off below 160–250 Hz is standard for small laptop drivers.",
            "Inaudibility ≥10 kHz commonly reflects human hearing thresholds.",
            "If both channels dip at the same frequency, DSP/EQ or room acoustics are more likely than twin hardware faults.",
            "For single-channel dips, verify with headphones to rule out hearing asymmetry.",
        ]
        guidance_html = "".join(f'<li>{_esc(g)}</li>' for g in guidance)

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FreqChecker Report — {_esc(self.session_id)}</title>
<style>
  @page {{ margin: 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px; font-family: 'Inter','Segoe UI',system-ui,-apple-system,sans-serif; background:#f5f5f7; color:#1f1f1f; line-height:1.5; -webkit-print-color-adjust: exact; }}
  .shell {{ max-width: 960px; margin:0 auto; }}
  .header {{ background: linear-gradient(135deg,#0f0f0f 0%, #1e1e1e 100%); color:#fff; border-radius:16px; padding:28px 32px; margin-bottom:20px; position:relative; overflow:hidden; }}
  .header::after {{ content:""; position:absolute; top:-40px; right:-40px; width:220px; height:220px; background: radial-gradient(circle, rgba(213,21,53,0.18) 0%, transparent 70%); }}
  .header h1 {{ margin:0; font-size:22px; letter-spacing:-0.3px; font-weight:800; }}
  .header h1 span {{ color:#d51535; }}
  .header p {{ margin:6px 0 0; color:#b1b1b1; font-size:13px; }}
  .meta {{ position:absolute; top:22px; right:24px; text-align:right; font-size:12px; color:#b1b1b1; line-height:1.4; }}
  .meta strong {{ color:#fff; font-weight:700; }}
  .summary {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin-bottom:20px; }}
  .kpi {{ background:#fff; border:1px solid #e6e8eb; border-radius:12px; padding:14px 16px; }}
  .kpi .k {{ font-size:11px; letter-spacing:0.6px; text-transform:uppercase; color:#7f7f7f; font-weight:700; }}
  .kpi .v {{ font-size:14px; font-weight:700; margin-top:4px; color:#1f1f1f; }}
  .kpi .v small {{ font-weight:500; color:#595959; }}
  .kpi.enh {{ border-left: 4px solid {enh_dot}; background:{enh_bg}; }}
  .channel-card {{ background:#fff; border:1px solid #e6e8eb; border-radius:14px; padding:20px 22px; margin-bottom:16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .channel-head {{ display:flex; align-items:center; gap:14px; margin-bottom:14px; }}
  .ch-badge {{ width:32px; height:32px; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:800; font-size:14px; flex-shrink:0; }}
  .channel-head h3 {{ margin:0; font-size:15px; font-weight:800; }}
  .ch-meta {{ margin:2px 0 0; font-size:12px; color:#595959; }}
  .ch-status {{ margin-left:auto; text-align:right; }}
  .badge {{ display:inline-block; padding:4px 10px; border-radius:999px; font-size:11px; font-weight:800; letter-spacing:0.4px; }}
  .badge.ok {{ background:#f6ffed; color:#389e0d; border:1px solid #b7eb8f; }}
  .badge.warn {{ background:#fffbe6; color:#ad6800; border:1px solid #ffe58f; }}
  .badge.danger {{ background:#fff1f0; color:#a8071a; border:1px solid #ffccc7; }}
  .callout {{ margin:8px 0 0; padding:8px 12px; border-radius:8px; font-size:12px; line-height:1.5; }}
  .callout.warn {{ background:#fffbe6; border:1px solid #ffe58f; color:#613400; }}
  .callout.danger {{ background:#fff1f0; border:1px solid #ffccc7; color:#5c0011; }}
  .hint {{ font-size:12px; color:#7f7f7f; margin-top:6px; }}
  .empty {{ background:#f5f5f7; border:1px dashed #d9d9d9; border-radius:10px; padding:16px; text-align:center; color:#595959; font-size:13px; }}
  .region {{ border:1px solid #f0f0f0; border-radius:12px; padding:16px; margin-top:12px; background:#fcfcfc; }}
  .region-head {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  .range {{ font-size:15px; font-weight:800; }}
  .range .sub {{ font-weight:500; color:#595959; font-size:12px; margin-left:6px; }}
  .bracket {{ font-size:11px; color:#7f7f7f; margin-left:8px; font-weight:600; }}
  .severity {{ margin-left:auto; padding:4px 10px; border-radius:999px; font-size:11px; font-weight:800; }}
  .region-grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin:12px 0; }}
  .region-grid div {{ background:#fff; border:1px solid #e8e8eb; border-radius:10px; padding:10px 12px; }}
  .region-grid .k {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#7f7f7f; font-weight:700; }}
  .region-grid .v {{ display:block; font-size:13px; font-weight:700; margin-top:2px; }}
  .depth {{ font-weight:500; color:#595959; font-size:12px; }}
  .bars {{ display:grid; gap:8px; margin:10px 0; }}
  .bar-row {{ display:grid; grid-template-columns: 72px 1fr 44px; align-items:center; gap:10px; font-size:12px; }}
  .bar-label {{ color:#595959; font-weight:600; font-size:11px; }}
  .bar-track {{ height:8px; background:#f0f0f0; border-radius:999px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:999px; }}
  .bar-val {{ font-weight:700; text-align:right; }}
  .cat {{ display:inline-block; padding:4px 10px; border-radius:999px; font-size:11px; font-weight:700; margin-top:6px; }}
  .evidence {{ margin-top:8px; font-size:12px; color:#434343; background:#fff; border:1px solid #f0f0f0; border-radius:8px; padding:8px 10px; }}
  .cc-card {{ background:#fff; border:1px solid #e6e8eb; border-left:4px solid #1ac1ff; border-radius:14px; padding:18px 22px; margin-bottom:16px; }}
  .cc-card h3 {{ margin:0 0 8px; font-size:14px; font-weight:800; }}
  .cc-body {{ font-size:13px; color:#434343; line-height:1.6; white-space:pre-wrap; }}
  .guide {{ background:#fff; border:1px solid #e6e8eb; border-radius:14px; padding:20px 22px; }}
  .guide h3 {{ margin:0 0 10px; font-size:14px; font-weight:800; }}
  .guide ol {{ margin:0; padding-left:18px; font-size:13px; color:#434343; }}
  .guide li {{ margin-bottom:6px; }}
  .footer {{ text-align:center; font-size:11px; color:#8c8c8c; margin-top:18px; }}
  .sweep-table {{ width:100%; border-collapse: collapse; margin-top:8px; font-size:13px; }}
  .sweep-table th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#7f7f7f; background:#f5f5f7; padding:8px 10px; }}
  .sweep-table td {{ padding:8px 10px; border-bottom:1px solid #f0f0f0; }}
  @media (max-width: 640px) {{
    body {{ padding:16px; }}
    .summary {{ grid-template-columns: repeat(2, 1fr); }}
    .region-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .header {{ padding:20px; }}
    .meta {{ position:static; text-align:left; margin-top:12px; }}
  }}
  @media print {{
    body {{ background:#fff; padding:0; }}
    .shell {{ max-width: none; }}
    .header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
<div class="shell">
  <div class="header">
    <h1>FREQ<span>CHECKER</span> — Diagnostic Report</h1>
    <p>Speaker Frequency Diagnostic Studio · FxSound-inspired premium report</p>
    <div class="meta">
      <div><strong>{_esc(self.session_id)}</strong> · Session</div>
      <div>{_esc(self.created_at)}</div>
      <div>{_esc(self.output_device_name)}</div>
    </div>
  </div>

  <div class="summary">
    <div class="kpi"><div class="k">Mode</div><div class="v">{_esc(mode_label)}</div></div>
    <div class="kpi"><div class="k">Output Device</div><div class="v" style="font-size:13px;">{_esc(self.output_device_name)}</div></div>
    <div class="kpi"><div class="k">Total Tests</div><div class="v">{total_tests} <small>tones</small></div></div>
    <div class="kpi"><div class="k">Elapsed</div><div class="v">{minutes} min {seconds} s</div></div>
  </div>
  <div class="summary" style="grid-template-columns: 1fr;">
    <div class="kpi enh" style="background:{enh_bg}; border-color:{enh_bd}; border-left-color:{enh_dot};">
      <div class="k">Audio Enhancements</div><div class="v">{_esc(enh_label)}</div>
    </div>
  </div>

  {channels_html}
  {cc_html}

  <section class="guide">
    <h3>Diagnostic Guidance &amp; Interpretation</h3>
    <ol>
      {guidance_html}
    </ol>
  </section>

  <div class="footer">Generated by FreqChecker · {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} · Session {self.session_id} · This is a listening-based test, not a hardware failure proof.</div>
</div>
</body>
</html>
'''

