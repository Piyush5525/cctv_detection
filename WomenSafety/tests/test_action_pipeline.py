"""End-to-end tests for the EXPERIMENTAL action detectors in the v2 pipeline: simulated clip -> incident (category,
evidence, signals, no keypoints), per-camera detector lists, and the alert policy (an experimental incident never
places a call by itself; Escalate now does; every safety rule unchanged). All network calls are mocked."""
import json
import os
import sys
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-action-pipe-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

import action_synth as S
from api import db
from api.core.config import settings
from api.models.camera import Camera, get_camera
from api.services import camera_workers as cw
from api.services import incident_service_v2 as incidents
from api.services import notification_service as ns
from api.services.action_detectors import ActionEngine


class FakePose:
    """Stands in for the shared YOLOv8n-pose pass: returns the scripted persons of each call."""
    available = True

    def __init__(self, script):
        self.script, self.i = script, 0

    def infer(self, frame):
        persons = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return [(p.box, p.kp) for p in persons]


def wait_for(fn, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return None


def synthetic_frame(i):
    rng = np.random.default_rng(i)
    return (rng.integers(0, 255, (480, 640, 3))).astype(np.uint8) // 4 + 40


class SimulatedClipTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.cam = get_camera("CAM-SAMPLE-001").model_copy(update={"detectors": ["fire", "crash", "fall"]})

    def _worker(self, script, camera=None):
        def make_engine(camera_id, names, on_verdict=None):
            return ActionEngine(camera_id, names, on_verdict=on_verdict, pose=FakePose(script), pose_interval_s=0.25, max_width=640)
        with patch.object(cw, "ActionEngine", make_engine):
            return cw.CameraWorker(camera or self.cam, registry=None, detector_lock=None)

    def _drive(self, worker, seq):
        n = len(seq)
        start = datetime.now(timezone.utc) - timedelta(seconds=n * 0.25 + 1)
        for i in range(n):
            ts = start + timedelta(seconds=i * 0.25)
            frame = synthetic_frame(i)
            worker.pipeline.add_raw_frame(frame, ts)
            for p in worker.action_pipelines.values():
                p.add_raw_frame(frame, ts)
            worker.action.process(frame, i * 0.25, ts)
        end = start + timedelta(seconds=n * 0.25)
        for p in worker.action_pipelines.values():
            p.flush(end)

    def test_simulated_fall_clip_creates_a_correct_experimental_incident(self):
        seq = S.true_fall(stay_s=4.0) + S.stand_frames(4)
        worker = self._worker(seq)
        self.assertEqual(sorted(worker.action_pipelines), ["fall"])
        self._drive(worker, seq)
        found = wait_for(lambda: incidents.list_incidents(camera_id=self.cam.camera_id, category="fall"))
        self.assertTrue(found, "no incident created from the simulated fall clip")
        inc = found[0]
        self.assertEqual(inc["category"], "fall")
        self.assertEqual(inc["source"], "test_replay")
        det = inc["detection"]
        self.assertTrue(det["experimental"])
        self.assertEqual(det["detector_source"], "pose-fall-rules")
        self.assertEqual(det["threshold_applied"], settings.FALL_SCORE_THRESHOLD)
        self.assertGreaterEqual(det["peak_confidence"], settings.FALL_SCORE_THRESHOLD)
        for key in ("head_drop_frac", "hip_drop_frac", "drop_velocity", "torso_angle_deg", "stay_down_s"):
            self.assertIn(key, det["signals"])
        self.assertGreaterEqual(det["signals"]["stay_down_s"], settings.FALL_STAY_DOWN_S)
        ev = inc["evidence"]
        for key in ("best_frame_path", "annotated_frame_path", "thumbnail_path", "clip_path"):
            self.assertTrue(Path(ev[key]).exists(), key)
        self.assertGreater(Path(ev["clip_path"]).stat().st_size, 1000)
        # No keypoints / biometric data in the stored record: bboxes keep label/conf/box only.
        stored = json.dumps(inc)
        self.assertNotIn("keypoints", stored)
        self.assertTrue(all(set(b) == {"label", "conf", "box"} for b in det["best_frame_bbox"]))
        # The best frame is the peak-score frame WITH the overlay: it differs from the raw annotated-free frame
        import cv2
        best = cv2.imread(ev["best_frame_path"])
        self.assertIsNotNone(best)
        self.assertTrue(((best[..., 2] > 200) & (best[..., 1] < 80) & (best[..., 0] < 80)).any(), "box overlay (red) missing on best frame")
        # Notification flow was enqueued: the dispatch plan and a timeline exist (alerts are disabled in tests => skipped)
        full = wait_for(lambda: (lambda d: d if d and d.get("notifications") and len(d["notifications"]) >= 2 else None)(incidents.get_incident(inc["incident_id"])))
        self.assertIsNotNone(full)
        self.assertTrue(any(n["channel"] == "dispatch" for n in full["notifications"]))
        self.assertEqual(full["dispatch_plan"]["required_services"], ["hospital"])   # DISPATCH_RULES: fall -> hospital

    def test_sitting_clip_creates_no_incident(self):
        seq = S.sitting_down() + S.stand_frames(4)
        worker = self._worker(seq)
        before = len(incidents.list_incidents(camera_id=self.cam.camera_id, category="fall"))
        self._drive(worker, seq)
        time.sleep(1.0)
        self.assertEqual(len(incidents.list_incidents(camera_id=self.cam.camera_id, category="fall")), before)

    def test_violence_maps_to_assault_and_snatch_to_snatching(self):
        for tag, cat in (("violence", "assault"), ("snatch", "snatching")):
            self.assertEqual(incidents._category_from_class_name(cat).value, cat)
        from api.services.action_detectors import CATEGORY_OF
        self.assertEqual(CATEGORY_OF, {"fall": "fall", "violence": "assault", "snatch": "snatching"})
        from api.core.config import required_services
        self.assertEqual(required_services("fall"), ("hospital",))
        self.assertEqual(required_services("assault"), ("police",))
        self.assertEqual(required_services("snatching"), ("police",))


class PerCameraDetectorListTests(unittest.TestCase):
    def test_default_is_fire_and_crash_only(self):
        cam = get_camera("CAM-SAMPLE-002")
        self.assertEqual(cam.active_detectors, ["fire", "crash"])

    def test_default_worker_builds_no_action_engine(self):
        with patch.object(cw, "ActionEngine", side_effect=AssertionError("no action detector may be built unless listed")):
            worker = cw.CameraWorker(get_camera("CAM-SAMPLE-002"), registry=None, detector_lock=None)
        self.assertIsNone(worker.action)
        self.assertEqual(worker.action_pipelines, {})

    def test_listed_action_detector_gets_its_own_pipeline_with_own_settings_and_shared_buffer(self):
        cam = get_camera("CAM-SAMPLE-002").model_copy(update={"detectors": ["fire", "violence", "snatch"]})
        worker = cw.CameraWorker(cam, registry=None, detector_lock=None)
        self.assertEqual(sorted(worker.action_pipelines), ["snatch", "violence"])
        v = worker.action_pipelines["violence"]
        self.assertEqual((v.confirm_n, v.confirm_m), (settings.VIOLENCE_CONFIRM_N, settings.VIOLENCE_CONFIRM_M))
        self.assertIs(v.pre_buffer, worker.pipeline.pre_buffer)
        self.assertIsNot(v, worker.pipeline)
        self.assertTrue(v.overlay_best_frame)
        self.assertFalse(worker.pipeline.overlay_best_frame)
        self.assertEqual(worker.pipeline.confirm_n, settings.EVENT_CONFIRM_N)   # fire/crash pipeline unchanged

    def test_env_override_and_unknown_names(self):
        cam = get_camera("CAM-SAMPLE-002")
        with patch.dict(os.environ, {"DETECTORS_CAM_SAMPLE_002": "fire, crash,FALL,bogus"}):
            self.assertEqual(cam.active_detectors, ["fire", "crash", "fall"])
        with self.assertRaises(Exception):
            Camera(**{**cam.model_dump(), "latitude": 26.9, "longitude": 75.8, "detectors": ["nope"]})

    def test_fire_crash_run_only_if_listed(self):
        class Det:
            def __init__(self, name):
                self.name, self.threshold = name, 0.5

            def detect(self, frame):
                return SimpleNamespace(detection=self.name.title(), confidence=0.9, boxes=[])
        registry = SimpleNamespace(all=lambda: [Det("fire"), Det("crash")])
        cam = get_camera("CAM-SAMPLE-002").model_copy(update={"detectors": ["crash"]})
        worker = cw.CameraWorker(cam, registry=registry, detector_lock=__import__("threading").Lock())
        self.assertEqual(worker._detect(np.zeros((100, 100, 3), np.uint8))["category"], "crash")


# --------------------------------------------------------------------------------------------- alert policy
PLAN_LOOKUP = {"source": "cache", "services": {
    "hospital": [{"title": "Test Hospital", "category": "hospital", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}],
    "police": [{"title": "Test Police", "category": "police", "distance_km": 0.7, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}],
    "fire": []}}


def make_incident(category, experimental, camera_id=None, confidence=0.9, threshold=0.6):
    incident_id = str(uuid.uuid4())
    data = {"incident_id": incident_id, "camera_id": camera_id or f"CAM-{incident_id[:4]}", "camera_name": "Test Cam", "place_text": "Test Place",
            "latitude": 26.9, "longitude": 75.8, "category": category, "status": "new", "source": "test_replay",
            "event_start": "2026-10-01T00:00:00+00:00", "detected_at": "2026-10-01T00:00:00+00:00",
            "detection": {"peak_confidence": confidence, "threshold_applied": threshold, "experimental": experimental,
                          "signals": {"stay_down_s": 3.0}}, "evidence": {}, "notifications": []}
    db.insert_incident(incident_id, data["camera_id"], category, "new", "test_replay", data["event_start"], data)
    return incident_id, data


def timeline(incident_id):
    return [(n["channel"], n["status"]) for n in incidents.get_incident(incident_id)["notifications"]]


def buttons(markup):
    return [b.callback_data.rsplit(":", 1)[-1] for row in markup.keyboard for b in row]


class AlertPolicyTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        keys = ("ALERTS_ENABLED", "DEMO_MODE", "DEMO_ESCALATION_DELAY_S", "DEMO_PHONE_NUMBER", "DEMO_COOLDOWN_S", "CALL_MIN_CONFIDENCE",
                "TELEGRAM_CHAT_ID_ALLOWLIST", "MAX_CALLS_PER_HOUR", "ACTION_COOLDOWN_S", "AUTO_CALL_CATEGORIES")
        self.saved = {k: getattr(settings, k) for k in keys}
        settings.ALERTS_ENABLED, settings.DEMO_MODE = True, True
        settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE = 0.3, 0, 0.5   # confidence 0.9 would bypass any delay
        settings.DEMO_PHONE_NUMBER, settings.TELEGRAM_CHAT_ID_ALLOWLIST, settings.MAX_CALLS_PER_HOUR = "+919000000011", "", 5
        settings.ACTION_COOLDOWN_S = 60.0
        os.environ.update(TELEGRAM_CHAT_ID="42", OMNIDIM_API_KEY="FAKE", OMNIDIM_AGENT_ID="7")
        self.posts = []

        def fake_post(url, **kw):
            self.posts.append(kw["json"])
            response = MagicMock()
            response.raise_for_status = lambda: None
            return response
        self.patches = [patch.object(ns.requests, "post", side_effect=fake_post), patch.object(ns, "get_nearby_services", return_value=PLAN_LOOKUP)]
        for p in self.patches:
            p.start()
        self.svc = ns.NotificationService()
        self.bot = MagicMock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=7)
        self.bot.send_photo.return_value = SimpleNamespace(message_id=7)
        self.svc._bot = self.bot

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for k, v in self.saved.items():
            setattr(settings, k, v)
        os.environ["TELEGRAM_CHAT_ID"] = ""
        self.svc.stop()

    def _press(self, incident_id, action):
        message = SimpleNamespace(message_id=7, chat=SimpleNamespace(id=42), caption=None, text="x", photo=None)
        return SimpleNamespace(id="cb", data=f"incident:{incident_id}:{action}", message=message,
                               from_user=SimpleNamespace(first_name="Asha", last_name=None, username=None, id=999))

    def _caption(self):
        return self.bot.send_message.call_args[0][1]

    def test_default_auto_call_categories_are_fire_and_crash_only(self):
        self.assertEqual(Path(__file__).exists() and settings.AUTO_CALL_CATEGORIES, "fire,crash")
        for cat in ("fire", "crash", "road_accident"):
            self.assertTrue(ns.auto_call_allowed(cat), cat)
        for cat in ("fall", "assault", "snatching", "women_safety", "other"):
            self.assertFalse(ns.auto_call_allowed(cat), cat)

    def test_experimental_incident_never_calls_by_itself_and_escalate_now_does(self):
        for category in ("fall", "assault", "snatching"):
            with self.subTest(category=category):
                self.posts.clear()
                incident_id, data = make_incident(category, True)
                self.svc._process(data)
                time.sleep(0.8)                                   # far past DEMO_ESCALATION_DELAY_S (0.3 s) and confidence 0.9 >= CALL_MIN_CONFIDENCE
                self.assertEqual(self.posts, [], "an experimental incident must NEVER place a call by itself")
                tl = timeline(incident_id)
                self.assertIn(("telegram", "sent"), tl)
                self.assertIn(("call", "manual_only"), tl)
                self.assertNotIn(("call", "scheduled"), tl)
                self.assertNotIn(("call", "sent"), tl)
                self.assertNotIn(incident_id, self.svc._call_timers)
                # Telegram message: EXPERIMENTAL, confidence, threshold, the three existing buttons
                caption = self._caption()
                self.assertIn("EXPERIMENTAL", caption)
                self.assertIn("Peak confidence: 0.90", caption)
                self.assertIn("Threshold: 0.60", caption)
                self.assertIn("no automatic call", caption)
                markup = self.bot.send_message.call_args.kwargs["reply_markup"]
                self.assertEqual(buttons(markup), ["confirm", "false_alarm", "escalate"])
                self.assertEqual(markup.keyboard[0][0].text, "Acknowledge")
                # Escalate now places the (mocked) call, with the experimental wording
                self.svc._on_callback(self._press(incident_id, "escalate"))
                self.assertTrue(wait_for(lambda: self.posts, 3), "Escalate now must place the call")
                self.assertEqual(len(self.posts), 1)
                self.assertEqual(self.posts[0]["to_number"], "+919000000011")
                spoken = self.posts[0]["call_context"]["alert_message"]
                self.assertIn("EXPERIMENTAL", spoken)
                self.assertIn("confidence 0.90", spoken)
                self.assertIn("threshold 0.60", spoken)
                self.assertIn(("call", "sent"), timeline(incident_id))

    def test_spoken_category_names(self):
        for category, word in (("fall", "Fall"), ("assault", "Violence"), ("snatching", "Snatching")):
            text = ns.build_call_message({"category": category, "place_text": "P", "detection": {"peak_confidence": 0.7, "threshold_applied": 0.6, "experimental": True}}, None)
            self.assertIn(f"{word} detected at P.", text)
            self.assertIn("EXPERIMENTAL", text)

    def test_fire_still_auto_calls_after_the_delay(self):
        incident_id, data = make_incident("fire", False, confidence=0.4, threshold=0.5)
        self.svc._process(data)
        self.assertEqual(self.posts, [])
        self.assertTrue(wait_for(lambda: self.posts, 3))
        self.assertNotIn("EXPERIMENTAL", self.posts[0]["call_context"]["alert_message"])
        self.assertNotIn("EXPERIMENTAL", self._caption())

    def test_acknowledge_and_false_alarm_never_call_for_experimental(self):
        for action in ("confirm", "false_alarm"):
            self.posts.clear()
            incident_id, data = make_incident("fall", True)
            self.svc._process(data)
            self.svc._on_callback(self._press(incident_id, action))
            time.sleep(0.6)
            self.assertEqual(self.posts, [])

    def test_cooldown_is_per_camera_and_category(self):
        a1, d1 = make_incident("fall", True, camera_id="CAM-X")
        a2, d2 = make_incident("fall", True, camera_id="CAM-X")
        a3, d3 = make_incident("fall", True, camera_id="CAM-Y")
        a4, d4 = make_incident("assault", True, camera_id="CAM-X")
        for d in (d1, d2, d3, d4):
            self.svc._process(d)
        self.assertIn(("telegram", "sent"), timeline(a1))
        self.assertIn(("telegram", "suppressed"), timeline(a2))     # same camera + category inside ACTION_COOLDOWN_S
        self.assertIn(("telegram", "sent"), timeline(a3))           # other camera
        self.assertIn(("telegram", "sent"), timeline(a4))           # other category
        self.assertEqual(self.posts, [])

    # --- DEMO_MODE / hard-block / caps unchanged on the escalate path -----------------------------------------
    def test_escalate_to_hard_blocked_or_unset_number_is_blocked(self):
        # (DEMO_PHONE_NUMBER *is* the allowlist, so "not allowlisted" can only mean unset; real emergency numbers are hard-blocked)
        for number in ("112", "+91100", "100", "0108", ""):
            self.posts.clear()
            settings.DEMO_PHONE_NUMBER = number
            incident_id, data = make_incident("assault", True)
            self.svc._process(data)
            self.svc._on_callback(self._press(incident_id, "escalate"))
            time.sleep(0.5)
            self.assertEqual(self.posts, [], number)

    def test_escalate_respects_the_hourly_call_cap(self):
        settings.MAX_CALLS_PER_HOUR = 0
        incident_id, data = make_incident("snatching", True)
        self.svc._process(data)
        self.svc._on_callback(self._press(incident_id, "escalate"))
        time.sleep(0.5)
        self.assertEqual(self.posts, [])
        self.assertIn(("call", "skipped"), timeline(incident_id))

    def test_telegram_to_a_non_allowlisted_chat_is_blocked(self):
        settings.TELEGRAM_CHAT_ID_ALLOWLIST = "999"
        incident_id, data = make_incident("fall", True)
        self.svc._process(data)
        self.assertFalse(self.bot.send_message.called or self.bot.send_photo.called)
        self.assertIn(("telegram", "blocked"), timeline(incident_id))

    def test_alerts_disabled_sends_nothing(self):
        settings.ALERTS_ENABLED = False
        incident_id, data = make_incident("fall", True)
        self.svc._process(data)
        self.assertFalse(self.bot.send_message.called)
        self.assertEqual(self.posts, [])
        self.assertIn(("telegram", "skipped"), timeline(incident_id))


if __name__ == "__main__":
    unittest.main()
