"""SCRIPTED demo incidents (fall / violence / snatching): created from a clip + data/demo/demo_events.yaml, NO detector run,
null confidence, the SCRIPTED DEMO label everywhere, no auto-call by default, opt-in SCRIPTED_AUTO_CALL with every safety rule.
Clips are tiny synthetic videos; all network calls are mocked."""
import json
import os
import subprocess
import sys
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-scripted-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from api import db
from api.core.config import settings
from api.services import audit, demo_clips, demo_events, demo_trigger
from api.services import incident_service_v2 as incidents
from api.services import notification_service as ns
from api.services.notification_service import notification_service as global_notification_service

CAMERA = "CAM-SAMPLE-001"
ENTRIES = {"fall": (3.0, 6.0, 4.0), "violence": (2.0, 5.5, 3.5), "snatching": (4.0, 7.0, 5.0)}
CLIP_FILES = {"fall": "fall.mp4", "violence": "violence.mp4", "snatching": "snatch.mp4"}
CATEGORY = {"fall": "fall", "violence": "assault", "snatching": "snatching"}
LOOKUP = {"source": "cache", "services": {
    "hospital": [{"title": "Test Hospital", "category": "hospital", "distance_km": 1.5, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}],
    "police": [{"title": "Test Police Station", "category": "police", "distance_km": 0.7, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}],
    "fire": [{"title": "Test Fire Station", "category": "fire", "distance_km": 2.0, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}]}}


def write_clip(path: Path, seconds=8.0, fps=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    rng = np.random.default_rng(3)
    for i in range(int(seconds * fps)):
        f = (rng.integers(0, 255, (240, 320, 3)).astype(np.uint8) // 5) + 30
        cv2.putText(f, str(i), (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
        w.write(f)
    w.release()


def write_yaml(path: Path, entries=ENTRIES, placeholder=False, extra=""):
    lines = ["REPLACE_ME: true"] if placeholder else []
    for key, (a, b, best) in entries.items():
        lines += [f"{key}:", f"  clip: data/demo/{CLIP_FILES[key]}", f"  event_start_s: {a}", f"  event_end_s: {b}", f"  best_frame_s: {best}"]
    path.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")


class ScriptedBase(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.root = Path(tempfile.mkdtemp(prefix="ws-scripted-root-"))
        for f in CLIP_FILES.values():
            write_clip(self.root / "data" / "demo" / f)
        self.yaml = self.root / "data" / "demo" / "demo_events.yaml"
        write_yaml(self.yaml)
        self.saved = {k: getattr(settings, k) for k in ("DEMO_EVENTS_PATH", "ALERTS_ENABLED", "DEMO_MODE", "SCRIPTED_AUTO_CALL", "DEMO_DRY_RUN", "DEMO_PHONE_NUMBER",
                                                         "DEMO_ESCALATION_DELAY_S", "DEMO_COOLDOWN_S", "ACTION_COOLDOWN_S", "MAX_CALLS_PER_HOUR", "TELEGRAM_CHAT_ID_ALLOWLIST")}
        settings.DEMO_EVENTS_PATH = self.yaml
        self.patches = [patch.object(demo_events, "ROOT", self.root), patch.object(demo_events, "DEMO_DIR", self.root / "data" / "demo"),
                        patch.object(demo_trigger, "_ROOT", self.root), patch.object(demo_trigger, "_real_skeleton_boxes", return_value=[])]
        for p in self.patches:
            p.start()
        global_notification_service._last_by_key.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for k, v in self.saved.items():
            setattr(settings, k, v)
        os.environ["TELEGRAM_CHAT_ID"] = ""
        global_notification_service._last_by_key.clear()

    def wait_plan(self, iid, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            inc = incidents.get_incident(iid)
            if inc and inc.get("dispatch_plan") and inc.get("notifications"):
                return inc
            time.sleep(0.1)
        self.fail("dispatch plan / notifications never appeared")


class ConfigTests(ScriptedBase):
    def test_valid_config_enables_all_three(self):
        cfg = demo_events.load()
        self.assertFalse(cfg["placeholder"])
        self.assertEqual(sorted(cfg["events"]), ["fall", "snatching", "violence"])
        self.assertEqual(cfg["errors"], {})
        ev = cfg["events"]["violence"]
        self.assertEqual((ev.category, ev.start_s, ev.end_s, ev.best_s, ev.clip_rel), ("assault", 2.0, 5.5, 3.5, "data/demo/violence.mp4"))
        cats = {c["category"]: c for c in demo_clips.categories()}
        self.assertEqual({k: cats[k]["enabled"] for k in ("fire", "road_accident", "fall", "assault", "snatching")}, {k: True for k in ("fire", "road_accident", "fall", "assault", "snatching")})
        self.assertTrue(all(cats[k]["scripted"] and cats[k]["experimental"] for k in ("fall", "assault", "snatching")))
        self.assertFalse(cats["fire"]["scripted"])

    def test_replace_me_marker_disables_every_scripted_category_and_refuses_the_trigger(self):
        write_yaml(self.yaml, placeholder=True)
        cfg = demo_events.load()
        self.assertTrue(cfg["placeholder"])
        for c in demo_clips.categories():
            if c["category"] in ("fall", "assault", "snatching"):
                self.assertFalse(c["enabled"])
                self.assertIn("REPLACE_ME", c["reason"])
        for cat in ("fall", "violence", "assault", "snatching", "snatch"):
            with self.assertRaises(demo_trigger.DemoUnavailable) as cm:
                demo_trigger.trigger_demo_incident(CAMERA, cat)
            self.assertIn("REPLACE_ME", str(cm.exception))
        self.assertEqual(incidents.list_incidents(camera_id=CAMERA, category="fall"), [])

    def test_fire_and_crash_stay_enabled_whatever_the_yaml_says(self):
        write_yaml(self.yaml, placeholder=True)
        cats = {c["category"]: c for c in demo_clips.categories()}
        self.assertTrue(cats["fire"]["enabled"] and cats["road_accident"]["enabled"])

    def test_missing_clip_disables_only_that_category(self):
        (self.root / "data" / "demo" / "fall.mp4").unlink()
        cfg = demo_events.load()
        self.assertIn("clip missing: data/demo/fall.mp4", cfg["errors"]["fall"])
        self.assertEqual(sorted(cfg["events"]), ["snatching", "violence"])
        with self.assertRaises(demo_trigger.DemoUnavailable) as cm:
            demo_trigger.trigger_demo_incident(CAMERA, "fall")
        self.assertIn("clip missing", str(cm.exception))

    def test_missing_entry_is_disabled_with_a_reason(self):
        write_yaml(self.yaml, entries={"fall": ENTRIES["fall"], "snatching": ENTRIES["snatching"]})
        ok, reason = demo_events.availability("violence")
        self.assertFalse(ok)
        self.assertIn("no entry for violence", reason)

    def test_invalid_windows_are_rejected(self):
        bad = {
            "past the end of the clip": (3.0, 20.0, 4.0),
            "negative start": (-1.0, 4.0, 2.0),
            "end before start": (5.0, 4.0, 4.5),
            "best frame outside the window": (3.0, 6.0, 7.0),
            "best frame before the window": (3.0, 6.0, 1.0),
        }
        for label, entry in bad.items():
            write_yaml(self.yaml, entries={"fall": entry})
            ok, reason = demo_events.availability("fall")
            self.assertFalse(ok, label)
            self.assertTrue(reason, label)
        write_yaml(self.yaml, entries={"fall": ENTRIES["fall"]}, extra="")
        txt = self.yaml.read_text().replace("event_start_s: 3.0", "event_start_s: soon")
        self.yaml.write_text(txt)
        self.assertIn("number", demo_events.availability("fall")[1])

    def test_clip_outside_data_demo_and_bad_yaml_are_rejected(self):
        self.yaml.write_text("fall:\n  clip: ../../etc/other.mp4\n  event_start_s: 1\n  event_end_s: 2\n  best_frame_s: 1.5\n")
        self.assertIn("inside data/demo", demo_events.availability("fall")[1])
        self.yaml.write_text("fall: [unclosed\n")
        self.assertIn("not valid YAML", demo_events.availability("fall")[1])
        self.yaml.unlink()
        self.assertIn("not found", demo_events.availability("fall")[1])


class TriggerTests(ScriptedBase):
    def _no_detector(self):
        """Any detector (fire/crash registry, action engine, event verdict feed) raising makes a test fail if it is invoked."""
        boom = AssertionError("a detector was invoked on a scripted clip")
        return [patch("api.services.action_detectors.engine.ActionEngine.process", side_effect=boom),
                patch("api.services.detector_interface.DetectorRegistry.__init__", side_effect=boom),
                patch("api.services.event_capture.EventCapturePipeline.feed_detection", side_effect=boom),
                patch("api.services.clip_replay.replay_clip", side_effect=boom)]

    def trigger(self, key, **kw):
        for p in self._no_detector():
            p.start()
            self.addCleanup(p.stop)
        return demo_trigger.trigger_demo_incident(CAMERA, key)

    def test_each_category_creates_a_scripted_incident_with_null_confidence_and_no_detector(self):
        for key, (start, end, best) in ENTRIES.items():
            with self.subTest(key=key), patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
                created = self.trigger(key)
                inc = self.wait_plan(created["incident_id"])
                det = inc["detection"]
                self.assertEqual(inc["category"], CATEGORY[key])
                self.assertEqual(inc["source"], "test_replay")
                self.assertEqual((det["peak_confidence"], det["mean_confidence"], det["threshold_applied"]), (None, None, None))
                self.assertEqual((det["detector_source"], det["scripted"], det["verified"], det["experimental"]), ("scripted_demo", True, False, True))
                self.assertEqual((det["signals"], det["best_frame_bbox"]), ({}, []))
                self.assertEqual(det["note"], "Scripted demo incident - category set by the demo script, not a detector result")
                self.assertTrue(inc["evidence"]["note"].startswith("Scripted demo incident - category set by the demo script, not a detector result."))
                self.assertIn(f"{start:g}-{end:g} s", inc["evidence"]["note"])
                self.assertIn(f"best frame at {best:g} s", inc["evidence"]["note"])
                self.assertAlmostEqual(inc["video_offset_start_s"], start, delta=0.2)
                self.assertAlmostEqual(inc["video_offset_end_s"], end, delta=0.2)

    def test_dispatch_services_follow_dispatch_rules_from_the_cache_only(self):
        expect = {"fall": [("hospital", "Test Hospital")], "violence": [("police", "Test Police Station")], "snatching": [("police", "Test Police Station")]}
        for key, want in expect.items():
            with self.subTest(key=key), patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
                inc = self.wait_plan(self.trigger(key)["incident_id"])
                got = [(a["service_category"], (a.get("service") or {}).get("title")) for a in inc["dispatch_plan"]["assignments"]]
                self.assertEqual(got, want)
                self.assertEqual(inc["dispatch_plan"]["nearby_services_source"], "cache")

    def test_uncached_cell_shows_services_unavailable_and_never_calls_serpapi_or_fabricates(self):
        with patch("api.services.nearby_services.lookup_cached", return_value=None), \
                patch.object(ns, "get_nearby_services", side_effect=AssertionError("a scripted incident must not use the live lookup")), \
                patch("api.services.nearby_services._query_serpapi", side_effect=AssertionError("SerpApi must not be called")):
            inc = self.wait_plan(self.trigger("fall")["incident_id"])
        plan = inc["dispatch_plan"]
        self.assertEqual(plan["nearby_services_source"], "unavailable")
        self.assertEqual([(a["service_category"], a["status"]) for a in plan["assignments"]], [("hospital", "unavailable")])
        self.assertNotIn("service", plan["assignments"][0])

    def test_evidence_files_and_the_clip_are_browser_playable(self):
        with patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
            inc = self.wait_plan(self.trigger("fall")["incident_id"])
        ev = inc["evidence"]
        names = {k: Path(ev[k]).name for k in ("best_frame_path", "thumbnail_path", "clip_path")}
        self.assertEqual(names, {"best_frame_path": "best_frame.jpg", "thumbnail_path": "thumbnail.jpg", "clip_path": "clip.mp4"})
        self.assertIsNone(ev["annotated_frame_path"])                     # nothing real to draw: no annotated frame, no overlay
        for k in ("best_frame_path", "thumbnail_path", "clip_path"):
            self.assertTrue(Path(ev[k]).exists(), k)
        self.assertEqual(Path(ev["best_frame_path"]).parent.parent.parent.name, CAMERA)    # same camera/date/incident layout as every incident
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt:format=duration",
                                           "-of", "json", ev["clip_path"]], capture_output=True, text=True).stdout)
        self.assertEqual((probe["streams"][0]["codec_name"], probe["streams"][0]["pix_fmt"]), ("h264", "yuv420p"))
        head = Path(ev["clip_path"]).read_bytes()
        self.assertLess(head.find(b"moov"), head.find(b"mdat"))              # +faststart
        # the clip covers the pre-event seconds + the event window (fall: 3 s of pre-event, window 3-6 s => about 6 s)
        self.assertAlmostEqual(float(probe["format"]["duration"]), 6.0, delta=0.6)
        # the best frame is the frame at best_frame_s, with NO overlay (frame counter text drawn into the clip shows frame 40 = 4.0 s)
        best = cv2.imread(ev["best_frame_path"])
        self.assertEqual(best.shape[:2], (240, 320))

    def test_best_frame_has_no_overlay_and_a_real_skeleton_only_goes_into_the_annotated_frame(self):
        skeleton = [{"label": "", "confidence": 0.0, "box": [50, 50, 150, 220], "skeleton_only": True,
                     "keypoints": [[100 + i, 60 + 10 * i, 0.9] for i in range(17)]}]
        with patch.object(demo_trigger, "_real_skeleton_boxes", return_value=skeleton), patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
            inc = self.wait_plan(self.trigger("violence")["incident_id"])
        ev = inc["evidence"]
        self.assertTrue(Path(ev["annotated_frame_path"]).exists())
        raw, annotated = cv2.imread(ev["best_frame_path"]), cv2.imread(ev["annotated_frame_path"])
        self.assertTrue(((annotated[..., 1] > 180) & (annotated[..., 2] < 80)).any(), "skeleton drawn in the annotated frame")
        self.assertFalse(((raw[..., 1] > 180) & (raw[..., 2] < 80) & (raw[..., 0] < 80)).any(), "best frame stays raw")
        self.assertIn("skeleton in the annotated frame comes from the real pose model", ev["note"])
        text = json.dumps(inc)
        self.assertNotIn("keypoints", text)                                  # never stored as data
        self.assertEqual(inc["detection"]["best_frame_bbox"], [])

    def test_cooldown_for_the_camera_and_category_returns_a_clear_message(self):
        settings.ACTION_COOLDOWN_S = 60.0
        global_notification_service._last_by_key[(CAMERA, "fall")] = time.monotonic()
        with self.assertRaises(demo_trigger.DemoUnavailable) as cm:
            demo_trigger.trigger_demo_incident(CAMERA, "fall")
        self.assertRegex(str(cm.exception), r"Cooldown active for Fall on this camera: wait \d+ s")
        self.assertEqual(incidents.list_incidents(camera_id=CAMERA, category="fall"), [])
        with patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
            self.wait_plan(demo_trigger.trigger_demo_incident(CAMERA, "snatching")["incident_id"])   # other category: not in cooldown

    def test_trigger_endpoint_returns_409_with_the_reason_and_200_when_valid(self):
        settings.DEMO_TOKEN = "t"
        from fastapi.testclient import TestClient
        from api.main import app
        try:
            with TestClient(app) as client:
                h = {"X-Demo-Token": "t"}
                write_yaml(self.yaml, placeholder=True)
                r = client.post("/api/v1/demo/trigger", json={"camera_id": CAMERA, "category": "fall"}, headers=h)
                self.assertEqual(r.status_code, 409)
                self.assertIn("REPLACE_ME", r.json()["detail"])
                write_yaml(self.yaml)
                (self.root / "data" / "demo" / "violence.mp4").unlink()
                r = client.post("/api/v1/demo/trigger", json={"camera_id": CAMERA, "category": "violence"}, headers=h)
                self.assertEqual((r.status_code, "clip missing" in r.json()["detail"]), (409, True))
                with patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP):
                    r = client.post("/api/v1/demo/trigger", json={"camera_id": CAMERA, "category": "snatching"}, headers=h)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["category"], "snatching")
                self.assertIsNone(r.json()["detection"]["peak_confidence"])
                state = client.get("/api/v1/demo-state").json()
                cats = {c["category"]: c for c in state["categories"]}
                self.assertTrue(cats["snatching"]["enabled"] and cats["fall"]["enabled"])
                self.assertFalse(cats["assault"]["enabled"])
                self.assertIn("clip missing", cats["assault"]["reason"])
        finally:
            settings.DEMO_TOKEN = ""


def scripted_incident_dict(category="fall", camera_id=None, **detection_over):
    iid = str(uuid.uuid4())
    data = {"incident_id": iid, "camera_id": camera_id or f"CAM-{iid[:4]}", "camera_name": "Demo phone camera - CAM 001", "place_text": "MI Road, Jaipur", "latitude": 26.9,
            "longitude": 75.8, "category": category, "status": "new", "source": "test_replay", "event_start": "2026-10-01T00:00:00+00:00",
            "detected_at": "2026-10-01T00:00:00+00:00",
            "detection": {"detector_source": "scripted_demo", "scripted": True, "verified": False, "experimental": True, "peak_confidence": None,
                          "mean_confidence": None, "threshold_applied": None, "signals": {}, **detection_over},
            "evidence": {}, "notifications": []}
    db.insert_incident(iid, data["camera_id"], category, "new", "test_replay", data["event_start"], data)
    return iid, data


class NotificationBase(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.saved = {k: getattr(settings, k) for k in ("ALERTS_ENABLED", "DEMO_MODE", "SCRIPTED_AUTO_CALL", "DEMO_DRY_RUN", "DEMO_PHONE_NUMBER", "DEMO_ESCALATION_DELAY_S",
                                                         "DEMO_COOLDOWN_S", "ACTION_COOLDOWN_S", "MAX_CALLS_PER_HOUR", "TELEGRAM_CHAT_ID_ALLOWLIST", "CALL_MIN_CONFIDENCE")}
        settings.ALERTS_ENABLED, settings.DEMO_MODE, settings.SCRIPTED_AUTO_CALL, settings.DEMO_DRY_RUN = True, True, False, False
        settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_COOLDOWN_S, settings.ACTION_COOLDOWN_S, settings.MAX_CALLS_PER_HOUR = 0.3, 0, 0, 5
        settings.DEMO_PHONE_NUMBER, settings.TELEGRAM_CHAT_ID_ALLOWLIST = "+919000000011", ""
        os.environ.update(TELEGRAM_CHAT_ID="42", OMNIDIM_API_KEY="FAKE", OMNIDIM_AGENT_ID="7")
        self.posts = []

        def fake_post(url, **kw):
            self.posts.append(kw["json"])
            m = MagicMock()
            m.raise_for_status = lambda: None
            return m
        self.patches = [patch.object(ns.requests, "post", side_effect=fake_post), patch("api.services.nearby_services.lookup_cached", return_value=LOOKUP)]
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

    def timeline(self, iid):
        return [(n["channel"], n["status"]) for n in incidents.get_incident(iid)["notifications"]]

    def press(self, iid, action):
        return self.svc.process_press(iid, action, "Asha", None, edit=False)

    def caption(self):
        c = self.bot.send_message.call_args or self.bot.send_photo.call_args
        return c.kwargs.get("caption") or c[0][1]


class TelegramAndCallTests(NotificationBase):
    def test_telegram_caption_is_scripted_experimental_not_scored_and_within_limits(self):
        for category, shown, primary in (("fall", "Fall", "hospital: Test Hospital (1.5 km)"), ("assault", "Violence", "police station: Test Police Station (0.7 km)"),
                                         ("snatching", "Snatching", "police station: Test Police Station (0.7 km)")):
            with self.subTest(category=category):
                self.bot.reset_mock()
                iid, data = scripted_incident_dict(category)
                self.svc._process(data)
                text = self.caption()
                for needle in ("SCRIPTED DEMO", "EXPERIMENTAL", "Confidence: not scored", f"Incident: {shown}", "Camera: Demo phone camera - CAM 001", "Place: MI Road, Jaipur",
                               "Time: 2026-10-01", primary):
                    self.assertIn(needle, text)
                self.assertNotIn("Peak confidence", text)
                self.assertNotIn("Threshold", text)
                self.assertLess(len(text), 1024)
                markup = (self.bot.send_message.call_args or self.bot.send_photo.call_args).kwargs["reply_markup"]
                self.assertEqual([b.callback_data.rsplit(":", 1)[-1] for row in markup.keyboard for b in row], ["confirm", "false_alarm", "escalate"])
                self.assertTrue(self.bot.send_location.called)

    def test_caption_stays_under_1024_in_the_worst_case(self):
        iid, data = scripted_incident_dict("fall")
        data["camera_name"], data["place_text"] = "C" * 300, "P" * 400
        long_lookup = {"source": "cache", "services": {"hospital": [{"title": "H" * 200, "category": "hospital", "distance_km": 12.34, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}], "police": [], "fire": []}}
        with patch("api.services.nearby_services.lookup_cached", return_value=long_lookup):
            self.svc._process(data)
        self.assertLessEqual(len(self.caption()), 1000)

    def test_call_text_is_exactly_the_scripted_wording(self):
        iid, data = scripted_incident_dict("fall")
        plan = {"assignments": [{"service_category": "hospital", "status": "available", "service": {"title": "Test Hospital", "distance_km": 1.5}}]}
        self.assertEqual(ns.build_call_message(data, plan),
                         "This is a test call for the Room 118 demo. Scripted demo incident: fall at MI Road, Jaipur. Nearest hospital: Test Hospital, 1.5 kilometres.")
        for category, word, svc in (("assault", "violence", "police station"), ("snatching", "snatching", "police station")):
            _i, d = scripted_incident_dict(category)
            text = ns.build_call_message(d, {"assignments": [{"service_category": "police", "status": "available", "service": {"title": "P", "distance_km": 0.7}}]})
            self.assertEqual(text, f"This is a test call for the Room 118 demo. Scripted demo incident: {word} at MI Road, Jaipur. Nearest {svc}: P, 0.7 kilometres.")
            self.assertIn("scripted demo", text.lower())
            self.assertLess(len(text), 200)

    def test_no_automatic_call_by_default_and_escalate_now_places_it(self):
        for category in ("fall", "assault", "snatching"):
            with self.subTest(category=category):
                self.posts.clear()
                iid, data = scripted_incident_dict(category)
                self.svc._process(data)
                time.sleep(0.8)                                             # well past DEMO_ESCALATION_DELAY_S
                self.assertEqual(self.posts, [])
                self.assertIn(("call", "manual_only"), self.timeline(iid))
                self.assertNotIn(("call", "scheduled"), self.timeline(iid))
                self.press(iid, "escalate")
                end = time.time() + 3
                while not self.posts and time.time() < end:
                    time.sleep(0.05)
                self.assertEqual(len(self.posts), 1)
                self.assertIn("scripted demo incident", self.posts[0]["call_context"]["alert_message"].lower())
                self.assertEqual(self.posts[0]["to_number"], "+919000000011")

    def test_scripted_auto_call_defaults_to_off(self):
        self.assertFalse(type(settings).model_fields["SCRIPTED_AUTO_CALL"].default)


class ScriptedAutoCallTests(NotificationBase):
    def setUp(self):
        super().setUp()
        settings.SCRIPTED_AUTO_CALL = True

    def _run(self, category="fall", camera_id=None):
        iid, data = scripted_incident_dict(category, camera_id)
        self.svc._process(data)
        return iid

    def test_call_fires_once_after_the_delay_with_the_scripted_text(self):
        iid = self._run()
        self.assertEqual(self.posts, [])                                   # not before the delay
        self.assertIn(("call", "scheduled"), self.timeline(iid))
        end = time.time() + 3
        while not self.posts and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(len(self.posts), 1)
        self.assertIn("Scripted demo incident: fall at MI Road, Jaipur.", self.posts[0]["call_context"]["alert_message"])
        self.assertIn(("call", "sent"), self.timeline(iid))

    def test_acknowledge_cancels_it(self):
        iid = self._run()
        self.press(iid, "confirm")
        time.sleep(0.8)
        self.assertEqual(self.posts, [])
        self.assertIn(("call", "cancelled"), self.timeline(iid))

    def test_false_alarm_cancels_it(self):
        iid = self._run("snatching")
        self.press(iid, "false_alarm")
        time.sleep(0.8)
        self.assertEqual(self.posts, [])

    def test_alerts_disabled_suppresses_everything(self):
        settings.ALERTS_ENABLED = False
        iid = self._run()
        time.sleep(0.7)
        self.assertEqual(self.posts, [])
        self.assertFalse(self.bot.send_message.called or self.bot.send_photo.called)
        self.assertIn(("call", "skipped"), self.timeline(iid))

    def test_dry_run_suppresses_the_call_but_telegram_is_real(self):
        settings.DEMO_DRY_RUN = True
        iid = self._run()
        time.sleep(0.8)
        self.assertEqual(self.posts, [])
        self.assertIn(("call", "suppressed"), self.timeline(iid))
        self.assertTrue(self.bot.send_message.called or self.bot.send_photo.called)

    def test_hard_blocked_numbers_are_never_dialed(self):
        for number in ("100", "101", "102", "108", "112", "+91112"):
            self.posts.clear()
            settings.DEMO_PHONE_NUMBER = number
            self._run()
            time.sleep(0.7)
            self.assertEqual(self.posts, [], number)

    def test_call_cap_is_respected(self):
        settings.MAX_CALLS_PER_HOUR = 0
        iid = self._run()
        time.sleep(0.7)
        self.assertEqual(self.posts, [])
        self.assertIn(("call", "skipped"), self.timeline(iid))

    def test_cooldown_suppresses_the_second_scripted_incident(self):
        settings.ACTION_COOLDOWN_S = 60.0
        first = self._run(camera_id="CAM-COOL")
        second_id, second = scripted_incident_dict("fall", "CAM-COOL")
        self.svc._process(second)
        self.assertIn(("telegram", "suppressed"), self.timeline(second_id))
        self.assertIn(("call", "suppressed"), self.timeline(second_id))

    def test_ignored_when_demo_mode_is_false(self):
        settings.DEMO_MODE = False
        iid = self._run()
        time.sleep(0.7)
        self.assertEqual(self.posts, [])
        self.assertNotIn(("call", "scheduled"), self.timeline(iid))
        self.assertIn(("call", "manual_only"), self.timeline(iid))

    def test_a_timer_scheduled_in_demo_mode_does_not_dial_after_demo_mode_is_turned_off(self):
        iid, data = scripted_incident_dict("fall")
        self.svc._process(data)
        settings.DEMO_MODE = False
        time.sleep(0.8)
        self.assertEqual(self.posts, [])

    def test_only_scripted_incidents_use_the_toggle(self):
        iid, data = scripted_incident_dict("fall", scripted=False, detector_source="pose-fall-rules", peak_confidence=0.9, threshold_applied=0.6)
        self.svc._process(data)
        time.sleep(0.8)
        self.assertEqual(self.posts, [])                                   # a detected (experimental) fall still never auto-calls

    def test_fire_still_auto_calls_and_is_not_labelled_scripted(self):
        iid = str(uuid.uuid4())
        data = {"incident_id": iid, "camera_id": "CAM-F", "camera_name": "C", "place_text": "P", "latitude": 26.9, "longitude": 75.8, "category": "fire", "status": "new",
                "source": "test_replay", "event_start": "2026-10-01T00:00:00+00:00", "detected_at": "2026-10-01T00:00:00+00:00",
                "detection": {"peak_confidence": 0.4, "threshold_applied": 0.5}, "evidence": {}, "notifications": []}
        db.insert_incident(iid, "CAM-F", "fire", "new", "test_replay", data["event_start"], data)
        self.svc._process(data)
        end = time.time() + 3
        while not self.posts and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(len(self.posts), 1)
        self.assertNotIn("cripted", self.posts[0]["call_context"]["alert_message"])
        self.assertNotIn("SCRIPTED", self.caption())


class ToggleEndpointTests(unittest.TestCase):
    def test_toggle_requires_the_token_is_audited_and_visible_in_the_state(self):
        settings.DEMO_TOKEN = "t"
        saved = (settings.SCRIPTED_AUTO_CALL, settings.DEMO_MODE)
        from fastapi.testclient import TestClient
        from api.main import app
        try:
            with TestClient(app) as client:
                h = {"X-Demo-Token": "t"}
                self.assertEqual(client.post("/api/v1/demo/scripted-auto-call", json={"enabled": True}).status_code, 403)
                settings.DEMO_MODE = True
                r = client.post("/api/v1/demo/scripted-auto-call", json={"enabled": True}, headers=h)
                self.assertEqual(r.json(), {"scripted_auto_call": True, "effective": True})
                st = client.get("/api/v1/demo-state").json()
                self.assertEqual((st["scripted_auto_call"], st["scripted_auto_call_effective"]), (True, True))
                settings.DEMO_MODE = False
                st = client.get("/api/v1/demo-state").json()
                self.assertEqual((st["scripted_auto_call"], st["scripted_auto_call_effective"]), (True, False))   # shown as ON but ignored
                client.post("/api/v1/demo/scripted-auto-call", json={"enabled": False}, headers=h)
                self.assertFalse(settings.SCRIPTED_AUTO_CALL)
                self.assertTrue(any(e["action"] == "scripted_auto_call" for e in audit.entries()))
        finally:
            settings.DEMO_TOKEN = ""
            settings.SCRIPTED_AUTO_CALL, settings.DEMO_MODE = saved


if __name__ == "__main__":
    unittest.main()
