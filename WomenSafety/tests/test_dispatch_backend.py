"""Offline tests for the dispatch backend's safety and control flow."""
import json
import os
import tempfile
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

    def test_notification_cooldown_is_per_camera_and_category(self):
        service = NotificationService()
        service._record = lambda *args, **kwargs: None
        service._process = lambda incident: None
        incident = SimpleNamespace(incident_id="one", camera_id="CAM-1", category=SimpleNamespace(value="fire"), to_dict=lambda: {"incident_id": "one"})
        self.assertTrue(service.enqueue(incident))
        self.assertFalse(service.enqueue(incident))
        service.stop()

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
