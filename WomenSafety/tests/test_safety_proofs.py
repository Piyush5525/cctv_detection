"""Safety proofs (mocked: nothing real is ever sent):
  * ALERTS_ENABLED=false  -> no Telegram message and no call, for all five categories, including a stale "Escalate now" press;
  * experimental categories never auto-call (even at confidence 1.0 with no delay);
  * hard-blocked emergency numbers (100, 101, 102, 108, 112, in any plausible formatting) and non-allowlisted numbers are blocked
    on the new path AND the legacy Call_Alert path;
  * the Telegram caption stays under 1024 characters in the worst case."""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-safety-tests-")
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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import db
from api.core.config import settings
from api.services import incident_service_v2 as incidents
from api.services import notification_service as ns
from api.services.safety_guard import HARD_BLOCKED_NUMBERS, check_call_allowed

ALL_CATEGORIES = ("fire", "road_accident", "fall", "assault", "snatching")
EXPERIMENTAL = ("fall", "assault", "snatching")
PLAN = {"source": "cache", "services": {
    "hospital": [{"title": "H", "category": "hospital", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
    "police": [{"title": "P", "category": "police", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
    "fire": [{"title": "F", "category": "fire", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}]}}


def make_incident(category, confidence=1.0, **over):
    iid = str(uuid.uuid4())
    data = {"incident_id": iid, "camera_id": f"CAM-{iid[:4]}", "camera_name": "Cam", "place_text": "Place", "latitude": 26.9, "longitude": 75.8,
            "category": category, "status": "new", "source": "test_replay", "event_start": "2026-10-01T00:00:00+00:00",
            "detected_at": "2026-10-01T00:00:00+00:00",
            "detection": {"peak_confidence": confidence, "threshold_applied": 0.5, "experimental": category in EXPERIMENTAL, "signals": {}},
            "evidence": {}, "notifications": [], **over}
    db.insert_incident(iid, data["camera_id"], category, "new", "test_replay", data["event_start"], data)
    return iid, data


def timeline(iid):
    return [(n["channel"], n["status"]) for n in incidents.get_incident(iid)["notifications"]]


class SafetyBase(unittest.TestCase):
    def setUp(self):
        db.init_db()
        keys = ("ALERTS_ENABLED", "DEMO_MODE", "DEMO_ESCALATION_DELAY_S", "DEMO_PHONE_NUMBER", "DEMO_COOLDOWN_S", "CALL_MIN_CONFIDENCE", "DEMO_DRY_RUN",
                "TELEGRAM_CHAT_ID_ALLOWLIST", "MAX_CALLS_PER_HOUR")
        self.saved = {k: getattr(settings, k) for k in keys}
        settings.ALERTS_ENABLED, settings.DEMO_MODE, settings.DEMO_DRY_RUN = False, True, False
        settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE = 0.1, 0, 0.0
        settings.DEMO_PHONE_NUMBER, settings.TELEGRAM_CHAT_ID_ALLOWLIST, settings.MAX_CALLS_PER_HOUR = "+919000000011", "", 5
        os.environ.update(TELEGRAM_CHAT_ID="42", OMNIDIM_API_KEY="FAKE", OMNIDIM_AGENT_ID="7")
        self.posts = []

        def fake_post(url, **kw):
            self.posts.append((url, kw["json"]["to_number"]))
            m = MagicMock()
            m.raise_for_status = lambda: None
            return m
        self.patches = [patch.object(ns.requests, "post", side_effect=fake_post), patch.object(ns, "get_nearby_services", return_value=PLAN)]
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

    def sent_telegram(self):
        return self.bot.send_message.called or self.bot.send_photo.called


class AlertsDisabledTests(SafetyBase):
    def test_nothing_is_sent_for_any_category_when_alerts_are_disabled(self):
        for category in ALL_CATEGORIES:
            iid, data = make_incident(category)
            self.svc._process(data)
            time.sleep(0.3)
            self.assertFalse(self.sent_telegram(), category)
            self.assertEqual(self.posts, [], category)
            self.assertIn(("telegram", "skipped"), timeline(iid))
            self.assertIn(("call", "skipped"), timeline(iid))

    def test_a_stale_escalate_button_cannot_place_a_call_while_alerts_are_disabled(self):
        for category in ALL_CATEGORIES:
            iid, data = make_incident(category)
            self.svc.process_press(iid, "escalate", "Asha", None, edit=False)
            time.sleep(0.5)
            self.assertEqual(self.posts, [], category)
            self.assertIn(("call", "skipped"), timeline(iid))


class ExperimentalNeverAutoCallsTests(SafetyBase):
    def test_even_at_full_confidence_and_zero_delay_no_call_without_escalate_now(self):
        settings.ALERTS_ENABLED = True
        settings.DEMO_ESCALATION_DELAY_S = 0.0
        for category in EXPERIMENTAL:
            iid, data = make_incident(category, confidence=1.0)
            self.svc._process(data)
            time.sleep(0.6)
            self.assertEqual(self.posts, [], category)
            self.assertTrue(self.sent_telegram())
            self.assertIn(("call", "manual_only"), timeline(iid))


class BlockedNumbersTests(SafetyBase):
    BLOCKED = ["100", "101", "102", "108", "112", "+91100", "+91 112", "0112", "91-108", "+91-101", "(102)"]

    def test_hard_blocked_numbers_and_formats_are_rejected_by_the_guard(self):
        for n in self.BLOCKED:
            r = check_call_allowed(n)
            self.assertFalse(r.allowed, n)
        self.assertEqual(HARD_BLOCKED_NUMBERS, frozenset({"100", "101", "102", "108", "112"}))

    def test_hard_blocked_number_as_the_demo_recipient_is_never_dialed_even_with_alerts_on(self):
        settings.ALERTS_ENABLED = True
        for number in ("100", "101", "102", "108", "112", "+91112"):
            self.posts.clear()
            settings.DEMO_PHONE_NUMBER = number
            for category in ("fire", "assault"):
                iid, data = make_incident(category)
                self.svc._process(data)
                self.svc.process_press(iid, "escalate", "Asha", None, edit=False)
            time.sleep(0.6)
            self.assertEqual(self.posts, [], number)

    def test_a_non_allowlisted_number_is_blocked(self):
        # the allowlist is exactly DEMO_PHONE_NUMBER (+919000000011 here): any other number is refused by the guard
        settings.DEMO_PHONE_NUMBER = "+919000000011"
        self.assertTrue(check_call_allowed("+919000000011").allowed)
        for other in ("+919999999999", "9876543210", "+14155550100", "", None):
            self.assertFalse(check_call_allowed(other).allowed, other)

    def test_legacy_call_alert_path_is_guarded_too(self):
        import Call_Alert
        settings.ALERTS_ENABLED = True
        with patch.object(Call_Alert.requests, "post") as post, \
                patch.object(Call_Alert, "OMNIDIM_API_KEY", "FAKE"), patch.object(Call_Alert, "OMNIDIM_AGENT_ID", "7"):
            for number in ("112", "100", "+919999999999"):
                with patch.object(Call_Alert, "ALERT_PHONE_NUMBER", number), patch.dict(Call_Alert._last_call_time, {}, clear=True):
                    Call_Alert.send_call_alert("test", reason="proof")
            post.assert_not_called()


class CaptionLengthTests(SafetyBase):
    def test_worst_case_caption_stays_under_1024(self):
        settings.ALERTS_ENABLED = True
        long = "X" * 80
        services = {"hospital": [{"title": long, "category": "hospital", "distance_km": 12.34, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
                    "police": [{"title": long, "category": "police", "distance_km": 12.34, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
                    "fire": [{"title": long, "category": "fire", "distance_km": 12.34, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}]}
        for category in ALL_CATEGORIES:
            self.bot.reset_mock()
            iid, data = make_incident(category, camera_name="C" * 200, place_text="P" * 300)
            data["camera_name"], data["place_text"] = "C" * 200, "P" * 300
            with patch.object(ns, "get_nearby_services", return_value={"source": "cache", "services": services}):
                self.svc._process(data)
            call = self.bot.send_message.call_args or self.bot.send_photo.call_args
            caption = call.kwargs.get("caption") or call[0][1]
            self.assertLessEqual(len(caption), 1000, category)
            self.assertLess(len(caption), 1024)
            if category in EXPERIMENTAL:
                self.assertIn("EXPERIMENTAL", caption)

    def test_compose_caption_with_many_status_lines_is_bounded(self):
        head = "EXPERIMENTAL detection - verify before acting\nIncident: Violence\n" + "Place: " + "P" * 400
        text = ns.compose_caption(head, ["hospital: " + "H" * 100 + " (1 km)"] * 3, ["status line " + "s" * 120] * 6, footer="Experimental detector: no automatic call.")
        self.assertLess(len(text), 1024)


if __name__ == "__main__":
    unittest.main()
