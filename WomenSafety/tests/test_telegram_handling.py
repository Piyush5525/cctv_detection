"""Telegram message handling: button presses edit the SAME message (caption kept,
status line appended, dead buttons removed), escalation timer line, expired alerts.
All network calls are mocked (fake bot, patched requests.post, patched SerpApi)."""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-tg-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
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

PLAN_LOOKUP = {"source": "cache", "services": {
    "hospital": [{"title": "Test Hospital", "category": "hospital", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}],
    "police": [], "fire": []}}


def _make_incident(confidence=0.5):
    incident_id = str(uuid.uuid4())
    data = {"incident_id": incident_id, "camera_id": f"CAM-{incident_id[:4]}", "camera_name": "Test Cam", "place_text": "Test Place",
            "latitude": 26.9, "longitude": 75.8, "category": "fire", "status": "new", "source": "test_replay",
            "event_start": "2026-10-01T00:00:00+00:00", "detected_at": "2026-10-01T00:00:00+00:00",
            "detection": {"peak_confidence": confidence, "threshold_applied": 0.5}, "evidence": {}, "notifications": []}
    db.insert_incident(incident_id, data["camera_id"], "fire", "new", "test_replay", data["event_start"], data)
    return incident_id, data


def _press(incident_id, action, name="Asha", message_id=7):
    message = SimpleNamespace(message_id=message_id, chat=SimpleNamespace(id=42), caption=None, text="x", photo=None)
    return SimpleNamespace(id="cb-1", data=f"incident:{incident_id}:{action}", message=message,
                           from_user=SimpleNamespace(first_name=name, last_name=None, username=None, id=999))


def _buttons(markup):
    return [button.callback_data.rsplit(":", 1)[-1] for row in markup.keyboard for button in row]


def _timeline(incident_id):
    return [(n["channel"], n["status"]) for n in incidents.get_incident(incident_id)["notifications"]]


class TelegramHandlingTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.saved = (settings.ALERTS_ENABLED, settings.DEMO_MODE, settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_PHONE_NUMBER,
                      settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE, settings.TELEGRAM_CHAT_ID_ALLOWLIST)
        settings.ALERTS_ENABLED, settings.DEMO_MODE = True, True
        settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE = 0.4, 0, 0.9
        settings.DEMO_PHONE_NUMBER, settings.TELEGRAM_CHAT_ID_ALLOWLIST = "+919000000011", ""
        os.environ.update(TELEGRAM_CHAT_ID="42", OMNIDIM_API_KEY="FAKE", OMNIDIM_AGENT_ID="7")
        self.posts = []

        def fake_post(url, **kw):
            self.posts.append(kw["json"]["to_number"])
            response = MagicMock()
            response.raise_for_status = lambda: None
            return response

        self.patches = [patch.object(ns.requests, "post", side_effect=fake_post),
                        patch.object(ns, "get_nearby_services", return_value=PLAN_LOOKUP)]
        for p in self.patches:
            p.start()
        self.svc = ns.NotificationService()
        self.bot = MagicMock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=7)
        self.svc._bot = self.bot

    def tearDown(self):
        for p in self.patches:
            p.stop()
        (settings.ALERTS_ENABLED, settings.DEMO_MODE, settings.DEMO_ESCALATION_DELAY_S, settings.DEMO_PHONE_NUMBER,
         settings.DEMO_COOLDOWN_S, settings.CALL_MIN_CONFIDENCE, settings.TELEGRAM_CHAT_ID_ALLOWLIST) = self.saved
        self.svc.stop()

    def _alert(self):
        incident_id, data = _make_incident()
        self.svc._process(data)  # sends the (mock) Telegram alert and schedules the call
        self.assertTrue(self.bot.send_message.called)
        return incident_id

    def _edit(self):
        args, kwargs = self.bot.edit_message_text.call_args
        return args[0], kwargs["reply_markup"]

    def _dashboard(self, incident_id):
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as client:
            return client.get(f"/api/v1/incidents/{incident_id}").json()

    def test_acknowledge_cancels_call_and_shows_in_timeline_and_dashboard(self):
        incident_id = self._alert()
        self.svc._on_callback(_press(incident_id, "confirm"))
        time.sleep(0.8)  # past DEMO_ESCALATION_DELAY_S
        self.assertEqual(self.posts, [])
        self.assertIn(("operator", "acknowledged"), _timeline(incident_id))
        self.assertIn(("call", "cancelled"), _timeline(incident_id))
        self.bot.answer_callback_query.assert_called_with("cb-1", "Acknowledged")
        text, markup = self._edit()
        self.assertIn("Incident: fire", text)
        self.assertIn("hospital: Test Hospital (1.0 km)", text)
        self.assertRegex(text, r"Acknowledged by Asha at \d\d:\d\d:\d\d UTC[+-]\d\d:\d\d - automatic call cancelled")
        self.assertNotIn("999", text)
        self.assertEqual(_buttons(markup), ["false_alarm"])
        dashboard = self._dashboard(incident_id)
        self.assertEqual(dashboard["status"], "confirmed")
        self.assertTrue(any(n["channel"] == "operator" and n["status"] == "acknowledged" for n in dashboard["notifications"]))

    def test_false_alarm_sets_false_positive_cancels_call_and_dashboard_updates(self):
        incident_id = self._alert()
        self.svc._on_callback(_press(incident_id, "false_alarm"))
        time.sleep(0.8)
        self.assertEqual(self.posts, [])
        text, markup = self._edit()
        self.assertIn("Incident: fire", text)
        self.assertRegex(text, r"Marked false alarm by Asha at \d\d:\d\d:\d\d UTC")
        self.assertEqual(_buttons(markup), [])
        dashboard = self._dashboard(incident_id)
        self.assertEqual(dashboard["status"], "false_positive")
        self.assertIn(("call", "cancelled"), _timeline(incident_id))

    def test_escalate_now_places_call_immediately(self):
        incident_id = self._alert()
        started = time.time()
        self.svc._on_callback(_press(incident_id, "escalate"))
        deadline = time.time() + 2
        while not self.posts and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.posts, ["+919000000011"])
        self.assertLess(time.time() - started, 0.35)  # well before the 0.4 s escalation delay
        time.sleep(0.2)
        text, markup = self._edit()
        self.assertIn("Escalate now pressed by Asha at", text)
        self.assertRegex(text, r"Call placed at \d\d:\d\d:\d\d UTC")
        self.assertEqual(_buttons(markup), ["confirm", "false_alarm"])  # Acknowledge + False alarm stay after the call

    def test_no_press_places_call_after_delay_and_message_shows_call_line(self):
        incident_id = self._alert()
        self.assertEqual(self.posts, [])
        time.sleep(1.0)
        self.assertEqual(self.posts, ["+919000000011"])
        text, markup = self._edit()
        self.assertIn("Incident: fire", text)
        self.assertRegex(text, r"No response - auto-call placed at \d\d:\d\d:\d\d UTC[+-]\d\d:\d\d")
        self.assertEqual(_buttons(markup), ["confirm", "false_alarm"])
        self.assertIn(("call", "sent"), _timeline(incident_id))

    def test_auto_call_skipped_line_when_call_cannot_be_placed(self):
        settings.DEMO_PHONE_NUMBER = ""
        incident_id = self._alert()
        time.sleep(1.0)
        self.assertEqual(self.posts, [])
        text, _ = self._edit()
        self.assertIn("auto-call skipped:", text)

    def test_press_on_expired_alert_answers_expired(self):
        stale = _press(str(uuid.uuid4()), "confirm")
        self.svc._on_callback(stale)
        self.bot.answer_callback_query.assert_called_with("cb-1", "This alert has expired")
        text, markup = self._edit()
        self.assertIn("This alert has expired", text)
        self.assertEqual(_buttons(markup), [])


if __name__ == "__main__":
    unittest.main()
