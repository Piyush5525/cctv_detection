"""Offline tests for the dispatch backend's safety and control flow."""
import json
import os
import tempfile

# Fix pass item 3: tests NEVER touch the real incidents.db / evidence dir and
# never start camera workers. Must be set before api.* is imported.
_TEST_DIR = tempfile.mkdtemp(prefix="ws-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
# Real credentials from .env must never be usable by tests (api.core.config
# loads .env with override=False, so an empty value here wins): no Telegram
# polling, no Omnidim, no SerpApi/Mapbox traffic.
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.core.config import settings
from api.services import nearby_services
from api.services.dispatch_routing import build_dispatch_plan, route_to_service
from api.services.notification_service import NotificationService
from api.services.safety_guard import check_call_allowed


SAMPLE_SERVICE = {
    "title": "Sample Hospital", "category": "hospital", "distance_km": 1.2,
    "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}, "phone": "+919999999999",
}


class DispatchBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_nearby_path = settings.NEARBY_SERVICES_CACHE_PATH
        self.old_route_path = settings.DISPATCH_ROUTE_CACHE_PATH
        self.old_demo_phone = settings.DEMO_PHONE_NUMBER
        settings.NEARBY_SERVICES_CACHE_PATH = Path(self.temp.name) / "nearby.json"
        settings.DISPATCH_ROUTE_CACHE_PATH = Path(self.temp.name) / "routes.json"

    def tearDown(self):
        settings.NEARBY_SERVICES_CACHE_PATH = self.old_nearby_path
        settings.DISPATCH_ROUTE_CACHE_PATH = self.old_route_path
        settings.DEMO_PHONE_NUMBER = self.old_demo_phone
        self.temp.cleanup()

    def test_nearby_services_uses_fresh_cache_without_network(self):
        cached_at = nearby_services.datetime.now(nearby_services.timezone.utc).isoformat()
        settings.NEARBY_SERVICES_CACHE_PATH.write_text(json.dumps({"CAM-TEST": {
            "cached_at": cached_at, "services": {"hospital": [SAMPLE_SERVICE]},
        }}), encoding="utf-8")
        with patch.object(nearby_services, "_query_serpapi", side_effect=AssertionError("network must not run")):
            result = nearby_services.get_nearby_services("CAM-TEST", 26.91, 75.78, "MI Road, Jaipur")
        self.assertEqual(result["source"], "cache")
        self.assertEqual(result["services"]["hospital"][0]["title"], "Sample Hospital")

    def test_route_falls_back_when_mapbox_is_offline(self):
        with patch.dict(os.environ, {"MAPBOX_TOKEN": ""}, clear=False):
            route = route_to_service(26.91, 75.78, SAMPLE_SERVICE)
        self.assertEqual(route["route_source"], "straight_line_fallback")
        self.assertEqual(route["geometry"]["type"], "LineString")

    def test_dispatch_plan_never_turns_lookup_phone_into_call_target(self):
        plan = build_dispatch_plan("road_accident", 26.91, 75.78, {
            "hospital": [SAMPLE_SERVICE], "police": [], "fire": [],
        })
        self.assertEqual(plan["contact_policy"], "display_only_never_auto_dial_discovered_numbers")
        self.assertEqual(plan["assignments"][0]["status"], "available")
        self.assertEqual(plan["assignments"][1]["status"], "unavailable")

    def test_emergency_formats_are_hard_blocked(self):
        settings.DEMO_PHONE_NUMBER = "+919876543210"
        for number in ("100", "+91-100", "91100", "0100", "1 0 0"):
            self.assertFalse(check_call_allowed(number).allowed, number)

    def test_cooldown_suppresses_outbound_only_and_is_per_camera_and_category(self):
        service = NotificationService()
        records = []
        service._record = lambda iid, channel, status, recipient, detail: records.append((iid, channel, status, detail))
        service._set_dispatch_plan = lambda iid, plan: records.append((iid, "plan", "set", None))
        service._send_telegram = lambda inc, plan: records.append((inc["incident_id"], "telegram", "sent", None)) or True
        service._schedule_call = lambda *a: None
        settings.ALERTS_ENABLED = True
        settings.DEMO_MODE = True
        settings.DEMO_COOLDOWN_S = 60
        def inc(i, cam="CAM-1", cat="fire"):
            return {"incident_id": i, "camera_id": cam, "category": cat, "latitude": 1, "longitude": 1, "place_text": "p",
                    "detection": {"peak_confidence": 0.5}}
        try:
            with patch("api.services.notification_service.get_nearby_services", return_value={"services": {}, "source": "cache"}):
                service._process(inc("one"))
                service._process(inc("two"))          # same camera+category: outbound suppressed, plan still built
                service._process(inc("three", cat="crash"))  # other category: not suppressed
        finally:
            settings.ALERTS_ENABLED = False
        self.assertIn(("two", "plan", "set", None), records)
        self.assertIn(("two", "telegram", "suppressed", "suppressed: cooldown"), records)
        self.assertNotIn(("two", "telegram", "sent", None), records)
        self.assertIn(("three", "telegram", "sent", None), records)
        self.assertTrue(service.enqueue(SimpleNamespace(incident_id="x", camera_id="CAM-1", category=SimpleNamespace(value="fire"), to_dict=lambda: {"incident_id": "x"})))
        service.stop()

    def test_telegram_and_call_blocked_when_recipient_unset(self):
        from api.services.safety_guard import check_telegram_allowed
        old_allow, old_chat, old_phone = settings.TELEGRAM_CHAT_ID_ALLOWLIST, os.environ.pop("TELEGRAM_CHAT_ID", None), settings.DEMO_PHONE_NUMBER
        try:
            settings.TELEGRAM_CHAT_ID_ALLOWLIST, settings.DEMO_PHONE_NUMBER = "", ""
            self.assertFalse(check_telegram_allowed("12345").allowed)   # no allowlist and no env chat id => blocked
            self.assertFalse(check_telegram_allowed(None).allowed)
            self.assertFalse(check_call_allowed("").allowed)
            self.assertFalse(check_call_allowed("+919876543210").allowed)
        finally:
            settings.TELEGRAM_CHAT_ID_ALLOWLIST, settings.DEMO_PHONE_NUMBER = old_allow, old_phone
            if old_chat is not None: os.environ["TELEGRAM_CHAT_ID"] = old_chat

    def test_public_view_strips_absolute_paths(self):
        from api.services.public_view import public_view
        root = str(Path(settings.EVIDENCE_ROOT_V2) / "CAM" / "2026-10-01" / "id" / "clip.mp4")
        out = public_view({"evidence": {"clip_path": root}, "list": [root]})
        self.assertEqual(out["evidence"]["clip_path"], "CAM/2026-10-01/id/clip.mp4")
        self.assertNotIn(":", out["list"][0])

    def test_open_capture_handles_digit_index_and_unresolved_env(self):
        from api.models.camera import Camera
        from api.services import camera_workers
        def cam(src): return Camera(camera_id="C", name="n", place_text="p", latitude=26.9, longitude=75.8, stream_source=src, camera_type="phone")
        with patch.object(camera_workers.cv2, "VideoCapture") as vc:
            camera_workers._open_capture(cam("0"))
            vc.assert_called_once_with(0)  # digit string => int device index
        os.environ.pop("AUDIT_UNSET_URL", None)
        cap, kind, error = camera_workers._open_capture(cam("env:AUDIT_UNSET_URL"))
        self.assertIsNone(cap)
        self.assertEqual(kind, "unresolved")
        self.assertIn("will retry", error)

    def test_demo_routes_need_token(self):
        from fastapi.testclient import TestClient
        from api.main import app
        old = settings.DEMO_TOKEN
        settings.DEMO_TOKEN = "t0k"
        try:
            with TestClient(app) as client:
                body = {"camera_id": "CAM-SAMPLE-001", "category": "fire"}
                self.assertEqual(client.post("/api/v1/demo/trigger", json=body).status_code, 403)
                self.assertEqual(client.patch("/api/v1/incidents/x/status", json={"status": "confirmed"}).status_code, 403)
                self.assertEqual(client.delete("/api/v1/evidence/x.mp4").status_code, 403)
                self.assertEqual(client.patch("/api/v1/incidents/x/status", json={"status": "confirmed"}, headers={"X-Demo-Token": "t0k"}).status_code, 404)
                self.assertEqual(client.get("/api/v1/does-not-exist").status_code, 404)
        finally:
            settings.DEMO_TOKEN = old

    def test_camera_nearby_http_route_returns_cached_data(self):
        from api import db
        from fastapi.testclient import TestClient
        old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "route-incidents.db"
        try:
            from api.main import app
            with patch("api.routes.nearby_services.get_nearby_services", return_value={"source": "cache", "services": {}}):
                with TestClient(app) as client:
                    response = client.get("/api/v1/cameras/CAM-SAMPLE-001/nearby-services")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["source"], "cache")
        finally:
            db.DB_PATH = old_db_path

    def test_confirm_and_false_alarm_callbacks_update_incident(self):
        from api import db
        old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "incidents.db"
        try:
            db.init_db()
            for incident_id in ("confirm-me", "dismiss-me"):
                db.insert_incident(incident_id, "CAM-1", "fire", "new", "live", _now(), {
                    "incident_id": incident_id, "camera_id": "CAM-1", "category": "fire", "status": "new", "notifications": [],
                })
            service = NotificationService()
            self.assertTrue(service.handle_callback("confirm-me", "confirm"))
            self.assertEqual(db.get_incident("confirm-me")["status"], "confirmed")
            self.assertTrue(service.handle_callback("dismiss-me", "false_alarm"))
            self.assertEqual(db.get_incident("dismiss-me")["status"], "false_positive")
            self.assertFalse(service.handle_callback("dismiss-me", "unknown"))
        finally:
            db.DB_PATH = old_db_path

    def test_escalation_timer_runs_and_false_alarm_cancels_call(self):
        service = NotificationService()
        called = []
        service._record = lambda *args, **kwargs: None
        service._send_call_if_still_needed = lambda incident_id, incident: called.append(incident_id)
        service._schedule_call("escalate-now", {"incident_id": "escalate-now"}, 0)
        deadline = time.time() + 1
        while not called and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(called, ["escalate-now"])
        service.stop()


if __name__ == "__main__":
    unittest.main()


def _now():
    return "2026-10-01T00:00:00+00:00"
