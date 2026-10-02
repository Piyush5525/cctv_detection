"""Unit tests for the EXPERIMENTAL fall / violence / snatch detectors, on synthetic pose and track sequences."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Tests never touch the real incidents.db / evidence dir (this module can be the first one imported by discovery).
_TEST_DIR = tempfile.mkdtemp(prefix="ws-action-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import action_synth as S
from api.services.action_detectors.fall import FallDetector
from api.services.action_detectors.snatch import SnatchDetector
from api.services.action_detectors.violence import ViolenceDetector


def any_hit(results):
    return any(r.detected for r in results)


class FallTests(unittest.TestCase):
    def run_seq(self, seq):
        return S.run(FallDetector(), S.frames(seq))

    def test_true_fall_detected_with_signals(self):
        res = self.run_seq(S.true_fall())
        hits = [r for r in res if r.detected]
        self.assertTrue(hits, "a fast drop to horizontal that stays down must be detected")
        sig = hits[0].signals
        for key in ("head_drop_frac", "hip_drop_frac", "drop_velocity", "torso_angle_deg", "aspect_flip", "stay_down_s"):
            self.assertIn(key, sig)
        self.assertGreaterEqual(sig["stay_down_s"], 2.0)
        self.assertTrue(sig["aspect_flip"])
        self.assertTrue(hits[0].boxes and "keypoints" in hits[0].boxes[0])      # overlay only, in memory

    def test_no_detection_before_stay_down_elapses(self):
        res = self.run_seq(S.true_fall(stay_s=4.0))
        first = next(i for i, r in enumerate(res) if r.detected)
        self.assertGreaterEqual(first, 8 + 1 + 1 + 7, "must wait FALL_STAY_DOWN_S (2 s = 8 samples) after the drop")

    def test_fall_that_recovers_quickly_is_not_a_fall(self):
        self.assertFalse(any_hit(self.run_seq(S.fall_then_get_up())))

    def test_sitting_down_is_not_a_fall(self):
        self.assertFalse(any_hit(self.run_seq(S.sitting_down())))

    def test_bending_is_not_a_fall(self):
        self.assertFalse(any_hit(self.run_seq(S.bending())))

    def test_lying_down_on_purpose_is_not_a_fall(self):
        self.assertFalse(any_hit(self.run_seq(S.lying_down_on_purpose())))

    def test_deep_held_bend_is_rejected_by_the_hip_drop_rule(self):
        from api.core.config import settings
        self.assertFalse(any_hit(self.run_seq(S.bending_deep_hold())))
        old = settings.FALL_HIP_DROP_FRAC
        settings.FALL_HIP_DROP_FRAC = -1.0                       # mutation: without the hip rule it WOULD be a fall
        try:
            self.assertTrue(any_hit(self.run_seq(S.bending_deep_hold())))
        finally:
            settings.FALL_HIP_DROP_FRAC = old

    def test_stay_down_rule_is_what_rejects_a_quick_recovery(self):
        from api.core.config import settings
        old = settings.FALL_STAY_DOWN_S
        settings.FALL_STAY_DOWN_S = 0.5
        try:
            self.assertTrue(any_hit(self.run_seq(S.fall_then_get_up())))
        finally:
            settings.FALL_STAY_DOWN_S = old

    def test_crouch_is_not_a_fall(self):
        self.assertFalse(any_hit(self.run_seq(S.crouching())))

    def test_latch_releases_when_person_stands_up(self):
        seq = S.true_fall(stay_s=3.0) + S.stand_frames(6)
        res = self.run_seq(seq)
        self.assertTrue(any_hit(res))
        self.assertFalse(res[-1].detected)

    def test_person_entering_already_lying_is_not_a_fall(self):
        seq = [[S.person(1, S.skeleton(300, S.GROUND - 0.08 * S.H, 88, legs="lie"))] for _ in range(24)]
        self.assertFalse(any_hit(self.run_seq(seq)))


class ViolenceGateTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def clip(frame):
            self.calls.append(1)
            return "fight on a street", 0.31
        self.det = ViolenceDetector(clip_fn=clip)

    def run_seq(self, seq):
        return S.run(self.det, S.frames(seq), window_s=3.0)

    def test_one_person_never_opens_gate_or_runs_clip(self):
        res = self.run_seq(S.stand_frames(20))
        self.assertFalse(any_hit(res))
        self.assertEqual(self.calls, [])

    def test_far_apart_never_opens_gate(self):
        res = self.run_seq(S.pair_sequence(20, gap=700, swing=1.0))
        self.assertFalse(any_hit(res))
        self.assertEqual(self.calls, [])

    def test_close_but_still_never_opens_gate(self):
        res = self.run_seq(S.pair_sequence(20, gap=80, swing=0.0, still=True))
        self.assertFalse(any_hit(res))
        self.assertEqual(self.calls, [])

    def test_close_and_moving_runs_clip_and_smooths(self):
        res = self.run_seq(S.pair_sequence(24, gap=80, swing=1.0))
        self.assertTrue(self.calls, "gate open => CLIP evaluated")
        hits = [r for r in res if r.detected]
        self.assertTrue(hits, "N-of-M smoothing satisfied after repeated raw hits")
        sig = hits[0].signals
        self.assertTrue(sig["gate_open"])
        for key in ("motion_energy", "motion_sustained_frac", "pair_distance", "clip_label", "clip_score", "smoothing"):
            self.assertIn(key, sig)
        self.assertEqual(len(hits[0].boxes), 2)

    def test_single_raw_hit_is_not_enough(self):
        outcomes = iter([("fight on a street", 0.31)] + [("people walking on a street", 0.30)] * 40)
        det = ViolenceDetector(clip_fn=lambda f: next(outcomes))
        res = S.run(det, S.frames(S.pair_sequence(24, gap=80, swing=1.0)), window_s=3.0)
        self.assertFalse(any_hit(res))

    def test_non_violent_clip_label_does_not_alert(self):
        det = ViolenceDetector(clip_fn=lambda f: ("people talking", 0.35))
        res = S.run(det, S.frames(S.pair_sequence(24, gap=80, swing=1.0)), window_s=3.0)
        self.assertFalse(any_hit(res))

    def test_below_clip_threshold_does_not_alert(self):
        det = ViolenceDetector(clip_fn=lambda f: ("street violence", 0.20))
        res = S.run(det, S.frames(S.pair_sequence(24, gap=80, swing=1.0)), window_s=3.0)
        self.assertFalse(any_hit(res))


class SnatchTests(unittest.TestCase):
    def run_seq(self, seq):
        return S.run(SnatchDetector(), S.frames(seq))

    def test_approach_and_flee_detected(self):
        res = self.run_seq(S.approach_and_flee())
        hits = [r for r in res if r.detected]
        self.assertTrue(hits)
        sig = hits[0].signals
        for key in ("approach_closing_speed", "flee_speed", "acceleration_ratio", "separation", "diverging_angle_deg"):
            self.assertIn(key, sig)
        self.assertGreaterEqual(sig["flee_speed"], 2.5)

    def test_two_people_walking_past_each_other_not_detected(self):
        self.assertFalse(any_hit(self.run_seq(S.walk_past())))

    def test_fast_walkers_passing_not_detected(self):
        self.assertFalse(any_hit(self.run_seq(S.walk_past(speed_h=2.0))))

    def test_slow_departure_not_detected(self):
        self.assertFalse(any_hit(self.run_seq(S.approach_and_flee(flee_speed_h=1.2))))

    def test_single_person_not_detected(self):
        self.assertFalse(any_hit(self.run_seq([[S.box_person(1, 100 + 10 * k, 300)] for k in range(20)])))

class FallLostTrackTests(unittest.TestCase):
    def run_seq(self, seq):
        return S.run(FallDetector(), S.frames(seq))

    def test_track_lost_during_the_fall_then_low_for_two_seconds_is_a_fall(self):
        res = self.run_seq(S.fall_lost_then_low())
        hits = [r for r in res if r.detected]
        self.assertTrue(hits)
        sig = hits[0].signals
        self.assertEqual(sig["path"], "lost_track_then_low")
        self.assertGreaterEqual(sig["stay_down_s"], 2.0)
        self.assertLessEqual(sig["height_ratio"], 0.75)
        self.assertGreaterEqual(sig["head_drop_frac"], 0.30)
        self.assertGreaterEqual(hits[0].score, 0.6)

    def test_not_a_fall_when_the_gap_is_too_long_or_the_person_walked_away_or_left_the_frame_or_stood_up(self):
        self.assertFalse(any_hit(self.run_seq(S.fall_lost_then_low(gap_s=4.5))), "gap longer than FALL_LOST_GAP_S")
        self.assertFalse(any_hit(self.run_seq(S.walk_away_lost())), "smaller person higher in the image = walked away")
        self.assertFalse(any_hit(self.run_seq(S.fall_lost_then_low(x=20.0, x_new=40.0))), "last seen at the frame edge = left the frame")
        self.assertFalse(any_hit(self.run_seq(S.lost_then_stands_up())), "stood up again")

    def test_stay_down_still_required(self):
        self.assertFalse(any_hit(self.run_seq(S.fall_lost_then_low(low_s=1.0))))


class ViolenceMergedBlobTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def clip(frame):
            self.calls.append(1)
            return "street violence", 0.23
        self.det = ViolenceDetector(clip_fn=clip)

    def run_seq(self, seq, det=None):
        return S.run(det or self.det, S.frames(seq), window_s=3.0)

    def test_one_large_merged_box_with_movement_and_sustained_clip_top1_is_detected(self):
        res = self.run_seq(S.merged_blob_sequence())
        hits = [r for r in res if r.detected]
        self.assertTrue(hits)
        self.assertEqual(hits[0].signals["mode"], "merged_blob")
        self.assertEqual(hits[0].signals["clip_label"], "street violence")

    def test_single_small_person_or_a_still_blob_never_runs_clip(self):
        self.assertFalse(any_hit(self.run_seq(S.merged_blob_sequence(h=100))))          # 100 px < 30 percent of the frame height
        self.assertFalse(any_hit(self.run_seq(S.merged_blob_sequence(swing=0.0))))      # large but not moving
        self.assertEqual(self.calls, [])

    def test_a_non_violent_top1_label_or_a_score_below_the_cutoff_does_not_alert(self):
        for label, score in (("people walking on a street", 0.30), ("street violence", 0.20)):
            det = ViolenceDetector(clip_fn=lambda f, l=label, sc=score: (l, sc))
            self.assertFalse(any_hit(self.run_seq(S.merged_blob_sequence(), det)), label)


class SnatchContactPathTests(unittest.TestCase):
    def run_seq(self, seq):
        return S.run(SnatchDetector(), S.frames(seq))

    def test_sustained_contact_with_a_speed_burst_then_a_takedown_is_detected(self):
        hits = [r for r in self.run_seq(S.contact_drag_takedown()) if r.detected]
        self.assertTrue(hits)
        sig = hits[0].signals
        self.assertEqual((sig["path"], sig["outcome"]), ("contact_burst_outcome", "ground"))
        self.assertGreaterEqual(sig["contact_s"], 2.0)
        self.assertGreaterEqual(sig["burst_speed"], 2.0)

    def test_walking_together_a_still_embrace_and_incomplete_patterns_are_not_detected(self):
        self.assertFalse(any_hit(self.run_seq(S.walking_together())))
        self.assertFalse(any_hit(self.run_seq(S.contact_drag_takedown(burst=False))), "no speed burst")
        self.assertFalse(any_hit(self.run_seq(S.contact_drag_takedown(takedown=False))), "no takedown and no separation")
        self.assertFalse(any_hit(self.run_seq([[S.box_person(1, 300, 300), S.box_person(2, 400, 300)] for _ in range(30)])), "standing still together")


if __name__ == "__main__":
    unittest.main()
