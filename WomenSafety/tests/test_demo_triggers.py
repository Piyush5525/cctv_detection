"""Demo triggers for fall / violence / snatching, DRY RUN, runtime detector toggles and the audit trail.
Real detectors are replaced only where a real clip cannot make them fire (a scripted pose sequence stands in for the
pose pass); nothing is forced: a detector that does not fire creates no incident. All network calls are mocked."""
import os
import sys
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-demo-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

import action_synth as S
from api import db
from api.core.config import settings
from api.models.camera import get_camera
from api.services import audit, camera_workers as cw, clip_replay, demo_clips, demo_trigger
from api.services import incident_service_v2 as incidents
from api.services import notification_service as ns
from api.services.action_detectors import ActionEngine

audit.set_path(Path(_TEST_DIR) / "audit.jsonl")


class FakePose:
    available = True

    def __init__(self, script):
        self.script, self.i = script, 0

    def infer(self, frame):
        persons = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return [(p.box, p.kp) for p in persons]


class NoPose:
    available = False


def write_clip(path: Path, seconds: float, fps: int = 20):
    path.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    rng = np.random.default_rng(1)
    for _ in range(int(seconds * fps)):
        w.write((rng.integers(0, 255, (480, 640, 3)).astype(np.uint8) // 4) + 40)
    w.release()


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ws-demo-root-"))
        self.rec = self.root / "record.json"
        self.p = patch.object(demo_clips, "ROOT", self.root)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_fire_and_crash_always_enabled(self):
        for cat in ("fire", "road_accident", "crash"):
            self.assertEqual(demo_clips.availability(cat, self.rec), (True, ""))

    def test_missing_clip(self):
        ok, reason = demo_clips.availability("fall", self.rec)
        self.assertFalse(ok)
        self.assertIn("clip missing: data/demo/fall.mp4", reason)

    def test_present_but_not_verified(self):
        write_clip(self.root / "data/demo/fall.mp4", 1)
        ok, reason = demo_clips.availability("fall", self.rec)
        self.assertFalse(ok)
        self.assertIn("not verified", reason)

    def test_detector_did_not_fire_on_the_clip(self):
        write_clip(self.root / "data/demo/violence.mp4", 1)
        demo_clips.save_record({"assault": {"fired": False, "peak_score": 0.0, "threshold": 0.28}}, self.rec)
        ok, reason = demo_clips.availability("violence", self.rec)      # alias accepted
        self.assertFalse(ok)
        self.assertIn("detector did not fire on the sample clip", reason)

    def test_enabled_only_when_clip_exists_and_fired_and_unchanged(self):
        clip = self.root / "data/demo/snatch.mp4"
        write_clip(clip, 1)
        demo_clips.save_record({"snatching": {"fired": True, "peak_score": 0.8, "threshold": 0.7}}, self.rec)
        self.assertEqual(demo_clips.availability("snatching", self.rec), (True, ""))
        write_clip(clip, 2)                                              # replaced clip => verification no longer applies
        ok, reason = demo_clips.availability("snatching", self.rec)
        self.assertFalse(ok)
        self.assertIn("changed", reason)

    def test_categories_lists_all_five_with_experimental_flags(self):
        cats = {c["category"]: c for c in demo_clips.categories(self.rec)}
        self.assertEqual(set(cats), {"fire", "road_accident", "fall", "assault", "snatching"})
        self.assertTrue(cats["fire"]["enabled"] and not cats["fire"]["experimental"])
        for c in ("fall", "assault", "snatching"):
            self.assertTrue(cats[c]["experimental"])
            self.assertFalse(cats[c]["enabled"])
            self.assertTrue(cats[c]["reason"])


class TriggerTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.root = Path(tempfile.mkdtemp(prefix="ws-demo-root-"))
        self.rec = self.root / "record.json"
        self.patches = [patch.object(demo_clips, "ROOT", self.root), patch.object(demo_clips, "RECORD_PATH", self.rec),
                        patch.object(demo_trigger, "_ROOT", self.root)]
        for p in self.patches:
            p.start()
        settings.DEMO_TOKEN = "test-token"
        from fastapi.testclient import TestClient
        from api.main import app
        self.client_cm = TestClient(app)
        self.client = self.client_cm.__enter__()
        self.hdr = {"X-Demo-Token": "test-token"}

    def tearDown(self):
        self.client_cm.__exit__(None, None, None)
        for p in self.patches:
            p.stop()
        settings.DEMO_TOKEN = ""

    def _trigger(self, category, camera="CAM-SAMPLE-001"):
        return self.client.post("/api/v1/demo/trigger", json={"camera_id": camera, "category": category}, headers=self.hdr)

    def _fall_clip(self, fired_record=True):
        seq = S.true_fall(stay_s=4.0) + S.stand_frames(2)
        write_clip(self.root / "data/demo/fall.mp4", 7.5)
        demo_clips.save_record({"fall": {"fired": fired_record, "peak_score": 0.9, "threshold": 0.6}}, self.rec)
        real = clip_replay.replay_clip
        return seq, patch("api.services.clip_replay.replay_clip", side_effect=lambda *a, **k: real(*a, pose=FakePose(seq), **k))

    def test_clip_missing_is_409_with_reason_and_creates_nothing(self):
        before = len(incidents.list_incidents(category="fall"))
        r = self._trigger("fall")
        self.assertEqual(r.status_code, 409)
        self.assertIn("clip missing", r.json()["detail"])
        self.assertEqual(len(incidents.list_incidents(category="fall")), before)

    def test_detector_not_firing_on_the_clip_is_409_and_never_forced(self):
        write_clip(self.root / "data/demo/snatch.mp4", 2)
        demo_clips.save_record({"snatching": {"fired": False, "peak_score": 0.0, "threshold": 0.7}}, self.rec)
        before = len(incidents.list_incidents(category="snatching"))
        r = self._trigger("snatching")
        self.assertEqual(r.status_code, 409)
        self.assertIn("did not fire", r.json()["detail"])
        self.assertEqual(len(incidents.list_incidents(category="snatching")), before)

    def test_recorded_as_fired_but_replay_does_not_fire_says_so_plainly(self):
        write_clip(self.root / "data/demo/fall.mp4", 4)
        demo_clips.save_record({"fall": {"fired": True, "peak_score": 0.9, "threshold": 0.6}}, self.rec)
        real = clip_replay.replay_clip
        quiet = S.stand_frames(20)                                        # nobody falls
        before = len(incidents.list_incidents(category="fall"))
        with patch("api.services.clip_replay.replay_clip", side_effect=lambda *a, **k: real(*a, pose=FakePose(quiet), **k)):
            r = self._trigger("fall")
        self.assertEqual(r.status_code, 409)
        self.assertIn("did not fire on the sample clip this time", r.json()["detail"])
        self.assertEqual(len(incidents.list_incidents(category="fall")), before)

    def test_fired_creates_a_real_experimental_incident_through_the_same_pipeline(self):
        seq, replay_patch = self._fall_clip()
        with replay_patch:
            r = self._trigger("fall")
        self.assertEqual(r.status_code, 200, r.text)
        inc = incidents.get_incident(r.json()["incident_id"])
        self.assertEqual(inc["category"], "fall")
        self.assertEqual(inc["source"], "test_replay")
        self.assertIn("synthetic demo trigger", inc["evidence"]["note"])
        det = inc["detection"]
        self.assertTrue(det["experimental"])
        self.assertEqual(det["detector_source"], "pose-fall-rules")
        self.assertGreaterEqual(det["peak_confidence"], det["threshold_applied"])
        self.assertIn("stay_down_s", det["signals"])
        self.assertNotIn("keypoints", json.dumps(inc))
        self.assertIsNotNone(inc["video_offset_start_s"])                # replay position recorded
        for key in ("best_frame_path", "annotated_frame_path", "thumbnail_path", "clip_path"):
            self.assertTrue(Path(inc["evidence"][key]).exists(), key)
        best = cv2.imread(inc["evidence"]["best_frame_path"])
        self.assertTrue(((best[..., 2] > 200) & (best[..., 1] < 80) & (best[..., 0] < 80)).any(), "overlay missing on best frame")

    def test_violence_alias_and_unknown_category(self):
        self.assertEqual(self._trigger("violence").status_code, 409)       # alias of assault: clip missing here
        self.assertEqual(self._trigger("no-such").status_code, 422)

    def test_trigger_requires_the_token(self):
        r = self.client.post("/api/v1/demo/trigger", json={"camera_id": "CAM-SAMPLE-001", "category": "fall"})
        self.assertEqual(r.status_code, 403)

    def test_fire_and_crash_still_use_the_stored_sample_path(self):
        frame = np.full((480, 640, 3), 120, np.uint8)
        pick = {"frame": frame, "confidence": 0.9, "boxes": [{"class": "fire", "confidence": 0.9, "box": [10, 10, 200, 200]}], "t_s": 3.0,
                "real_detection": False, "detector": None}
        with patch.object(demo_trigger, "_pick_frame", return_value=pick), patch.object(demo_trigger, "trigger_action_incident",
                                                                                        side_effect=AssertionError("fire must not use the action path")):
            inc = demo_trigger.trigger_demo_incident("CAM-SAMPLE-001", "fire")
        self.assertEqual(inc["category"], "fire")
        self.assertFalse(inc["detection"].get("experimental", False))
        self.assertIn("synthetic demo trigger", inc["evidence"]["note"])

    def test_demo_state_is_public_and_carries_no_secrets(self):
        r = self.client.get("/api/v1/demo-state")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual({c["category"] for c in body["categories"]}, {"fire", "road_accident", "fall", "assault", "snatching"})
        self.assertIn("dry_run", body)
        text = json.dumps(body)
        for forbidden in ("test-token", "latitude", "longitude", "stream"):
            self.assertNotIn(forbidden, text)


class DryRunTests(unittest.TestCase):
    PLAN = {"source": "cache", "services": {"hospital": [{"title": "H", "category": "hospital", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
                                           "police": [{"title": "P", "category": "police", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}], "fire": []}}

    def setUp(self):
        db.init_db()
        keys = ("ALERTS_ENABLED", "DEMO_MODE", "DEMO_ESCALATION_DELAY_S", "DEMO_PHONE_NUMBER", "DEMO_COOLDOWN_S", "CALL_MIN_CONFIDENCE", "DEMO_DRY_RUN", "TELEGRAM_CHAT_ID_ALLOWLIST")
        self.saved = {k: getattr(settings, k) for k in keys}
        settings.ALERTS_ENABLED, settings.DEMO_MODE, settings.DEMO_ESCALATION_DELAY_S = True, True, 0.2
        settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE, settings.DEMO_PHONE_NUMBER = 0, 0.5, "+919000000011"
        settings.TELEGRAM_CHAT_ID_ALLOWLIST = ""
        os.environ.update(TELEGRAM_CHAT_ID="42", OMNIDIM_API_KEY="FAKE", OMNIDIM_AGENT_ID="7")
        self.posts = []

        def fake_post(url, **kw):
            self.posts.append(kw["json"])
            m = MagicMock()
            m.raise_for_status = lambda: None
            return m
        self.patches = [patch.object(ns.requests, "post", side_effect=fake_post), patch.object(ns, "get_nearby_services", return_value=self.PLAN)]
        for p in self.patches:
            p.start()
        self.svc = ns.NotificationService()
        self.bot = MagicMock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=7)
        self.svc._bot = self.bot

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for k, v in self.saved.items():
            setattr(settings, k, v)
        os.environ["TELEGRAM_CHAT_ID"] = ""
        self.svc.stop()

    def _incident(self, category, experimental):
        iid = str(uuid.uuid4())
        data = {"incident_id": iid, "camera_id": f"CAM-{iid[:4]}", "camera_name": "Cam", "place_text": "Place", "latitude": 26.9, "longitude": 75.8,
                "category": category, "status": "new", "source": "test_replay", "event_start": "2026-10-01T00:00:00+00:00", "detected_at": "2026-10-01T00:00:00+00:00",
                "detection": {"peak_confidence": 0.9, "threshold_applied": 0.5, "experimental": experimental, "signals": {}}, "evidence": {}, "notifications": []}
        db.insert_incident(iid, data["camera_id"], category, "new", "test_replay", data["event_start"], data)
        return iid, data

    def _timeline(self, iid):
        return [(n["channel"], n["status"]) for n in incidents.get_incident(iid)["notifications"]]

    def test_dry_run_suppresses_the_auto_call_but_telegram_stays_real(self):
        settings.DEMO_DRY_RUN = True
        iid, data = self._incident("fire", False)
        self.svc._process(data)
        time.sleep(0.8)
        self.assertEqual(self.posts, [])
        tl = self._timeline(iid)
        self.assertIn(("telegram", "sent"), tl)
        self.assertIn(("call", "suppressed"), tl)
        detail = [n["detail"] for n in incidents.get_incident(iid)["notifications"] if n["channel"] == "call" and n["status"] == "suppressed"]
        self.assertEqual(detail, ["suppressed: dry run"])
        self.assertTrue(self.bot.send_message.called)

    def test_dry_run_off_still_auto_calls_fire(self):
        settings.DEMO_DRY_RUN = False
        iid, data = self._incident("fire", False)
        self.svc._process(data)
        time.sleep(0.9)
        self.assertEqual(len(self.posts), 1)

    def test_escalate_now_is_also_suppressed_in_dry_run(self):
        settings.DEMO_DRY_RUN = True
        iid, data = self._incident("assault", True)
        self.svc._process(data)
        self.svc.process_press(iid, "escalate", "Asha", None, edit=False)
        time.sleep(0.6)
        self.assertEqual(self.posts, [])
        self.assertIn(("call", "suppressed"), self._timeline(iid))

    def test_experimental_never_auto_calls_and_escalate_calls_when_not_dry(self):
        for category in ("fall", "assault", "snatching"):
            self.posts.clear()
            settings.DEMO_DRY_RUN = False
            iid, data = self._incident(category, True)
            self.svc._process(data)
            time.sleep(0.7)
            self.assertEqual(self.posts, [], f"{category} must not call by itself")
            self.svc.process_press(iid, "escalate", "Asha", None, edit=False)
            end = time.time() + 3
            while not self.posts and time.time() < end:
                time.sleep(0.05)
            self.assertEqual(len(self.posts), 1, f"{category}: Escalate now must call")

    def test_dry_run_endpoint_toggles_and_is_audited_and_header_visible(self):
        settings.DEMO_TOKEN = "test-token"
        from fastapi.testclient import TestClient
        from api.main import app
        try:
            with TestClient(app) as client:
                hdr = {"X-Demo-Token": "test-token"}
                self.assertEqual(client.post("/api/v1/demo/dry-run", json={"enabled": True}).status_code, 403)
                self.assertEqual(client.post("/api/v1/demo/dry-run", json={"enabled": True}, headers=hdr).json(), {"dry_run": True})
                self.assertTrue(client.get("/api/v1/demo-state").json()["dry_run"])
                client.post("/api/v1/demo/dry-run", json={"enabled": False}, headers=hdr)
                self.assertFalse(settings.DEMO_DRY_RUN)
                self.assertTrue(any(e["action"] == "dry_run" for e in audit.entries()))
        finally:
            settings.DEMO_TOKEN = ""


class RuntimeToggleTests(unittest.TestCase):
    def setUp(self):
        self.cam = get_camera("CAM-SAMPLE-002")                          # default detectors: fire, crash
        self.made = []

        def make_engine(camera_id, names, on_verdict=None, **kw):
            self.made.append(list(names))
            return ActionEngine(camera_id, names, on_verdict=on_verdict, pose=FakePose([S.stand_frames(1)[0]]), pose_interval_s=0.25, max_width=640)
        self.patch = patch.object(cw, "ActionEngine", make_engine)
        self.patch.start()
        self.worker = cw.CameraWorker(self.cam, registry=None, detector_lock=None)
        audit.clear()

    def tearDown(self):
        self.patch.stop()

    def test_default_has_no_action_engine(self):
        self.assertEqual(self.worker.detectors, ["fire", "crash"])
        self.assertIsNone(self.worker.action)
        self.assertEqual(self.made, [])

    def test_enable_and_disable_without_restart(self):
        applied = self.worker.set_detectors(["fire", "crash", "fall", "violence"])
        self.assertEqual(applied, ["fire", "crash", "fall", "violence"])
        self.assertEqual(sorted(self.worker.action_pipelines), ["fall", "violence"])
        self.assertIsNotNone(self.worker.action)
        self.assertEqual(self.worker.detail()["detectors"], ["fire", "crash", "fall", "violence"])   # shown on the camera tile
        self.worker.set_detectors(["fire", "crash"])
        self.assertIsNone(self.worker.action)
        self.assertEqual(self.worker.action_pipelines, {})

    def test_fire_and_crash_can_be_toggled_off_and_are_honoured(self):
        class Det:
            def __init__(self, name):
                self.name, self.threshold = name, 0.5

            def detect(self, frame):
                return SimpleNamespace(detection=self.name.title(), confidence=0.9, boxes=[])
        self.worker.registry = SimpleNamespace(all=lambda: [Det("fire"), Det("crash")])
        self.worker.detector_lock = __import__("threading").Lock()
        frame = np.zeros((100, 100, 3), np.uint8)
        self.assertIn(self.worker._detect(frame)["category"], ("fire", "crash"))
        self.worker.set_detectors(["crash"])
        self.assertEqual(self.worker._detect(frame)["category"], "crash")
        self.worker.set_detectors([])
        self.assertIsNone(self.worker._detect(frame)["category"])

    def test_unknown_names_are_ignored_and_order_is_canonical(self):
        self.assertEqual(self.worker.set_detectors(["snatch", "bogus", "fire"]), ["fire", "snatch"])

    def test_pose_model_unavailable_refuses_cleanly(self):
        def no_pose(camera_id, names, on_verdict=None, **kw):
            return ActionEngine(camera_id, names, on_verdict=on_verdict, pose=NoPose())
        with patch.object(cw, "ActionEngine", no_pose):
            with self.assertRaises(RuntimeError):
                self.worker.set_detectors(["fire", "crash", "fall"])
        self.assertEqual(self.worker.detectors, ["fire", "crash"])         # unchanged on failure

    def test_toggle_endpoint_applies_live_and_writes_the_audit_trail(self):
        settings.DEMO_TOKEN = "test-token"
        from fastapi.testclient import TestClient
        from api.main import app
        hdr = {"X-Demo-Token": "test-token"}
        try:
            self.worker.stop = lambda: None            # the app's shutdown stops every registered worker; this one was never started
            with patch.dict(cw.camera_workers.workers, {"CAM-SAMPLE-002": self.worker}):
                with TestClient(app) as client:
                    self.assertEqual(client.post("/api/v1/demo/detectors", json={"camera_id": "CAM-SAMPLE-002", "detector": "fall", "enabled": True}).status_code, 403)
                    r = client.post("/api/v1/demo/detectors", json={"camera_id": "CAM-SAMPLE-002", "detector": "fall", "enabled": True}, headers=hdr)
                    self.assertEqual(r.json()["detectors"], ["fire", "crash", "fall"])
                    r = client.post("/api/v1/demo/detectors", json={"camera_id": "CAM-SAMPLE-002", "detector": "fire", "enabled": False}, headers=hdr)
                    self.assertEqual(r.json()["detectors"], ["crash", "fall"])
                    self.assertEqual(client.post("/api/v1/demo/detectors", json={"camera_id": "CAM-SAMPLE-002", "detector": "nope", "enabled": True}, headers=hdr).status_code, 422)
                    self.assertEqual(client.post("/api/v1/demo/detectors", json={"camera_id": "CAM-NOPE", "detector": "fall", "enabled": True}, headers=hdr).status_code, 409)
            logged = [e["detail"] for e in audit.entries() if e["action"] == "detector_toggle"]
            self.assertEqual(len(logged), 2)
            self.assertIn("fall on", logged[1])
            self.assertTrue((Path(_TEST_DIR) / "audit.jsonl").exists())
        finally:
            settings.DEMO_TOKEN = ""


if __name__ == "__main__":
    unittest.main()
