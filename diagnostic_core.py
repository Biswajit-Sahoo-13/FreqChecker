"""
diagnostic_core.py - Adaptive testing algorithm, mathematical analysis controller, and pure scheduler for FreqChecker.
"""

import math
from typing import List, Dict, Tuple, Optional, Any
import numpy as np

from models import (
    Measurement, Region, ChannelResult, Session,
    Classification, Stage, RegionCategory
)


class DiagnosticConfig:
    STOP_RATIO = 2.0 ** (1.0 / 12.0)  # ~1.05946 (1/12th octave stop condition)
    MAX_EDGE_TESTS = 6
    LOW_ROLLOFF_LIMIT = 250.0  # Structural roll-off zone limit for small laptop speakers
    CONTROL_VARIATION_LIMIT = 3.0

    # Quick: start at 250 Hz — 125 Hz is below the roll-off threshold for most
    # small laptop speakers and is marked EXPECTED_LOW_ROLLOFF; starting at
    # 250 avoids an inaudible first tone that users mistake for hardware failure.
    # Users who need sub-bass can use Detailed (63-16k) or set --quick-start-hz.
    QUICK_GRID = [250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]
    
    DETAILED_GRID = [
        63.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0, 315.0, 400.0, 500.0,
        630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0, 2500.0, 3150.0,
        4000.0, 5000.0, 6300.0, 8000.0, 10000.0, 12500.0, 16000.0
    ]


class DiagnosticController:
    """
    Test controller managing the adaptive diagnostic lifecycle for speaker channels.
    """

    def __init__(self, mode: str = "detailed"):
        self.mode = mode
        self.config = DiagnosticConfig()
        self.grid = self.config.QUICK_GRID if mode == "quick" else self.config.DETAILED_GRID

    @staticmethod
    def rating_anchor(measurements: List[Measurement]) -> float:
        """
        Calculate personal calibration baseline anchor with a resilient fallback hierarchy:
        1. Median clarity of heard 1 kHz control tones (if >= 2 heard).
        2. Median quality of heard coarse tones > 200 Hz (if >= 4 heard).
        3. Standard nominal anchor of 8.0.
        """
        controls = [
            float(m.clarity) for m in measurements
            if (m.stage == Stage.CONTROL or m.is_control) and not m.input_error and m.heard
        ]
        if len(controls) >= 2:
            return float(np.median(controls))

        mid_high_coarse = [
            m.quality for m in measurements
            if m.stage == Stage.COARSE and not m.input_error and m.heard and m.frequency_hz > 200.0
        ]
        if len(mid_high_coarse) >= 4:
            return float(np.median(mid_high_coarse))

        return 8.0

    @classmethod
    def effective_classification(
        cls,
        m: Measurement,
        anchor: Optional[float] = None,
        local_baseline: Optional[float] = None
    ) -> str:
        """
        Determine effective discrete classification combining anchor-relative and local-relative deviation.
        Enforces a strict absolute floor (quality <= 2.0 is always BAD) to prevent whitewashing genuinely dead hardware,
        and clamps effective anchor to >= 5.0 to prevent detection window collapse on very low anchors.
        """
        if not m.heard:
            return Classification.BAD
        if m.quality <= 2.0:
            return Classification.BAD

        raw_anchor = anchor if anchor is not None else 8.0
        eff_anchor = max(5.0, raw_anchor)

        # 1. Anchor-relative classification
        if m.quality >= eff_anchor - 1.5:
            anchor_class = Classification.GOOD
        elif m.quality >= eff_anchor - 3.0:
            anchor_class = Classification.BORDERLINE
        else:
            anchor_class = Classification.BAD

        # 2. Local-relative classification (if local baseline is provided)
        if local_baseline is not None:
            eff_local = max(5.0, local_baseline)
            if m.quality >= eff_local - 1.5:
                local_class = Classification.GOOD
            elif m.quality >= eff_local - 3.0:
                local_class = Classification.BORDERLINE
            else:
                local_class = Classification.BAD
        else:
            local_class = anchor_class

        # Return worse of anchor / local classifications
        if anchor_class == Classification.BAD or local_class == Classification.BAD:
            return Classification.BAD
        if anchor_class == Classification.BORDERLINE or local_class == Classification.BORDERLINE:
            return Classification.BORDERLINE
        return Classification.GOOD

    @staticmethod
    def calculate_quality(heard: bool, clarity: int, distortion: Optional[int] = None) -> Tuple[float, str]:
        """
        Calculate composite quality score and discrete classification.
        """
        if not heard:
            return 0.0, Classification.BAD
        
        clarity_val = float(max(0, min(10, clarity)))
        if distortion is not None and distortion > 0:
            quality = max(0.0, clarity_val - 0.4 * float(distortion))
        else:
            quality = clarity_val

        if quality >= 7.0:
            cls = Classification.GOOD
        elif quality >= 4.0:
            cls = Classification.BORDERLINE
        else:
            cls = Classification.BAD

        return round(quality, 2), cls

    @classmethod
    def check_global_abort(cls, measurements: List[Measurement]) -> Tuple[bool, str]:
        """
        Abort refinement with 3-way diagnosis:
        - GLOBAL_OUTPUT_FAILURE: heard_ratio < 0.25 or severe driver/mute crash.
        - GLOBAL_OUTPUT_UNCERTAIN: 0.25 <= heard_ratio < 0.75 with poor quality (< 3.5).
        - RATING_SCALE_LOW: heard_ratio >= 0.75, anchor <= 4.0 or no effectively-GOOD points, low average, and NO localized dips.
        Classification is anchor-relative: a rater whose personal scale never uses 7+ but who anchors
        consistently (e.g. uniform 6.5 with dips detectable relative to their own baseline) must NOT
        be aborted, so only the effective (anchor-relative) GOOD count participates in this decision.
        If localized dips exist even under conservative ratings, allows testing to proceed to catch defects.
        """
        mid_high_coarse = [
            m for m in measurements
            if m.stage == Stage.COARSE and m.frequency_hz > 200.0 and not m.input_error
        ]
        if len(mid_high_coarse) < 4:
            return False, ""
        
        heard_count = sum(1 for m in mid_high_coarse if m.heard)
        heard_ratio = heard_count / float(len(mid_high_coarse))
        avg_mid_high = sum(m.quality for m in mid_high_coarse) / float(len(mid_high_coarse))

        anchor = cls.rating_anchor(measurements)
        good_count = sum(1 for m in mid_high_coarse if cls.effective_classification(m, anchor) == Classification.GOOD)
        bad_count = sum(1 for m in mid_high_coarse if cls.effective_classification(m, anchor) == Classification.BAD)
        bad_ratio = bad_count / float(len(mid_high_coarse))

        if heard_ratio < 0.25:
            return True, "GLOBAL_OUTPUT_FAILURE"

        if 0.25 <= heard_ratio < 0.75 and avg_mid_high < 3.5:
            return True, "GLOBAL_OUTPUT_UNCERTAIN"

        if heard_ratio >= 0.75 and (anchor <= 4.0 or good_count == 0):
            # Check if there is a strong localized dip relative to rater's own cluster
            qualities = [m.quality for m in mid_high_coarse]
            med_q = float(np.median(qualities))
            has_strong_dip = any((med_q - q >= 3.0 or q <= 2.0) for q in qualities)
            if has_strong_dip:
                return False, ""  # Keep testing to capture localized defect!

            if avg_mid_high >= 3.0 or anchor <= 4.0:
                return True, "RATING_SCALE_LOW"
            return True, "GLOBAL_OUTPUT_FAILURE"

        if avg_mid_high < 2.5 or bad_ratio > 0.75:
            return True, "GLOBAL_OUTPUT_FAILURE"

        return False, ""

    @staticmethod
    def check_early_output_failure(measurements: List[Measurement], min_points: int = 6) -> bool:
        """
        Mid-coarse dead-output guard: True when at least `min_points` coarse tones
        above 200 Hz have been rated and none were heard. The midrange is where
        even tiny laptop drivers are plainly audible, so hearing none of it means
        the output chain is muted/dead long before the full coarse pass finishes.
        """
        rated = [
            m for m in measurements
            if m.stage == Stage.COARSE and m.frequency_hz > 200.0 and not m.input_error
        ]
        if len(rated) < min_points:
            return False
        return not any(m.heard for m in rated)

    @staticmethod
    def check_control_stability(measurements: List[Measurement]) -> bool:
        """
        Return True if 1 kHz control tone responses are stable.
        For >= 3 controls, checks standard deviation <= 1.2; otherwise range <= 3.
        """
        controls = [m for m in measurements if (m.stage == Stage.CONTROL or m.is_control) and not m.input_error and m.heard]
        if len(controls) < 2:
            return True
        clarities = [float(m.clarity) for m in controls]
        if (max(clarities) - min(clarities)) > DiagnosticConfig.CONTROL_VARIATION_LIMIT:
            return False
        if len(controls) >= 3:
            return float(np.std(clarities)) <= 1.2
        return True

    @classmethod
    def estimate_local_baseline(cls, measurements: List[Measurement], target_freq: float, channel: Optional[str] = None) -> float:
        """
        Compute local baseline clarity: median clarity of GOOD points within +/- 1 octave.
        """
        octave_low = target_freq / 2.0
        octave_high = target_freq * 2.0
        anchor = cls.rating_anchor(measurements)

        good_points = [
            m.quality for m in measurements
            if not m.input_error and not m.is_control and cls.effective_classification(m, anchor) == Classification.GOOD
            and (channel is None or m.channel == channel)
            and (octave_low <= m.frequency_hz <= octave_high)
        ]

        if not good_points:
            good_points = [
                m.quality for m in measurements
                if not m.input_error and not m.is_control and cls.effective_classification(m, anchor) == Classification.GOOD
                and (channel is None or m.channel == channel)
            ]

        if not good_points:
            return anchor

        return float(np.median(good_points))

    @classmethod
    def find_isolated_bad_points(cls, measurements: List[Measurement], channel: Optional[str] = None) -> List[Measurement]:
        """
        Identify coarse measurements that are BAD or BORDERLINE but whose neighbors are GOOD,
        using effective classification relative to anchor and local baseline.
        """
        coarse = [
            m for m in measurements
            if m.stage == Stage.COARSE and not m.input_error and (channel is None or m.channel == channel)
        ]
        coarse = sorted(coarse, key=lambda x: x.frequency_hz)
        anchor = cls.rating_anchor(measurements)
        isolated = []
        for i in range(len(coarse)):
            curr = coarse[i]
            local_base = cls.estimate_local_baseline(coarse, curr.frequency_hz, channel)
            curr_cls = cls.effective_classification(curr, anchor, local_base)
            if curr_cls in (Classification.BAD, Classification.BORDERLINE):
                # Sub-160 Hz roll-off is expected on laptops and not treated as an isolated flaw
                if curr.frequency_hz <= 160.0:
                    continue
                # Hearing threshold guard: skip >= 10 kHz inaudibility if isolated
                if curr.frequency_hz >= 10000.0 and not curr.heard:
                    continue

                prev_p = coarse[i - 1] if i > 0 else None
                next_p = coarse[i + 1] if i < len(coarse) - 1 else None

                prev_good = prev_p is not None and cls.effective_classification(prev_p, anchor) == Classification.GOOD
                next_good = next_p is not None and cls.effective_classification(next_p, anchor) == Classification.GOOD

                if prev_p and next_p:
                    if prev_good and next_good:
                        isolated.append(curr)
                elif prev_p and not next_p:
                    if prev_good:
                        isolated.append(curr)
                elif next_p and not prev_p:
                    if next_good:
                        isolated.append(curr)
        return isolated

    @classmethod
    def resolve_isolated_retest(cls, original: Measurement, retest: Measurement, anchor: Optional[float] = None):
        """
        Automatically update flags on original measurement based on retest result using effective classification.
        """
        if cls.effective_classification(retest, anchor) == Classification.GOOD:
            original.input_error = True
            original.verified_suspicious = False
        else:
            original.input_error = False
            original.verified_suspicious = True

    @classmethod
    def is_low_rolloff(cls, region: Region, measurements: List[Measurement]) -> bool:
        """
        Structural roll-off check: True if region is in the bass zone (<= 250 Hz)
        and clean reproduction recovers within an octave above the region.
        """
        if region.f_high > DiagnosticConfig.LOW_ROLLOFF_LIMIT:
            return False
        
        anchor = cls.rating_anchor(measurements)
        goods_above = [
            m.frequency_hz for m in measurements
            if not m.input_error and cls.effective_classification(m, anchor) == Classification.GOOD and m.frequency_hz > region.f_high
        ]
        return bool(goods_above) and min(goods_above) <= region.f_high * 2.0

    @classmethod
    def detect_regions(cls, measurements: List[Measurement], channel: str) -> List[Region]:
        """
        Detect contiguous runs of non-GOOD points from active measurements,
        aggregating duplicate frequencies, computing boundary estimates, and filtering control artifacts.
        Uses anchor-relative and local-relative classification.
        """
        chan_measurements = [
            m for m in measurements
            if m.channel == channel and not m.input_error and not m.is_control and m.stage not in (Stage.MANUAL, Stage.SWEEP, Stage.CONTROL)
        ]

        anchor = cls.rating_anchor(measurements)

        # Map measurements by frequency (favoring retests/refinements over raw coarse)
        freq_map: Dict[float, Measurement] = {}
        for m in chan_measurements:
            f = round(m.frequency_hz, 1)
            if f not in freq_map or m.is_retest or m.stage == Stage.REFINE:
                freq_map[f] = m

        valid_points = sorted(freq_map.values(), key=lambda x: x.frequency_hz)
        good_points = [p for p in valid_points if cls.effective_classification(p, anchor) == Classification.GOOD]

        raw_regions = []
        current_run: List[Measurement] = []

        for p in valid_points:
            local_base = cls.estimate_local_baseline(valid_points, p.frequency_hz, channel)
            eff_cls = cls.effective_classification(p, anchor, local_base)
            if eff_cls in (Classification.BAD, Classification.BORDERLINE):
                current_run.append(p)
            else:
                if current_run:
                    raw_regions.append(current_run)
                    current_run = []
        if current_run:
            raw_regions.append(current_run)

        regions = []
        for idx, pts in enumerate(raw_regions):
            f_low = min(p.frequency_hz for p in pts)
            f_high = max(p.frequency_hz for p in pts)
            center = math.sqrt(f_low * f_high)
            min_q = min(p.quality for p in pts)
            local_base = cls.estimate_local_baseline(valid_points, center, channel)
            
            # Deterministic tie-breaking for worst measured point
            worst_pt = min(pts, key=lambda p: (p.quality, -(local_base - p.quality), p.frequency_hz))
            worst_f = worst_pt.frequency_hz
            avg_q = round(sum(p.quality for p in pts) / float(len(pts)), 1)

            bad_count = sum(1 for p in pts if cls.effective_classification(p, anchor, local_base) == Classification.BAD)
            borderline_count = sum(1 for p in pts if cls.effective_classification(p, anchor, local_base) == Classification.BORDERLINE)
            effective_bad = float(bad_count) + 0.5 * float(borderline_count)

            # Determine boundary estimates using nearest GOOD anchors
            goods_below = [g.frequency_hz for g in good_points if g.frequency_hz < f_low]
            goods_above = [g.frequency_hz for g in good_points if g.frequency_hz > f_high]

            if goods_below:
                start_est = math.sqrt(max(goods_below) * f_low)
                lower_open = False
            else:
                start_est = f_low
                lower_open = True

            if goods_above:
                end_est = math.sqrt(f_high * min(goods_above))
                upper_open = False
            else:
                end_est = f_high
                upper_open = True

            # Bracket uncertainty estimation
            ratio_low = (f_low / max(1.0, start_est)) if not lower_open else 2.0
            ratio_high = (end_est / max(1.0, f_high)) if not upper_open else 2.0
            max_ratio = max(ratio_low, ratio_high)
            unc_pct = min(50.0, max(3.0, round((math.sqrt(max_ratio) - 1.0) * 100.0)))

            is_point = (len(pts) == 1 and not any(p.stage == Stage.REFINE for p in pts))

            reg = Region(
                region_id=f"reg_{channel}_{idx+1}",
                channel=channel,
                f_low=f_low,
                f_high=f_high,
                center_frequency=center,
                min_quality=min_q,
                baseline_quality=local_base,
                depth=max(0.0, local_base - min_q),
                effective_bad_count=effective_bad,
                anomaly_confidence=0,
                hardware_confidence=0,
                category=RegionCategory.PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE,
                evidence="",
                worst_frequency=worst_f,
                avg_quality=avg_q,
                severity="Uncertain",
                uncertainty_pct=unc_pct,
                start_estimate=round(start_est, 1),
                end_estimate=round(end_est, 1),
                lower_boundary_open=lower_open,
                upper_boundary_open=upper_open,
                is_point_anomaly=is_point,
                points=pts
            )
            regions.append(reg)

        return regions

    @classmethod
    def expand_region_boundaries(cls, region: Region, all_measurements: List[Measurement]) -> Region:
        """
        Estimate the true start and end boundaries of a region using nearest GOOD anchors
        from coarse and refined measurements.
        """
        valid = sorted(
            [m for m in all_measurements if not m.input_error and not m.is_control and m.stage not in (Stage.MANUAL, Stage.SWEEP, Stage.CONTROL) and m.channel == region.channel],
            key=lambda x: x.frequency_hz
        )

        if not region.points:
            return region

        anchor = cls.rating_anchor(all_measurements)
        first_bad = min(p.frequency_hz for p in region.points)
        last_bad = max(p.frequency_hz for p in region.points)
        local_base = cls.estimate_local_baseline(all_measurements, region.center_frequency, region.channel)

        worst_pt = min(region.points, key=lambda p: (p.quality, -(local_base - p.quality), p.frequency_hz))
        region.worst_frequency = worst_pt.frequency_hz
        region.avg_quality = round(sum(p.quality for p in region.points) / float(len(region.points)), 1)

        left_goods = [
            m.frequency_hz for m in valid
            if m.frequency_hz < first_bad and cls.effective_classification(m, anchor) == Classification.GOOD
        ]

        right_goods = [
            m.frequency_hz for m in valid
            if m.frequency_hz > last_bad and cls.effective_classification(m, anchor) == Classification.GOOD
        ]

        if left_goods:
            nearest_good_low = max(left_goods)
            region.start_estimate = round(math.sqrt(nearest_good_low * first_bad), 1)
            region.lower_boundary_open = False
        else:
            region.start_estimate = first_bad
            region.lower_boundary_open = True

        if right_goods:
            nearest_good_high = min(right_goods)
            region.end_estimate = round(math.sqrt(last_bad * nearest_good_high), 1)
            region.upper_boundary_open = False
        else:
            region.end_estimate = last_bad
            region.upper_boundary_open = True

        if region.end_estimate < region.start_estimate:
            region.start_estimate, region.end_estimate = region.end_estimate, region.start_estimate

        region.center_frequency = round(math.sqrt(region.start_estimate * region.end_estimate), 1)

        ratio_low = (first_bad / max(1.0, region.start_estimate)) if not region.lower_boundary_open else 2.0
        ratio_high = (region.end_estimate / max(1.0, last_bad)) if not region.upper_boundary_open else 2.0
        max_ratio = max(ratio_low, ratio_high)
        region.uncertainty_pct = min(50.0, max(3.0, round((math.sqrt(max_ratio) - 1.0) * 100.0)))

        return region

    @classmethod
    def score_region(
        cls,
        region: Region,
        all_measurements: List[Measurement],
        fxsound_disabled: bool = True,
        enhancements_disabled: bool = True
    ) -> Region:
        """
        Calculate mathematical confidence scores, handle single-point caps, and categorize region.
        """
        anchor = cls.rating_anchor(all_measurements)
        baseline = cls.estimate_local_baseline(all_measurements, region.center_frequency, region.channel)
        region.baseline_quality = baseline

        reg_points = region.points
        bad_count = sum(1 for p in reg_points if cls.effective_classification(p, anchor, baseline) == Classification.BAD)
        borderline_count = sum(1 for p in reg_points if cls.effective_classification(p, anchor, baseline) == Classification.BORDERLINE)
        
        effective_bad = float(bad_count) + 0.5 * float(borderline_count)
        region.effective_bad_count = effective_bad

        if reg_points:
            worst_pt = min(reg_points, key=lambda p: (p.quality, -(baseline - p.quality), p.frequency_hz))
            region.worst_frequency = worst_pt.frequency_hz
            region.avg_quality = round(sum(p.quality for p in reg_points) / float(len(reg_points)), 1)

        # 1. Consistency score
        consistency_score = min(1.0, effective_bad / 3.0)

        # 2. Depth score relative to local baseline
        depth = max(0.0, baseline - region.min_quality)
        region.depth = depth
        depth_score = min(1.0, depth / 6.0)

        # 3. Retest agreement score
        retests = [p for p in reg_points if p.is_retest]
        has_verified_retest = any(
            p.is_retest and cls.effective_classification(p, anchor, baseline) in (Classification.BAD, Classification.BORDERLINE)
            for p in reg_points
        )
        if not retests:
            retest_score = 0.35
        else:
            matching = sum(1 for p in retests if cls.effective_classification(p, anchor, baseline) in (Classification.BAD, Classification.BORDERLINE))
            retest_score = 0.35 + 0.65 * (matching / float(len(retests)))

        # 4. Control tone stability score
        controls_ok = cls.check_control_stability(all_measurements)
        control_score = 1.0 if controls_ok else 0.5

        # 5. Plausibility score based on region width in octaves
        if region.f_low > 0 and region.f_high > region.f_low:
            width_octaves = math.log2(region.f_high / region.f_low)
        else:
            width_octaves = 0.0

        if (1.0 / 12.0) <= width_octaves <= 2.0:
            plausibility_score = 1.0
        elif width_octaves < (1.0 / 24.0):
            plausibility_score = 0.6
        else:
            plausibility_score = 0.7

        # Composite anomaly confidence (0 - 95%)
        raw_anomaly = 100.0 * (
            0.35 * consistency_score +
            0.25 * depth_score +
            0.20 * retest_score +
            0.10 * control_score +
            0.10 * plausibility_score
        )
        anomaly_conf = min(95, max(10, int(round(raw_anomaly))))

        # Apply single-point outlier safety cap
        if effective_bad < 2.0 and not has_verified_retest:
            anomaly_conf = min(anomaly_conf, 35)
            region.category = RegionCategory.INCONCLUSIVE
        elif effective_bad < 2.0 and has_verified_retest:
            anomaly_conf = min(anomaly_conf, 55)
            region.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE

        region.anomaly_confidence = anomaly_conf

        # Check for Expected Low-Frequency Roll-Off using structural predicate
        is_rolloff = cls.is_low_rolloff(region, all_measurements)

        # High frequency hearing threshold guard
        is_hf_hearing_limit = (region.f_low >= 10000.0 and all(not p.heard for p in reg_points))

        # Check for elevated distortion on audible tones (mechanical buzz / driver clipping)
        high_dist_pts = [p for p in reg_points if p.distortion is not None and p.distortion >= 5 and p.clarity >= 6]

        # Hardware Attribution Confidence
        hardware_mult = 1.0
        if is_rolloff:
            hardware_mult *= 0.20
            region.category = RegionCategory.EXPECTED_LOW_ROLLOFF
        elif is_hf_hearing_limit:
            hardware_mult *= 0.35  # Allows moderate cap (~35-45%) for unilateral loss pending cross-channel check
            anomaly_conf = min(anomaly_conf, 50)
            region.anomaly_confidence = anomaly_conf
            if region.category not in (RegionCategory.INCONCLUSIVE, RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE):
                region.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE
        elif high_dist_pts and region.category not in (RegionCategory.EXPECTED_LOW_ROLLOFF, RegionCategory.INCONCLUSIVE):
            region.category = RegionCategory.LIKELY_LEVEL_DEPENDENT_DISTORTION
            hardware_mult *= 0.70
        elif not (fxsound_disabled and enhancements_disabled):
            hardware_mult *= 0.30
            region.category = RegionCategory.LIKELY_DSP_OR_ENHANCEMENT_EFFECT
        elif not controls_ok:
            hardware_mult *= 0.60
            region.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE
        elif region.category not in (RegionCategory.INCONCLUSIVE, RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE):
            if anomaly_conf >= 80:
                region.category = RegionCategory.PERCEIVED_ANOMALY_HIGH_CONFIDENCE
            elif anomaly_conf >= 50:
                region.category = RegionCategory.PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE
            else:
                region.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE

        raw_hw = anomaly_conf * hardware_mult
        region.hardware_confidence = min(95, max(5, int(round(raw_hw))))

        # Determine Severity Tier
        if region.category == RegionCategory.NO_ISSUE:
            region.severity = "No significant anomaly"
        elif region.category == RegionCategory.EXPECTED_LOW_ROLLOFF:
            region.severity = "Expected low-frequency roll-off"
        elif region.category == RegionCategory.INCONCLUSIVE or region.anomaly_confidence < 40:
            region.severity = "Uncertain"
        elif region.anomaly_confidence < 60 and region.depth < 3.0:
            region.severity = "Minor"
        elif region.anomaly_confidence < 80 or region.depth <= 5.0:
            region.severity = "Moderate"
        else:
            region.severity = "Strong"

        # Evidence String
        ev_parts = []
        ev_parts.append(f"{len(reg_points)} test points in range (min clarity: {region.min_quality:.1f}/10)")
        if retests:
            ev_parts.append("re-test confirmed dip")
        if depth >= 3.0:
            ev_parts.append(f"clarity drop of {depth:.1f} pts below local baseline ({baseline:.1f})")
        if is_rolloff:
            ev_parts.append("expected laptop acoustic roll-off in bass zone")
        if is_hf_hearing_limit:
            ev_parts.append("extreme high-frequency inaudibility may reflect listener hearing thresholds (verify with headphones)")
        if high_dist_pts:
            max_d = max(p.distortion for p in high_dist_pts if p.distortion is not None)
            ev_parts.append(f"elevated distortion ({max_d}/10) on audible tone suggests mechanical/driver clipping")
        region.evidence = "; ".join(ev_parts)

        return region

    @classmethod
    def evaluate_cross_channel(cls, session: Session) -> str:
        """
        Perform Left vs Right differential comparison (Idempotent).
        """
        left_res = session.channel_results.get("left")
        right_res = session.channel_results.get("right")

        if not left_res or not right_res:
            return "Single-channel mode tested. Cross-channel comparison not applicable."

        # Guard: If either channel suffered global output failure / uncertain / rating low, short-circuit
        if left_res.is_global_problem or right_res.is_global_problem:
            issues = []
            if left_res.is_global_problem:
                issues.append(f"Left channel: {left_res.global_problem_type or 'Global problem'}")
            if right_res.is_global_problem:
                issues.append(f"Right channel: {right_res.global_problem_type or 'Global problem'}")
            return f"• Global problem state active ({', '.join(issues)}).\n  -> Interpretation: Cross-channel balance cannot be reliably evaluated until system volume, playback device, or audio driver state is resolved."

        left_regions = [r for r in left_res.regions if r.category != RegionCategory.EXPECTED_LOW_ROLLOFF]
        right_regions = [r for r in right_res.regions if r.category != RegionCategory.EXPECTED_LOW_ROLLOFF]

        findings = []

        if not left_regions and not right_regions:
            findings.append("Both Left and Right channels exhibit balanced, clean frequency response.")
            return "\n".join(findings)

        # Check for matching / symmetrical anomalies
        matched_pairs = []
        for l_reg in left_regions:
            for r_reg in right_regions:
                ratio = max(l_reg.center_frequency, r_reg.center_frequency) / max(1.0, min(l_reg.center_frequency, r_reg.center_frequency))
                if ratio <= (2.0 ** (1.0 / 6.0)):
                    matched_pairs.append((l_reg, r_reg))

        enh_disabled = session.fxsound_disabled and session.enhancements_disabled
        dsp_mult = 1.0 if enh_disabled else 0.30

        if matched_pairs:
            for l_reg, r_reg in matched_pairs:
                is_hf_matched = (
                    l_reg.f_low >= 8000.0 and r_reg.f_low >= 8000.0 and
                    (all(not p.heard for p in l_reg.points) or l_reg.avg_quality <= 1.0) and
                    (all(not p.heard for p in r_reg.points) or r_reg.avg_quality <= 1.0)
                )
                if is_hf_matched:
                    findings.append(
                        f"• Symmetrical high-frequency roll-off detected on BOTH channels above ~{l_reg.f_low:.0f} Hz."
                    )
                    findings.append(
                        "  -> Interpretation: Identical high-frequency roll-off across both channels is most consistent with normal"
                    )
                    findings.append(
                        "     human hearing threshold limits or standard ultrasonic speaker driver filtering; physical hardware defect is unlikely."
                    )
                    l_reg.hardware_confidence = min(25, l_reg.hardware_confidence)
                    r_reg.hardware_confidence = min(25, r_reg.hardware_confidence)
                    l_reg.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE
                    r_reg.category = RegionCategory.PERCEIVED_ANOMALY_LOW_CONFIDENCE
                else:
                    findings.append(
                        f"• Symmetrical dip detected on BOTH channels around ~{l_reg.center_frequency:.0f} Hz."
                    )
                    findings.append(
                        "  -> Interpretation: Identical dual-channel notches strongly suggest active DSP/equalization,"
                    )
                    findings.append(
                        "     audio driver filtering, or room acoustic standing waves rather than two identical physical driver faults."
                    )
                    l_reg.hardware_confidence = min(95, max(5, int(l_reg.anomaly_confidence * 0.45 * dsp_mult)))
                    r_reg.hardware_confidence = min(95, max(5, int(r_reg.anomaly_confidence * 0.45 * dsp_mult)))
                    l_reg.category = RegionCategory.LIKELY_DSP_OR_ENHANCEMENT_EFFECT
                    r_reg.category = RegionCategory.LIKELY_DSP_OR_ENHANCEMENT_EFFECT

        # Check for one-sided anomalies
        for l_reg in left_regions:
            if not any(p[0] == l_reg for p in matched_pairs):
                findings.append(
                    f"• Asymmetrical anomaly on LEFT channel at {l_reg.f_low:.0f}–{l_reg.f_high:.0f} Hz (Right channel is normal)."
                )
                findings.append(
                    "  -> Interpretation: Higher likelihood of physical Left speaker hardware anomaly. Verify with headphones to rule out hearing asymmetry."
                )
                l_reg.hardware_confidence = min(95, max(5, int(round(l_reg.anomaly_confidence * 1.15 * dsp_mult))))

        for r_reg in right_regions:
            if not any(p[1] == r_reg for p in matched_pairs):
                findings.append(
                    f"• Asymmetrical anomaly on RIGHT channel at {r_reg.f_low:.0f}–{r_reg.f_high:.0f} Hz (Left channel is normal)."
                )
                findings.append(
                    "  -> Interpretation: Higher likelihood of physical Right speaker hardware anomaly. Verify with headphones to rule out hearing asymmetry."
                )
                r_reg.hardware_confidence = min(95, max(5, int(round(r_reg.anomaly_confidence * 1.15 * dsp_mult))))

        return "\n".join(findings)


class TestScheduler:
    """
    Pure, GUI-independent test scheduler managing queueing, deduplication,
    isolated retesting, and bounded adaptive bisection refinement.
    """

    def __init__(self, mode: str = "detailed"):
        self.mode = mode
        self.config = DiagnosticConfig()
        self.grid = self.config.QUICK_GRID if mode == "quick" else self.config.DETAILED_GRID
        self.channel: str = "left"
        self.test_queue: List[Dict[str, Any]] = []
        self.current_idx: int = 0
        self.pending_freqs: set = set()
        self.edge_attempts: Dict[Tuple, int] = {}
        self.global_refine_count: int = 0
        self.active_measurements: List[Measurement] = []
        self.manual_mode: bool = False

    def load_manual_queue(self, freqs: List[float], stage: str = Stage.SWEEP):
        """
        Replace the queue with a fixed, user-driven sequence (e.g. sweep marker
        retests). Manual mode skips all adaptive phase transitions.
        """
        self.start_channel(self.channel)
        self.test_queue.clear()
        self.current_idx = 0
        self.pending_freqs.clear()
        self.manual_mode = True
        for f in freqs:
            key = round(float(f), 1)
            self.pending_freqs.add(key)
            self.test_queue.append({
                "freq": key,
                "stage": stage,
                "is_retest": True,
                "is_control": False
            })

    def undo_last_measurement(self):
        """
        Step back one rating: drop the newest measurement and rewind the queue
        cursor so the same test item is presented again. Also reverts the side
        effects the measurement may have recorded: a retest resolved its original
        coarse point (input_error / verified_suspicious flags); restore the
        pre-resolution state so the original is judged again. Refine budget is
        NOT refunded — it is consumed when the item is enqueued, and the queue
        item survives undo, so the slot is re-rated without a new charge.
        """
        if not self.active_measurements or self.current_idx <= 0:
            return
        m = self.active_measurements.pop()
        self.pending_freqs.add(round(float(m.frequency_hz), 1))
        self.current_idx -= 1
        if m.is_retest:
            for orig in self.active_measurements:
                if orig.stage == Stage.COARSE and abs(orig.frequency_hz - m.frequency_hz) < 1.0:
                    orig.input_error = False
                    orig.verified_suspicious = False

    def start_channel(self, channel: str):
        """
        Reset per-channel state and enqueue coarse grid and periodic control tones.
        """
        self.channel = channel
        self.test_queue.clear()
        self.current_idx = 0
        self.pending_freqs.clear()
        self.edge_attempts.clear()
        self.global_refine_count = 0
        self.active_measurements.clear()

        control_interval = 3 if self.mode == "quick" else 8
        for i, freq in enumerate(self.grid):
            self.enqueue(freq, Stage.COARSE)
            if (i % control_interval == control_interval - 1) and freq != 1000.0:
                self.enqueue(1000.0, Stage.CONTROL, is_control=True)

    def enqueue(self, freq: float, stage: str, is_retest: bool = False, is_control: bool = False) -> bool:
        """
        Stage-aware test enqueueing with duplicate prevention.
        """
        key = round(float(freq), 1)
        if not is_control and key in self.pending_freqs:
            return False

        if stage == Stage.RETEST:
            already_retested = any(
                m.is_retest and abs(m.frequency_hz - key) < 1.0
                for m in self.active_measurements
            )
            if already_retested:
                return False
        elif not is_control:
            already_measured = any(
                abs(m.frequency_hz - key) < 1.0
                for m in self.active_measurements
            )
            if already_measured:
                return False

        if not is_control:
            self.pending_freqs.add(key)
        self.test_queue.append({
            "freq": key,
            "stage": stage,
            "is_retest": is_retest,
            "is_control": is_control
        })
        return True

    def get_current_test(self) -> Optional[Dict[str, Any]]:
        if self.current_idx < len(self.test_queue):
            item = self.test_queue[self.current_idx]
            return item
        return None

    def record_measurement(self, m: Measurement, controller: Optional[DiagnosticController] = None):
        self.active_measurements.append(m)
        self.pending_freqs.discard(round(float(m.frequency_hz), 1))
        if m.is_retest and controller:
            anchor = controller.rating_anchor(self.active_measurements)
            for orig in self.active_measurements:
                if orig.stage == Stage.COARSE and abs(orig.frequency_hz - m.frequency_hz) < 1.0:
                    controller.resolve_isolated_retest(orig, m, anchor)
        self.current_idx += 1

    def handle_phase_transition(self, controller: DiagnosticController) -> Tuple[str, str, int]:
        """
        Evaluates global abort, isolated retests, small region verification, and bisection refinement.
        Returns (action, reason_or_status, count_of_new_items).
        action in ("ABORT", "CONTINUE", "COMPLETE").
        """
        if self.manual_mode:
            return "COMPLETE", "MANUAL_QUEUE_DONE", 0

        is_abort, abort_reason = controller.check_global_abort(self.active_measurements)
        if is_abort:
            return "ABORT", abort_reason, 0

        initial_len = len(self.test_queue)

        # 1. Isolated bad point retests
        isolated = controller.find_isolated_bad_points(self.active_measurements, self.channel)
        for iso in isolated:
            self.enqueue(iso.frequency_hz, Stage.RETEST, is_retest=True)

        # 2. Small-region worst-point verification (< 3.0 effective bad count)
        # Using < 3.0 ensures 2-point BAD regions get verified, raising genuine dips to high confidence
        regions = controller.detect_regions(self.active_measurements, self.channel)
        for reg in regions:
            if not controller.is_low_rolloff(reg, self.active_measurements):
                # Skip inaudible extreme HF points (>= 10 kHz) as they represent normal hearing thresholds
                if reg.f_low >= 10000.0 and all(not p.heard for p in reg.points):
                    continue
                if reg.effective_bad_count < 3.0 and not any(p.is_retest for p in reg.points):
                    worst_pt = min(reg.points, key=lambda x: x.quality)
                    self.enqueue(worst_pt.frequency_hz, Stage.RETEST, is_retest=True)

        if len(self.test_queue) > initial_len:
            return "CONTINUE", "RETESTS_ADDED", len(self.test_queue) - initial_len

        # 3. Adaptive bisection refinement (Detailed mode)
        if self.mode == "detailed":
            anchor = controller.rating_anchor(self.active_measurements)
            sorted_pts = sorted(
                [p for p in self.active_measurements if not p.input_error and not p.is_control and p.stage not in (Stage.MANUAL, Stage.SWEEP, Stage.CONTROL)],
                key=lambda x: x.frequency_hz
            )

            for reg in regions:
                if controller.is_low_rolloff(reg, self.active_measurements):
                    continue

                # Lower transition bisection
                f_min_reg = reg.f_low
                lower_goods = [
                    p for p in sorted_pts
                    if p.frequency_hz < f_min_reg and controller.effective_classification(p, anchor) == Classification.GOOD
                ]
                if lower_goods:
                    f_good_low = max(p.frequency_hz for p in lower_goods)
                    lower_edge_key = (self.channel, "lower", round(f_good_low, 1))
                    attempts = self.edge_attempts.get(lower_edge_key, 0)
                    if (f_min_reg / f_good_low) > DiagnosticConfig.STOP_RATIO and attempts < DiagnosticConfig.MAX_EDGE_TESTS and self.global_refine_count < 24:
                        f_mid = round(math.sqrt(f_good_low * f_min_reg), 1)
                        if self.enqueue(f_mid, Stage.REFINE):
                            self.edge_attempts[lower_edge_key] = attempts + 1
                            self.global_refine_count += 1

                # Upper transition bisection
                f_max_reg = reg.f_high
                upper_goods = [
                    p for p in sorted_pts
                    if p.frequency_hz > f_max_reg and controller.effective_classification(p, anchor) == Classification.GOOD
                ]
                if upper_goods:
                    f_good_high = min(p.frequency_hz for p in upper_goods)
                    upper_edge_key = (self.channel, "upper", round(f_max_reg, 1))
                    attempts = self.edge_attempts.get(upper_edge_key, 0)
                    if (f_good_high / f_max_reg) > DiagnosticConfig.STOP_RATIO and attempts < DiagnosticConfig.MAX_EDGE_TESTS and self.global_refine_count < 24:
                        f_mid = round(math.sqrt(f_max_reg * f_good_high), 1)
                        if self.enqueue(f_mid, Stage.REFINE):
                            self.edge_attempts[upper_edge_key] = attempts + 1
                            self.global_refine_count += 1

        if len(self.test_queue) > initial_len:
            return "CONTINUE", "REFINEMENTS_ADDED", len(self.test_queue) - initial_len

        return "COMPLETE", "PHASE_DONE", 0


class RangeScanConfig:
    BAND_MIN_HZ = 20.0
    BAND_MAX_HZ = 20000.0
    COARSE_MAX_POINTS = 24
    MIN_STEP_HZ = 5.0
    REFINE_PROBES_PER_ROUND = 3  # at 25% / 50% / 75% of each open bracket
    MAX_ROUNDS_PER_BRACKET = 7
    MAX_REFINE_PROBES_TOTAL = 60
    BRACKET_CLOSE_WIDTH_HZ = 10.0  # bracket resolved at <= 10 Hz (±5 Hz accuracy)
    BAND_SILENT_RATIO = 0.20  # < 20% effectively-GOOD probes => whole-band shortcut


class RangeScanScheduler:
    """
    Boundary-refinement scheduler for Range Scan mode: a coarse linear probe pass
    across a user-selected band, then shrinking-step refinement (25/50/75% probes)
    of every GOOD<->NOT-GOOD transition until each bracket closes at ±5 Hz.

    Exposes the same interface as TestScheduler (get_current_test,
    record_measurement, handle_phase_transition, undo_last_measurement,
    active_measurements, test_queue, current_idx, manual_mode) so the existing
    Testing view drives it unchanged.
    """

    def __init__(self, f_start: float, f_end: float):
        self.config = RangeScanConfig()
        self.f_start = float(f_start)
        self.f_end = float(f_end)
        self.channel: str = "left"
        self.test_queue: List[Dict[str, Any]] = []
        self.current_idx: int = 0
        self.pending_freqs: set = set()
        self.active_measurements: List[Measurement] = []
        self.manual_mode: bool = False  # interface compatibility
        self.refine_probe_count: int = 0
        self._rounds_per_bracket: Dict[Tuple[float, float], int] = {}
        self._coarse_analyzed: bool = False
        self._complete: bool = False

    # ------------------------------------------------------------------ setup
    def validate_band(self):
        if not (self.config.BAND_MIN_HZ <= self.f_start < self.f_end <= self.config.BAND_MAX_HZ):
            raise ValueError(
                f"Invalid scan band {self.f_start:.0f}-{self.f_end:.0f} Hz: "
                f"requires {self.config.BAND_MIN_HZ:.0f} <= start < end <= {self.config.BAND_MAX_HZ:.0f} Hz."
            )

    def _build_coarse_queue(self):
        span = self.f_end - self.f_start
        step = max(span / (self.config.COARSE_MAX_POINTS - 1), self.config.MIN_STEP_HZ)
        n = min(self.config.COARSE_MAX_POINTS, int(span / step) + 1)
        freqs = [round(self.f_start + i * step, 1) for i in range(n)]
        if freqs[-1] < self.f_end - step * 0.5:
            freqs.append(round(self.f_end, 1))
        for f in freqs:
            self.enqueue(f)

    def start_channel(self, channel: str):
        self.channel = channel
        self.validate_band()
        self.test_queue = []
        self.current_idx = 0
        self.pending_freqs = set()
        self.active_measurements = []
        self.refine_probe_count = 0
        self._rounds_per_bracket = {}
        self._coarse_analyzed = False
        self._complete = False
        self._build_coarse_queue()

    def get_current_test(self) -> Optional[Dict[str, Any]]:
        if self.current_idx < len(self.test_queue):
            return self.test_queue[self.current_idx]
        return None

    def enqueue(self, freq: float) -> bool:
        key = round(float(freq), 1)
        if key in self.pending_freqs:
            return False
        if any(abs(m.frequency_hz - key) < 1.0 for m in self.active_measurements):
            return False
        self.pending_freqs.add(key)
        self.test_queue.append({
            "freq": key,
            "stage": Stage.RANGE,
            "is_retest": False,
            "is_control": False
        })
        return True

    def record_measurement(self, m: Measurement, controller: Optional[DiagnosticController] = None):
        self.active_measurements.append(m)
        self.pending_freqs.discard(round(float(m.frequency_hz), 1))
        self.current_idx += 1

    def undo_last_measurement(self):
        if not self.active_measurements or self.current_idx <= 0:
            return
        m = self.active_measurements.pop()
        self.pending_freqs.add(round(float(m.frequency_hz), 1))
        self.current_idx -= 1

    # ------------------------------------------------------- classification
    def _scan_anchor(self) -> float:
        """
        Personal anchor for the scan band: median quality of heard probes once
        >= 4 exist, else the standard 8.0 nominal. (Band probes are Stage.RANGE,
        so the coarse-grid fallback tiers of rating_anchor do not apply here.)
        """
        heard_q = [m.quality for m in self.active_measurements if not m.input_error and m.heard]
        if len(heard_q) >= 4:
            return float(np.median(heard_q))
        return 8.0

    def _is_good(self, m: Measurement, anchor: float) -> bool:
        return DiagnosticController.effective_classification(m, anchor) == Classification.GOOD

    # ----------------------------------------------------------- transitions
    def handle_phase_transition(self, controller: Optional[DiagnosticController] = None) -> Tuple[str, str, int]:
        """
        Called when the probe queue is exhausted. First call after the coarse
        pass applies the band-silent shortcut; then repeatedly refines every
        open GOOD<->NOT-GOOD bracket until all close (<= 10 Hz) or caps hit.
        Returns (action, reason, count_of_new_probes).
        """
        if self._complete:
            return "COMPLETE", "SCAN_DONE", 0

        rated = sorted(
            [m for m in self.active_measurements if not m.input_error],
            key=lambda x: x.frequency_hz
        )
        if len(rated) < 2:
            self._complete = True
            return "COMPLETE", "NO_DATA", 0

        anchor = self._scan_anchor()

        if not self._coarse_analyzed:
            self._coarse_analyzed = True
            good_count = sum(1 for m in rated if self._is_good(m, anchor))
            if good_count / float(len(rated)) < self.config.BAND_SILENT_RATIO:
                self._complete = True
                return "COMPLETE", "BAND_SILENT", 0

        initial_len = len(self.test_queue)
        for i in range(len(rated) - 1):
            a, b = rated[i], rated[i + 1]
            if self._is_good(a, anchor) == self._is_good(b, anchor):
                continue
            width = b.frequency_hz - a.frequency_hz
            if width <= self.config.BRACKET_CLOSE_WIDTH_HZ:
                continue
            key = (round(a.frequency_hz, 1), round(b.frequency_hz, 1))
            rounds = self._rounds_per_bracket.get(key, 0)
            if rounds >= self.config.MAX_ROUNDS_PER_BRACKET:
                continue
            added = 0
            for frac in (0.25, 0.50, 0.75):
                if self.refine_probe_count >= self.config.MAX_REFINE_PROBES_TOTAL:
                    break
                f = round(a.frequency_hz + width * frac, 1)
                if f - a.frequency_hz < 1.0 or b.frequency_hz - f < 1.0:
                    continue
                if self.enqueue(f):
                    self.refine_probe_count += 1
                    added += 1
            if added:
                self._rounds_per_bracket[key] = rounds + 1

        if len(self.test_queue) > initial_len:
            return "CONTINUE", "REFINEMENT_ADDED", len(self.test_queue) - initial_len

        self._complete = True
        return "COMPLETE", "SCAN_DONE", 0

    # --------------------------------------------------------------- regions
    def build_regions(self, controller: Optional[DiagnosticController] = None) -> List[Region]:
        """
        Convert contiguous NOT-GOOD probe runs into Region objects with
        bracket-based boundary estimates (arithmetic midpoints of the final
        GOOD/NOT-GOOD pairs — the scan grid is linear, not logarithmic).
        score_region() is applied afterwards by the caller for confidences.
        """
        rated = sorted(
            [m for m in self.active_measurements if not m.input_error],
            key=lambda x: x.frequency_hz
        )
        anchor = self._scan_anchor()

        regions: List[Region] = []
        runs: List[List[Measurement]] = []
        current: List[Measurement] = []
        for m in rated:
            if not self._is_good(m, anchor):
                current.append(m)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)

        for idx, pts in enumerate(runs):
            f_low = min(p.frequency_hz for p in pts)
            f_high = max(p.frequency_hz for p in pts)
            center = math.sqrt(f_low * f_high)
            min_q = min(p.quality for p in pts)
            local_base = anchor
            worst_pt = min(pts, key=lambda p: (p.quality, -(local_base - p.quality), p.frequency_hz))
            avg_q = round(sum(p.quality for p in pts) / float(len(pts)), 1)

            prev_good = next(
                (m.frequency_hz for m in reversed(rated)
                 if m.frequency_hz < f_low and self._is_good(m, anchor)),
                None
            )
            next_good = next(
                (m.frequency_hz for m in rated
                 if m.frequency_hz > f_high and self._is_good(m, anchor)),
                None
            )

            if prev_good is not None:
                start_est = round((prev_good + f_low) / 2.0, 1)
                lower_open = False
            else:
                start_est = f_low
                lower_open = True
            if next_good is not None:
                end_est = round((f_high + next_good) / 2.0, 1)
                upper_open = False
            else:
                end_est = f_high
                upper_open = True
            if end_est < start_est:
                start_est, end_est = end_est, start_est

            low_unc = ((f_low - start_est) / center * 100.0) if not lower_open else ((f_low - self.f_start) / center * 100.0)
            high_unc = ((end_est - f_high) / center * 100.0) if not upper_open else ((self.f_end - f_high) / center * 100.0)
            unc_pct = min(50.0, max(3.0, round(max(low_unc, high_unc), 1)))

            bad_count = sum(1 for p in pts if p.quality <= 2.0 or not p.heard)
            borderline_count = len(pts) - bad_count

            regions.append(Region(
                region_id=f"scan_{self.channel}_{idx + 1}",
                channel=self.channel,
                f_low=f_low,
                f_high=f_high,
                center_frequency=center,
                min_quality=min_q,
                baseline_quality=local_base,
                depth=max(0.0, local_base - min_q),
                effective_bad_count=float(bad_count) + 0.5 * float(borderline_count),
                anomaly_confidence=0,
                hardware_confidence=0,
                category=RegionCategory.PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE,
                evidence="",
                worst_frequency=worst_pt.frequency_hz,
                avg_quality=avg_q,
                severity="Uncertain",
                uncertainty_pct=unc_pct,
                start_estimate=start_est,
                end_estimate=end_est,
                lower_boundary_open=lower_open,
                upper_boundary_open=upper_open,
                is_point_anomaly=(len(pts) == 1),
                points=list(pts)
            ))

        return regions
