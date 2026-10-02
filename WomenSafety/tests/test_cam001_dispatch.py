"""CAM-001 dispatch plans for all five categories, with the nearby-services lookup mocked (no SerpApi, no Mapbox):
crash -> hospital then police, never a fire station; fire -> fire station then hospital, never police; fall -> hospital;
violence and snatching -> police only. The crash goes through the real demo-trigger path on CAM-001."""
import os
import sys
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-cam001-tests-")
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
from unittest.mock import patch

import numpy as np

from api import db
from api.models.camera import get_camera
from api.services import demo_trigger
from api.services import incident_service_v2 as incidents
from api.services import notification_service as ns


def _svc(title, km, category):
    return {"title": title, "category": category, "distance_km": km, "phone": "+910000000000", "type": category,
            "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}


LOOKUP = {"source": "cache", "services": {
    "hospital": [_svc("Mock Hospital A", 0.9, "hospital"), _svc("Mock Hospital B", 1.4, "hospital")],
    "police": [_svc("Mock Police Station A", 0.8, "police")],
    "fire": [_svc("Mock Fire Station A", 1.5, "fire")]}}

EXPECTED = {
    "road_accident": [("hospital", "Mock Hospital A"), ("police", "Mock Police Station A")],
    "fire": [("fire_station", "Mock Fire Station A"), ("hospital", "Mock Hospital A")],
    "fall": [("hospital", "Mock Hospital A")],
    "assault": [("police", "Mock Police Station A")],
    "snatching": [("police", "Mock Police Station A")],
}


def _plan_types(incident):
    return [(a["service_category"], (a.get("service") or {}).get("title")) for a in incident["dispatch_plan"]["assignments"]]


@unittest.skipIf(get_camera("CAM-001") is None or get_camera("CAM-001").latitude is None, "CAM-001 location not configured in this environment")
class Cam001DispatchTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.patch = patch.object(ns, "get_nearby_services", return_value=LOOKUP)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _wait_plan(self, incident_id):
        end = time.time() + 20
        while time.time() < end:
            inc = incidents.get_incident(incident_id)
            if inc and inc.get("dispatch_plan"):
                return inc
            time.sleep(0.1)
        self.fail("no dispatch plan computed")

    def test_crash_trigger_on_cam001_plans_hospital_then_police_and_no_fire_station(self):
        frame = np.full((480, 640, 3), 120, np.uint8)
        pick = {"frame": frame, "confidence": 0.9, "boxes": [{"class": "Accident", "confidence": 0.9, "box": [10, 10, 200, 200]}], "t_s": 3.0,
                "real_detection": False, "detector": None}
        with patch.object(demo_trigger, "_pick_frame", return_value=pick):
            created = demo_trigger.trigger_demo_incident("CAM-001", "crash")
        inc = self._wait_plan(created["incident_id"])
        self.assertEqual(inc["camera_id"], "CAM-001")
        self.assertEqual(inc["category"], "road_accident")
        self.assertEqual(_plan_types(inc), EXPECTED["road_accident"])
        self.assertEqual([a["role"] for a in inc["dispatch_plan"]["assignments"]], ["primary", "secondary"])
        self.assertNotIn("fire_station", [t for t, _ in _plan_types(inc)])

    def test_every_category_on_cam001_follows_dispatch_rules(self):
        cam = get_camera("CAM-001")
        svc = ns.NotificationService()
        for category, expected in EXPECTED.items():
            iid = str(uuid.uuid4())
            data = {"incident_id": iid, "camera_id": "CAM-001", "camera_name": cam.display_name, "place_text": cam.place_text,
                    "latitude": cam.latitude, "longitude": cam.longitude, "category": category, "status": "new", "source": "test_replay",
                    "event_start": "2026-10-01T00:00:00+00:00", "detected_at": "2026-10-01T00:00:00+00:00",
                    "detection": {"peak_confidence": 0.8, "threshold_applied": 0.5, "experimental": category in ("fall", "assault", "snatching")},
                    "evidence": {}, "notifications": []}
            db.insert_incident(iid, "CAM-001", category, "new", "test_replay", data["event_start"], data)
            svc._process(data)                                         # ALERTS_ENABLED=false: plan is built, nothing is sent
            self.assertEqual(_plan_types(incidents.get_incident(iid)), expected, category)
        svc.stop()


if __name__ == "__main__":
    unittest.main()
