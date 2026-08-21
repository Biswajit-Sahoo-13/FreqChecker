"""
test_diagnostic.py - Comprehensive Unit & Integration tests for FreqChecker diagnostic algorithms,
adaptive test scheduler, and audio synthesis.
"""

import unittest
import numpy as np
import math
import random
import time
import threading

from models import (
    Measurement, Region, ChannelResult, Session,
    Classification, Stage, RegionCategory, practical_round_freq
)
from diagnostic_core import DiagnosticController, DiagnosticConfig, TestScheduler
from audio_engine import AudioEngine
import fx_theme


class TestAudioGeneration(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine(sample_rate=48000, default_peak=0.4)

    def test_sine_tone_generation(self):
        tone = self.engine.generate_sine_tone(1000.0, duration_s=1.0, peak=0.4, channel="both")
        self.assertEqual(tone.shape, (48000, 2))
        self.assertEqual(tone.dtype, np.float32)

        max_val = np.max(np.abs(tone))
        self.assertAlmostEqual(max_val, 0.4, places=2)

        mean_val = np.mean(tone)
        self.assertAlmostEqual(mean_val, 0.0, places=4)

        # Fade in & out verification
        self.assertLess(np.abs(tone[0, 0]), 0.05)
        self.assertLess(np.abs(tone[-1, 0]), 0.05)

        # FFT peak frequency verification
        left_ch = tone[:, 0]
        fft_vals = np.abs(np.fft.rfft(left_ch))
        freqs = np.fft.rfftfreq(len(left_ch), 1.0 / 48000.0)
        peak_freq = freqs[np.argmax(fft_vals)]
        self.assertAlmostEqual(peak_freq, 1000.0, delta=2.0)

    def test_channel_routing(self):
        tone_left = self.engine.generate_sine_tone(500.0, duration_s=0.5, channel="left")
        self.assertGreater(np.max(np.abs(tone_left[:, 0])), 0.3)
        self.assertEqual(np.max(np.abs(tone_left[:, 1])), 0.0)

        tone_right = self.engine.generate_sine_tone(500.0, duration_s=0.5, channel="right")
        self.assertEqual(np.max(np.abs(tone_right[:, 0])), 0.0)
        self.assertGreater(np.max(np.abs(tone_right[:, 1])), 0.3)

    def test_frequency_validation(self):
        with self.assertRaises(ValueError):
            self.engine.generate_sine_tone(-50.0)
        with self.assertRaises(ValueError):
            self.engine.generate_sine_tone(0.0)
        with self.assertRaises(ValueError):
            self.engine.generate_sine_tone(24000.0)  # Nyquist limit for 48kHz


class TestDiagnosticAlgorithm(unittest.TestCase):
    def setUp(self):
        self.controller = DiagnosticController(mode="detailed")

    def test_rating_anchor_fallback_hierarchy(self):
        """
        Verify rating_anchor fallback hierarchy:
        1. Median of heard 1 kHz controls (>= 2).
        2. Median of heard coarse > 200 Hz (>= 4).
        3. Default 8.0.
        """
        # Case 1: 2 valid controls
        m_controls = [
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.CONTROL, heard=True, clarity=6, is_control=True),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.CONTROL, heard=True, clarity=8, is_control=True),
        ]
        self.assertEqual(DiagnosticController.rating_anchor(m_controls), 7.0)

        # Case 2: Only 1 control -> fallback to coarse mid/high median
        m_fallback_coarse = [
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.CONTROL, heard=True, clarity=6, is_control=True),
            Measurement(frequency_hz=250.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=6),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=6),
            Measurement(frequency_hz=2000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=7),
        ]
        self.assertEqual(DiagnosticController.rating_anchor(m_fallback_coarse), 6.0)

        # Case 3: No controls, few points -> fallback to 8.0 default
        m_empty = []
        self.assertEqual(DiagnosticController.rating_anchor(m_empty), 8.0)

    def test_combined_effective_classification_anchor_and_local(self):
        """
        Verify that effective_classification combines anchor-relative and local-relative scoring,
        and enforces an absolute floor (quality <= 2.0 -> BAD).
        """
        # Absolute floor
        m_floor = Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2)
        self.assertEqual(DiagnosticController.effective_classification(m_floor, anchor=4.0, local_baseline=4.0), Classification.BAD)

        # Conservative rater relative baseline
        m_mid = Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=6)
        self.assertEqual(DiagnosticController.effective_classification(m_mid, anchor=6.0, local_baseline=6.0), Classification.GOOD)

        # Local dip relative to local baseline even if anchor is slightly lower
        m_dip = Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=4)
        self.assertEqual(DiagnosticController.effective_classification(m_dip, anchor=5.0, local_baseline=8.0), Classification.BAD)

    def test_3way_global_abort_split(self):
        """
        Verify the 3 global abort outcomes:
        - GLOBAL_OUTPUT_FAILURE (< 25% heard or driver dead)
        - GLOBAL_OUTPUT_UNCERTAIN (25%-75% heard with low quality)
        - RATING_SCALE_LOW (>= 75% heard, average low, no GOOD points, no localized dips)
        """
        # 1. Failure (all dead)
        dead = [Measurement(frequency_hz=f, channel="left", stage=Stage.COARSE, heard=False, clarity=0) for f in [250.0, 500.0, 1000.0, 2000.0, 4000.0]]
        self.assertEqual(self.controller.check_global_abort(dead), (True, "GLOBAL_OUTPUT_FAILURE"))

        # 2. Uncertain (partial audibility: 2/5 heard = 40%)
        uncertain = [
            Measurement(frequency_hz=250.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=2000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=3),
            Measurement(frequency_hz=4000.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
        ]
        self.assertEqual(self.controller.check_global_abort(uncertain), (True, "GLOBAL_OUTPUT_UNCERTAIN"))

        # 3. Rating Scale Low (all heard, quality = 4-5 uniformly without localized dips)
        rating_low = [Measurement(frequency_hz=f, channel="left", stage=Stage.COARSE, heard=True, clarity=5) for f in [250.0, 500.0, 1000.0, 2000.0, 4000.0]]
        self.assertEqual(self.controller.check_global_abort(rating_low), (True, "RATING_SCALE_LOW"))

    def test_global_abort_retains_strong_local_dips_under_low_ratings(self):
        """
        Verify that if the user rates conservatively (e.g. 5/10) but has a severe localized dip (e.g. 1/10 at 1 kHz),
        global abort is NOT triggered so the localized anomaly can be diagnosed.
        """
        meas = [
            Measurement(frequency_hz=250.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=1),  # Strong dip
            Measurement(frequency_hz=2000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
            Measurement(frequency_hz=4000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
        ]
        is_abort, reason = self.controller.check_global_abort(meas)
        self.assertFalse(is_abort)

    def test_deterministic_worst_frequency_tie_breaking(self):
        """
        Verify deterministic tie-breaking for worst measured frequency in detect_regions:
        lowest quality -> largest deviation from baseline -> lowest frequency.
        """
        meas = [
            Measurement(frequency_hz=250.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2),
            Measurement(frequency_hz=630.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2),
            Measurement(frequency_hz=800.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
        ]
        regions = self.controller.detect_regions(meas, "left")
        self.assertEqual(len(regions), 1)
        # All three have quality 2.0; lowest frequency (500 Hz) wins tie
        self.assertEqual(regions[0].worst_frequency, 500.0)

    def test_structural_rolloff_escape_cases(self):
        m_rolloff = [
            Measurement(frequency_hz=63.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=80.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=100.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=125.0, channel="left", stage=Stage.COARSE, heard=True, clarity=1),
            Measurement(frequency_hz=160.0, channel="left", stage=Stage.COARSE, heard=True, clarity=2),
            Measurement(frequency_hz=200.0, channel="left", stage=Stage.COARSE, heard=True, clarity=3),
            Measurement(frequency_hz=250.0, channel="left", stage=Stage.COARSE, heard=True, clarity=5),
            Measurement(frequency_hz=315.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
        ]
        reg = self.controller.detect_regions(m_rolloff, "left")[0]
        scored = self.controller.score_region(reg, m_rolloff)
        self.assertEqual(scored.category, RegionCategory.EXPECTED_LOW_ROLLOFF)
        self.assertLessEqual(scored.hardware_confidence, 25)

    def test_high_frequency_unilateral_vs_bilateral_guard(self):
        """
        Verify that bilateral high-frequency roll-off caps hardware confidence to <= 25%,
        while unilateral loss allows moderate attribution (~35-45%) with headphone advice.
        """
        m_left = [
            Measurement(frequency_hz=8000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
            Measurement(frequency_hz=10000.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=12500.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=16000.0, channel="left", stage=Stage.COARSE, heard=False, clarity=0),
        ]
        reg_l = self.controller.score_region(self.controller.detect_regions(m_left, "left")[0], m_left)
        self.assertLessEqual(reg_l.hardware_confidence, 45)

        # Bilateral
        session = Session()
        m_right = [
            Measurement(frequency_hz=8000.0, channel="right", stage=Stage.COARSE, heard=True, clarity=9),
            Measurement(frequency_hz=10000.0, channel="right", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=12500.0, channel="right", stage=Stage.COARSE, heard=False, clarity=0),
            Measurement(frequency_hz=16000.0, channel="right", stage=Stage.COARSE, heard=False, clarity=0),
        ]
        reg_r = self.controller.score_region(self.controller.detect_regions(m_right, "right")[0], m_right)
        session.channel_results["left"] = ChannelResult("left", m_left, [reg_l])
        session.channel_results["right"] = ChannelResult("right", m_right, [reg_r])

        findings = self.controller.evaluate_cross_channel(session)
        self.assertIn("hearing threshold limits", findings)
        self.assertLessEqual(reg_l.hardware_confidence, 25)
        self.assertLessEqual(reg_r.hardware_confidence, 25)

    def test_dynamic_half_bracket_uncertainty_and_severity(self):
        """
        Verify that uncertainty percentage uses the half-bracket formula:
        (sqrt(high/low) - 1.0) * 100 capped between 3% and 50%.
        """
        self.assertEqual(practical_round_freq(474.3), 475.0)
        meas = [
            Measurement(frequency_hz=400.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=1),
            Measurement(frequency_hz=630.0, channel="left", stage=Stage.COARSE, heard=True, clarity=1),
            Measurement(frequency_hz=800.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9),
        ]
        reg = self.controller.detect_regions(meas, "left")[0]
        expanded = self.controller.expand_region_boundaries(reg, meas)
        scored = self.controller.score_region(expanded, meas)
        self.assertIn(scored.severity, ("Moderate", "Strong"))
        self.assertGreaterEqual(scored.uncertainty_pct, 3.0)
        self.assertLessEqual(scored.uncertainty_pct, 50.0)

    def test_session_json_schema_version_and_unknown_fields_resilience(self):
        """
        Verify that Session.from_dict handles schema_version=2 and safely filters unknown fields.
        """
        data = {
            "schema_version": 2,
            "session_id": "test_schema_version",
            "unknown_future_field": "some_value",
            "channel_results": {
                "left": {
                    "channel": "left",
                    "avg_clarity": 7.5,
                    "unknown_channel_key": 999,
                    "measurements": [
                        {"frequency_hz": 1000.0, "channel": "left", "stage": "coarse", "heard": True, "clarity": 8, "unknown_field": True}
                    ],
                    "regions": [
                        {
                            "region_id": "reg_1", "channel": "left", "f_low": 500.0, "f_high": 630.0,
                            "center_frequency": 561.0, "min_quality": 2.0, "baseline_quality": 8.0,
                            "depth": 6.0, "effective_bad_count": 2.0, "anomaly_confidence": 70,
                            "hardware_confidence": 40, "category": "PERCEIVED_ANOMALY_MEDIUM_CONFIDENCE",
                            "evidence": "evidence", "worst_frequency": 500.0, "avg_quality": 2.0,
                            "severity": "Moderate", "uncertainty_pct": 12.0, "points": []
                        }
                    ]
                }
            }
        }
        restored = Session.from_dict(data)
        self.assertEqual(restored.schema_version, 2)
        self.assertEqual(restored.session_id, "test_schema_version")
        self.assertEqual(len(restored.channel_results["left"].regions), 1)
        self.assertEqual(restored.channel_results["left"].regions[0].worst_frequency, 500.0)


class TestSchedulerIntegration(unittest.TestCase):
    def setUp(self):
        self.controller = DiagnosticController(mode="detailed")
        self.scheduler = TestScheduler(mode="detailed")

    def test_scheduler_coarse_queueing_and_periodic_controls(self):
        self.scheduler.start_channel("left")
        queue = self.scheduler.test_queue
        # Detailed grid: 25 coarse points + controls every 8 points (at indices 7, 15, 23)
        self.assertGreaterEqual(len(queue), 25)
        controls = [item for item in queue if item["is_control"]]
        self.assertGreaterEqual(len(controls), 3)
        self.assertTrue(all(c["freq"] == 1000.0 for c in controls))

    def test_scheduler_deduplication_and_stage_awareness(self):
        self.scheduler.start_channel("left")
        # Enqueueing duplicate frequency should fail
        self.assertFalse(self.scheduler.enqueue(1000.0, Stage.COARSE))
        # Enqueueing new frequency should succeed
        self.assertTrue(self.scheduler.enqueue(720.0, Stage.REFINE))
        # Duplicate refine should fail
        self.assertFalse(self.scheduler.enqueue(720.0, Stage.REFINE))

    def test_scheduler_isolated_bad_point_retest_and_resolution(self):
        self.scheduler.start_channel("left")
        
        # Simulate testing all initial coarse and control queue items
        while True:
            item = self.scheduler.get_current_test()
            if item is None:
                break
            freq = item["freq"]
            clarity = 2 if (freq == 500.0 and item["stage"] == Stage.COARSE) else 9
            m = Measurement(frequency_hz=freq, channel="left", stage=item["stage"], heard=True, clarity=clarity, is_control=item["is_control"])
            self.scheduler.record_measurement(m, self.controller)

        # Transition should identify 500 Hz and queue a RETEST
        action, reason, count = self.scheduler.handle_phase_transition(self.controller)
        self.assertEqual(action, "CONTINUE")
        self.assertEqual(reason, "RETESTS_ADDED")
        self.assertEqual(count, 1)

        # Get next test and simulate retest response (good retest resolves input error)
        retest_item = self.scheduler.get_current_test()
        self.assertIsNotNone(retest_item)
        self.assertEqual(retest_item["freq"], 500.0)
        self.assertEqual(retest_item["stage"], Stage.RETEST)
        retest_m = Measurement(frequency_hz=500.0, channel="left", stage=Stage.RETEST, heard=True, clarity=9, is_retest=True)
        self.scheduler.record_measurement(retest_m, self.controller)

        # Verify original measurement was resolved as input error
        orig = next(m for m in self.scheduler.active_measurements if m.stage == Stage.COARSE and m.frequency_hz == 500.0)
        self.assertTrue(orig.input_error)

    def test_scheduler_adaptive_bisection_and_global_budget(self):
        self.scheduler.start_channel("left")

        # Simulate testing all initial queue items with a dip from 400 to 630 Hz
        while True:
            item = self.scheduler.get_current_test()
            if item is None:
                break
            freq = item["freq"]
            clarity = 2 if (400.0 <= freq <= 630.0 and item["stage"] == Stage.COARSE) else 9
            m = Measurement(frequency_hz=freq, channel="left", stage=item["stage"], heard=True, clarity=clarity, is_control=item["is_control"])
            self.scheduler.record_measurement(m, self.controller)

        # Transition should queue adaptive bisection refinement tests
        action, reason, count = self.scheduler.handle_phase_transition(self.controller)
        self.assertEqual(action, "CONTINUE")
        self.assertEqual(reason, "REFINEMENTS_ADDED")
        self.assertGreater(count, 0)
        self.assertLessEqual(self.scheduler.global_refine_count, 24)


class TestPropertyBasedInvariantFuzz(unittest.TestCase):
    def test_property_based_invariant_fuzz(self):
        """
        Fuzz test: execute 500 randomized measurement vectors through detect_regions and score_region.
        Assert that mathematical invariants always hold.
        """
        controller = DiagnosticController(mode="detailed")
        rng = random.Random(1337)
        grid = [63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0]

        for _ in range(500):
            sample_meas = []
            for freq in grid:
                heard = rng.choice([True, False])
                clarity = rng.randint(0, 10) if heard else 0
                dist = rng.randint(0, 10) if (heard and rng.random() > 0.5) else None
                qual, cls = controller.calculate_quality(heard, clarity, dist)
                sample_meas.append(Measurement(
                    frequency_hz=freq,
                    channel="left",
                    stage=Stage.COARSE,
                    heard=heard,
                    clarity=clarity,
                    distortion=dist,
                    quality=qual,
                    classification=cls
                ))

            regions = controller.detect_regions(sample_meas, "left")
            for reg in regions:
                self.assertLessEqual(reg.f_low, reg.f_high)
                self.assertFalse(math.isnan(reg.center_frequency))
                self.assertFalse(math.isinf(reg.center_frequency))
                self.assertTrue(reg.f_low <= reg.worst_frequency <= reg.f_high)

                expanded = controller.expand_region_boundaries(reg, sample_meas)
                self.assertLessEqual(expanded.start_estimate, expanded.end_estimate)

                scored = controller.score_region(expanded, sample_meas)
                self.assertGreaterEqual(scored.anomaly_confidence, 0)
                self.assertLessEqual(scored.anomaly_confidence, 95)
                self.assertGreaterEqual(scored.hardware_confidence, 0)
                self.assertLessEqual(scored.hardware_confidence, 95)
                self.assertGreaterEqual(scored.uncertainty_pct, 3.0)
                self.assertLessEqual(scored.uncertainty_pct, 50.0)


class TestHeadlessOracleSuite(unittest.TestCase):
    """
    Headless end-to-end oracle tests simulating closed-loop interactive raters with
    deterministic ground-truth acoustic and human rating profiles.
    """

    def _run_interactive_scheduler(self, rater_func, mode="detailed", max_steps=100) -> TestScheduler:
        controller = DiagnosticController(mode=mode)
        scheduler = TestScheduler(mode=mode)
        scheduler.start_channel("left")

        steps = 0
        while steps < max_steps:
            steps += 1
            item = scheduler.get_current_test()
            if item is None:
                action, reason, count = scheduler.handle_phase_transition(controller)
                if action == "ABORT" or action == "COMPLETE":
                    break
                elif action == "CONTINUE":
                    continue

            freq = item["freq"]
            stage = item["stage"]
            is_control = item.get("is_control", False)
            is_retest = item.get("is_retest", False)

            heard, clarity, dist = rater_func(freq, stage, is_control, is_retest)
            qual, cls = controller.calculate_quality(heard, clarity, dist)
            anchor = controller.rating_anchor(scheduler.active_measurements)
            eff_cls = controller.effective_classification(
                Measurement(frequency_hz=freq, channel="left", stage=stage, heard=heard, clarity=clarity, distortion=dist, quality=qual),
                anchor
            )

            m = Measurement(
                frequency_hz=freq,
                channel="left",
                stage=stage,
                heard=heard,
                clarity=clarity,
                distortion=dist,
                quality=qual,
                classification=cls,
                effective_classification=eff_cls,
                is_retest=is_retest,
                is_control=is_control
            )
            scheduler.record_measurement(m, controller)

        self.assertLess(steps, max_steps, "Scheduler exceeded maximum step count; potential infinite loop!")
        return scheduler

    def test_oracle_470_530_dip_rater(self):
        """
        Synthetic rater with true acoustic notch at 470-530 Hz.
        Verify that scheduler terminates, refines the transition boundaries, and detects the notch.
        """
        def dip_rater(freq, stage, is_control, is_retest):
            if 470.0 <= freq <= 530.0:
                return True, 2, 0  # Severe dip
            return True, 9, 0  # Clean nominal

        scheduler = self._run_interactive_scheduler(dip_rater, mode="detailed")
        controller = DiagnosticController(mode="detailed")
        regions = controller.detect_regions(scheduler.active_measurements, "left")

        self.assertEqual(len(regions), 1)
        reg = regions[0]
        self.assertAlmostEqual(reg.worst_frequency, 500.0, delta=35.0)

        # Scored region
        scored = controller.score_region(reg, scheduler.active_measurements)
        self.assertGreaterEqual(scored.anomaly_confidence, 80)
        self.assertIn("PERCEIVED_ANOMALY", scored.category)

    def test_oracle_always_bad_hardware_dead_rater(self):
        """
        Synthetic rater simulating dead speaker hardware (all inaudible).
        Verify aborts at coarse transition with GLOBAL_OUTPUT_FAILURE.
        """
        def dead_rater(freq, stage, is_control, is_retest):
            return False, 0, 0

        controller = DiagnosticController(mode="detailed")
        scheduler = TestScheduler(mode="detailed")
        scheduler.start_channel("left")

        while True:
            item = scheduler.get_current_test()
            if item is None:
                break
            m = Measurement(frequency_hz=item["freq"], channel="left", stage=item["stage"], heard=False, clarity=0, is_control=item.get("is_control", False))
            scheduler.record_measurement(m, controller)

        action, reason, _ = scheduler.handle_phase_transition(controller)
        self.assertEqual(action, "ABORT")
        self.assertEqual(reason, "GLOBAL_OUTPUT_FAILURE")

    def test_oracle_low_anchor_conservative_rater(self):
        """
        Synthetic conservative rater who hears all tones but rates everything 4/10 uniformly (no dips).
        Verify aborts with RATING_SCALE_LOW.
        """
        def conservative_rater(freq, stage, is_control, is_retest):
            return True, 4, 0

        controller = DiagnosticController(mode="detailed")
        scheduler = TestScheduler(mode="detailed")
        scheduler.start_channel("left")

        while True:
            item = scheduler.get_current_test()
            if item is None:
                break
            m = Measurement(frequency_hz=item["freq"], channel="left", stage=item["stage"], heard=True, clarity=4, quality=4.0, is_control=item.get("is_control", False))
            scheduler.record_measurement(m, controller)

        action, reason, _ = scheduler.handle_phase_transition(controller)
        self.assertEqual(action, "ABORT")
        self.assertEqual(reason, "RATING_SCALE_LOW")

    def test_oracle_contradictory_isolated_retest_resolves_cleanly(self):
        """
        Synthetic rater who accidentally inputs a bad score at 800 Hz, but on retest inputs 9/10.
        Verify original point is marked as input_error and final region count is 0.
        """
        def misclick_rater(freq, stage, is_control, is_retest):
            if stage == Stage.COARSE and freq == 800.0:
                return True, 1, 0  # Accidental misclick
            if stage == Stage.RETEST and freq == 800.0:
                return True, 9, 0  # Verified clean
            return True, 9, 0

        scheduler = self._run_interactive_scheduler(misclick_rater, mode="detailed")
        controller = DiagnosticController(mode="detailed")
        regions = controller.detect_regions(scheduler.active_measurements, "left")
        self.assertEqual(len(regions), 0)

    def test_oracle_elevated_distortion_categorization(self):
        """
        Synthetic rater who experiences loud buzzing/distortion (dist=8, clarity=7) across a band at 1 kHz–1.25 kHz.
        Verify categorization as LIKELY_LEVEL_DEPENDENT_DISTORTION.
        """
        controller = DiagnosticController(mode="detailed")
        meas = [
            Measurement(frequency_hz=500.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9, distortion=0),
            Measurement(frequency_hz=800.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9, distortion=0),
            Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=7, distortion=8),
            Measurement(frequency_hz=1250.0, channel="left", stage=Stage.COARSE, heard=True, clarity=7, distortion=8),
            Measurement(frequency_hz=1600.0, channel="left", stage=Stage.COARSE, heard=True, clarity=9, distortion=0),
        ]
        regions = controller.detect_regions(meas, "left")
        self.assertEqual(len(regions), 1)
        scored = controller.score_region(regions[0], meas)
        self.assertEqual(scored.category, RegionCategory.LIKELY_LEVEL_DEPENDENT_DISTORTION)
        self.assertIn("elevated distortion", scored.evidence)


class TestAudioEngineHelpers(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine(sample_rate=48000)

    def test_resample_length_and_content(self):
        sr = 44100
        t = np.arange(int(1.0 * sr)) / float(sr)
        data = np.stack([np.sin(2 * np.pi * 440.0 * t), np.sin(2 * np.pi * 440.0 * t)], axis=1)
        out = self.engine.resample_linear(data, sr, 48000)
        self.assertEqual(out.shape[1], 2)
        self.assertAlmostEqual(len(out) / 48000.0, 1.0, delta=0.01)

        # FFT dominant frequency preserved
        fft_vals = np.abs(np.fft.rfft(out[:48000, 0]))
        freqs = np.fft.rfftfreq(len(out[:48000, 0]), 1.0 / 48000.0)
        peak_freq = freqs[np.argmax(fft_vals)]
        self.assertAlmostEqual(peak_freq, 440.0, delta=3.0)

    def test_route_stereo(self):
        data = np.ones((100, 2), dtype=np.float32)
        left = self.engine.route_stereo(data, "left")
        self.assertGreater(np.max(np.abs(left[:, 0])), 0.0)
        self.assertEqual(np.max(np.abs(left[:, 1])), 0.0)

        right = self.engine.route_stereo(data, "right")
        self.assertEqual(np.max(np.abs(right[:, 0])), 0.0)
        self.assertGreater(np.max(np.abs(right[:, 1])), 0.0)

        both = self.engine.route_stereo(data, "both")
        self.assertEqual(np.max(np.abs(both[:, 0])), 1.0)
        self.assertEqual(np.max(np.abs(both[:, 1])), 1.0)

        # Original data unmutated
        self.assertEqual(np.max(np.abs(data[:, 1])), 1.0)

    def test_prepare_music_segment(self):
        base = np.ones((48000, 2), dtype=np.float32)
        seg = self.engine.prepare_music_segment(base, 0, "both", volume=0.5, fade_ms=8.0)
        self.assertAlmostEqual(float(np.max(np.abs(seg))), 0.5, places=3)
        self.assertLess(abs(seg[0, 0]), 0.05)  # Fade-in start near zero

    def test_device_samplerate_adaptation(self):
        self.engine.set_output_device(None)
        self.assertGreaterEqual(self.engine.sample_rate, 8000)
        self.assertLessEqual(self.engine.sample_rate, 192000)


class TestSessionPersistence(unittest.TestCase):
    def test_from_dict_without_channel_results(self):
        minimal_data = {
            "session_id": "test_123",
            "mode": "quick",
            "sample_rate": 48000
        }
        session = Session.from_dict(minimal_data)
        self.assertEqual(session.session_id, "test_123")
        self.assertEqual(session.mode, "quick")
        self.assertEqual(session.channel_results, {})

    def test_from_dict_roundtrip(self):
        session = Session(session_id="roundtrip_test", mode="detailed")
        m = Measurement(frequency_hz=1000.0, channel="left", stage=Stage.COARSE, heard=True, clarity=8)
        cr = ChannelResult(channel="left", measurements=[m], avg_clarity=8.0)
        session.channel_results["left"] = cr

        d = session.to_dict()
        restored = Session.from_dict(d)
        self.assertEqual(restored.session_id, "roundtrip_test")
        self.assertIn("left", restored.channel_results)
        self.assertEqual(len(restored.channel_results["left"].measurements), 1)
        self.assertEqual(restored.channel_results["left"].measurements[0].clarity, 8)


class TestPreflightDetection(unittest.TestCase):
    def test_detect_preflight_conditions_structure(self):
        res = AudioEngine.detect_preflight_conditions(None)
        self.assertIsInstance(res, dict)
        self.assertIn("fxsound_running", res)
        self.assertIn("detected_enhancers", res)
        self.assertIn("is_virtual_device", res)
        self.assertIn("output_device_name", res)
        self.assertIn("output_samplerate", res)
        self.assertIn("output_channels", res)
        self.assertIn("mic_available", res)
        self.assertIn("is_quiet", res)
        self.assertIn("fxsound_clean", res)
        self.assertIn("hardware_clean", res)
        self.assertIn("all_clear", res)
        self.assertIsInstance(res["detected_enhancers"], list)
        self.assertIsInstance(res["fxsound_running"], bool)
        self.assertIsInstance(res["is_virtual_device"], bool)
        self.assertIsInstance(res["output_samplerate"], int)
        self.assertGreater(res["output_samplerate"], 0)


class TestSvgIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

    def test_all_svg_icons_render(self):
        from icons import SVG_ICONS, get_svg_icon, get_svg_pixmap
        for name in SVG_ICONS:
            icon = get_svg_icon(name)
            self.assertFalse(icon.isNull(), f"Icon '{name}' failed to render")
            pix = get_svg_pixmap(name)
            self.assertFalse(pix.isNull(), f"Pixmap '{name}' failed to render")
            self.assertEqual(pix.width(), 20)
            self.assertEqual(pix.height(), 20)

    def test_no_emojis_in_python_sources(self):
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for root, _, files in os.walk(base_dir):
            if any(x in root for x in ["build", "dist", "__pycache__", ".git"]):
                continue
            for file in files:
                if file.endswith(".py"):
                    p = os.path.join(root, file)
                    with open(p, "r", encoding="utf-8") as f:
                        for line_idx, line in enumerate(f, 1):
                            for c in line:
                                is_emoji = (
                                    (0x1F300 <= ord(c) <= 0x1FAFF) or
                                    (0x2600 <= ord(c) <= 0x27BF) or
                                    (0x25A0 <= ord(c) <= 0x25FF) or
                                    (0x2190 <= ord(c) <= 0x21FF)
                                )
                                self.assertFalse(
                                    is_emoji,
                                    f"Found emoji/symbol U+{ord(c):04X} in {file}:{line_idx} -> {line.strip()}"
                                )


    def test_fx_theme_tokens_and_qss(self):
        import fx_theme
        self.assertEqual(len(fx_theme.SPECTRUM_BANDS), 9)
        for token in ["window_bg", "control_bg", "card_bg", "primary_accent", "text_primary", "text_body"]:
            self.assertIn(token, fx_theme.FX_COLORS_DARK)
            self.assertIn(token, fx_theme.FX_COLORS_LIGHT)
            self.assertTrue(fx_theme.get_fx_color(token, True).startswith("#"))
            self.assertTrue(fx_theme.get_fx_color(token, False).startswith("#"))
        qss_dark = fx_theme.get_qss(True)
        qss_light = fx_theme.get_qss(False)
        self.assertIn("#181818", qss_dark)
        self.assertIn("#f5f5f5", qss_light)
        self.assertIn("#d51535", qss_dark)
        self.assertIn("#1ac1ff", qss_light)

    def test_visualizer_idle_timer_stops(self):
        from ui_components import FxSpectrumVisualizerWidget
        vis = FxSpectrumVisualizerWidget()
        vis.set_provider(lambda: None)
        vis._on_tick()
        # When provider returns None, visualizer decays and stops timer
        self.assertFalse(vis._timer.isActive())
        self.assertFalse(vis._is_playing)


class TestFxSoundUiAndNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

    def test_toggle_no_active_qss_present(self):
        import fx_theme
        for qss in (fx_theme.get_qss(True), fx_theme.get_qss(False)):
            self.assertIn("QPushButton.toggle-no-active", qss)
            self.assertIn("QPushButton.toggle-yes-active", qss)

    def test_manrope_font_loads_and_rebuilds_qss(self):
        import fx_theme
        loaded = fx_theme.load_app_fonts()
        self.assertTrue(loaded, "Bundled Manrope font failed to register")
        self.assertIn("Manrope", fx_theme.FONT_FAMILY_STACK)
        self.assertTrue(
            fx_theme.FONT_FAMILY_STACK.startswith("'Manrope'"),
            "Manrope must be the primary UI font family"
        )
        self.assertIn("'Manrope'", fx_theme.get_qss(True))
        self.assertIn("'Manrope'", fx_theme.get_qss(False))

    def test_scheduler_manual_queue_mode(self):
        sched = TestScheduler(mode="quick")
        sched.load_manual_queue([440.0, 880.0, 1660.0])
        self.assertTrue(sched.manual_mode)
        self.assertEqual(len(sched.test_queue), 3)
        controller = DiagnosticController(mode="quick")
        action, reason, count = sched.handle_phase_transition(controller)
        self.assertEqual(action, "COMPLETE")
        self.assertEqual(reason, "MANUAL_QUEUE_DONE")
        self.assertEqual(count, 0)

    def test_scheduler_undo_last_measurement(self):
        sched = TestScheduler(mode="quick")
        sched.start_channel("left")
        controller = DiagnosticController(mode="quick")
        first = sched.get_current_test()
        m1 = Measurement(frequency_hz=first["freq"], channel="left", stage=first["stage"], heard=True, clarity=8)
        sched.record_measurement(m1, controller)
        second = sched.get_current_test()
        m2 = Measurement(frequency_hz=second["freq"], channel="left", stage=second["stage"], heard=False, clarity=0)
        sched.record_measurement(m2, controller)
        self.assertEqual(len(sched.active_measurements), 2)
        sched.undo_last_measurement()
        self.assertEqual(len(sched.active_measurements), 1)
        current = sched.get_current_test()
        self.assertIsNotNone(current)
        self.assertAlmostEqual(current["freq"], m2.frequency_hz, delta=1.0)
        again = Measurement(frequency_hz=current["freq"], channel="left", stage=current["stage"], heard=True, clarity=9)
        sched.record_measurement(again, controller)
        self.assertEqual(len(sched.active_measurements), 2)

    def test_session_sweep_marks_roundtrip(self):
        session = Session(session_id="sweep_marks_test", mode="sweep")
        session.sweep_marks_hz = [1234.5, 5678.0]
        d = session.to_dict()
        restored = Session.from_dict(d)
        self.assertEqual(restored.sweep_marks_hz, [1234.5, 5678.0])

    def test_from_dict_legacy_without_sweep_marks(self):
        legacy = {"session_id": "legacy_1", "mode": "detailed"}
        session = Session.from_dict(legacy)
        self.assertEqual(session.sweep_marks_hz, [])

    def test_real_spectrum_bands_from_engine(self):
        engine = AudioEngine(sample_rate=48000, default_peak=0.4)
        self.assertIsNone(engine.get_spectrum_bands())
        tone = engine.generate_sine_tone(1000.0, duration_s=0.2, peak=0.4, channel="both")
        engine._spectrum_meta = {"buffer": tone, "sample_rate": 48000}
        # Simulate playback already 100 ms in so the analysis window holds real signal
        engine._spectrum_start = time.time() - 0.1
        engine._is_playing = True
        try:
            bands = engine.get_spectrum_bands()
            self.assertIsNotNone(bands)
            self.assertEqual(len(bands), len(fx_theme.SPECTRUM_BANDS))
            peak_idx = max(range(len(bands)), key=lambda i: bands[i])
            self.assertEqual(peak_idx, 4, "1 kHz tone must peak in the 1000 Hz band")
            self.assertGreater(bands[peak_idx], 0.5)
            for v in bands:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)
        finally:
            engine._is_playing = False
            engine._spectrum_meta = None
            engine._spectrum_start = None

    def test_report_labels_sweep_retest_channel(self):
        session = Session(session_id="sweep_report_test", mode="sweep")
        m = Measurement(frequency_hz=2400.0, channel="both", stage=Stage.SWEEP, heard=True, clarity=7, is_retest=True)
        session.channel_results["sweep"] = ChannelResult(channel="sweep", measurements=[m], avg_clarity=7.0)
        report = session.generate_report()
        self.assertIn("SWEEP MARKER RETESTS", report)
        self.assertIn("2,400 Hz", report)


class TestPlaybackLifecycleThreadSafety(unittest.TestCase):
    """
    Regression guard for native heap corruption (0xc0000374): python-sounddevice's
    module-global stream must never receive concurrent play/stop calls.
    All AudioEngine entry points serialize through _PORTAUDIO_LOCK.
    """

    class _FakeSd:
        def __init__(self):
            self.cur = 0
            self.overlaps = []
            self.calls = 0
            self._mtx = threading.Lock()

        def play(self, data, samplerate=48000, device=None, blocking=False):
            with self._mtx:
                self.cur += 1
                self.calls += 1
                if self.cur > 1:
                    self.overlaps.append("play")
            time.sleep(0.0005)
            with self._mtx:
                self.cur -= 1

        def stop(self):
            with self._mtx:
                self.cur += 1
                self.calls += 1
                if self.cur > 1:
                    self.overlaps.append("stop")
            time.sleep(0.0005)
            with self._mtx:
                self.cur -= 1

    def _make_engine(self, fake_sd):
        import audio_engine as ae_mod
        original = ae_mod.sd
        ae_mod.sd = fake_sd
        self.addCleanup(setattr, ae_mod, "sd", original)
        return ae_mod.AudioEngine(sample_rate=48000)

    def test_sequential_cycles_never_overlap_portaudio_calls(self):
        import threading as threading_mod
        fake = self._FakeSd()
        eng = self._make_engine(fake)
        tone = np.zeros((64, 2), dtype=np.float32)

        for _ in range(20):
            finished = []
            eng.play_audio(tone, on_finished=lambda ok, err: finished.append(ok))
            time.sleep(0.005)
            eng.stop_playback()
            t = eng._playback_thread
            if t is not None:
                t.join(timeout=2.0)
            self.assertFalse(eng.is_playing())
            self.assertEqual(finished, [], "explicit stop must suppress stale callbacks")

        self.assertEqual(fake.overlaps, [])

    def test_natural_completion_fires_callback_once(self):
        fake = self._FakeSd()
        eng = self._make_engine(fake)
        tone = np.zeros((64, 2), dtype=np.float32)
        finished = []
        eng.play_audio(tone, on_finished=lambda ok, err: finished.append(ok))
        t = eng._playback_thread
        t.join(timeout=3.0)
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0])
        self.assertFalse(eng.is_playing())

    def test_concurrent_play_stop_hammer_stays_consistent(self):
        import threading as threading_mod
        fake = self._FakeSd()
        eng = self._make_engine(fake)
        tone = np.zeros((64, 2), dtype=np.float32)
        errors = []

        def player():
            try:
                for _ in range(30):
                    eng.play_audio(tone)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        def stopper():
            try:
                for _ in range(30):
                    eng.stop_playback()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        tp = threading_mod.Thread(target=player)
        ts = threading_mod.Thread(target=stopper)
        tp.start(); ts.start()
        tp.join(timeout=10); ts.join(timeout=10)
        eng.stop_playback()
        t = eng._playback_thread
        if t is not None:
            t.join(timeout=2.0)

        self.assertEqual(errors, [])
        self.assertEqual(fake.overlaps, [])
        self.assertFalse(eng.is_playing())


if __name__ == "__main__":
    unittest.main()
