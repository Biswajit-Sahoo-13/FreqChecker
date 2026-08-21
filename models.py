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
    REGION_VERIFY = "region_verify"
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
    loudness_relative: Optional[str] = "same"  # softer, same, louder
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
    system_volume: str = "45% (Nominal)"
    fxsound_disabled: bool = True
    enhancements_disabled: bool = True
    output_device_name: str = "Default Audio Device"
    channel_mode: str = "both"  # left, right, both
    notes: str = ""
    channel_results: Dict[str, ChannelResult] = field(default_factory=dict)
    cross_channel_findings: str = ""
    elapsed_seconds: float = 0.0

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
            "heard", "clarity", "distortion", "loudness_relative", "quality",
            "classification", "is_retest", "is_control", "input_error"
        ])
        for ch, res in self.channel_results.items():
            for m in res.measurements:
                writer.writerow([
                    self.session_id, m.timestamp, m.channel, f"{m.frequency_hz:.1f}", m.stage,
                    1 if m.heard else 0, m.clarity, m.distortion if m.distortion is not None else "",
                    m.loudness_relative or "same", f"{m.quality:.2f}", m.classification,
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
        lines.append(f"Session Volume:     {self.system_volume} (Nominal pre-test setting)")
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
            ch_name = ch.upper()
            lines.append(f"\n--- [{ch_name} SPEAKER CHANNEL] ---")
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

