"""Names, SerpApi result filtering, call text, caption length (all offline)."""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-fix-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import unittest
from pathlib import Path
from unittest.mock import patch

from api.core.config import settings
from api.models.camera import Camera
from api.services import nearby_services as ns_mod
from api.services.notification_service import CAPTION_LIMIT, build_call_message, compose_caption


def _cam(name, camera_type="phone"):
    return Camera(camera_id="C", name=name, place_text="p", latitude=26.9, longitude=75.8, stream_source="0", camera_type=camera_type)


def _raw(title, type_, lat=26.91, lng=75.79, phone=None, types=None):
    return {"title": title, "type": type_, "types": types or [type_], "gps_coordinates": {"latitude": lat, "longitude": lng},
            "phone": phone, "address": "addr", "place_id": title}


class CameraNameTests(unittest.TestCase):
    def test_phone_prefix_not_doubled(self):
        self.assertEqual(_cam("Demo phone camera - Entrance").display_name, "Demo phone camera - Entrance")
        self.assertEqual(_cam("demo PHONE camera Entrance").display_name, "demo PHONE camera Entrance")
        self.assertEqual(_cam("Entrance").display_name, "Demo phone camera - Entrance")
        self.assertEqual(_cam("MI Road", "cctv").display_name, "MI Road")


class NearbyFilterTests(unittest.TestCase):
    def setUp(self):
        self.old = settings.NEARBY_SERVICES_CACHE_PATH
        settings.NEARBY_SERVICES_CACHE_PATH = Path(tempfile.mkdtemp()) / "nearby.json"
        os.environ["SERPAPI_KEY"] = "FAKE"

    def tearDown(self):
        settings.NEARBY_SERVICES_CACHE_PATH = self.old
        os.environ["SERPAPI_KEY"] = ""

    def _lookup(self, per_query):
        def fake_query(query, lat, lng):
            for word, results in per_query.items():
                if query.startswith(word):
                    return results
            return []
        with patch.object(ns_mod, "_query_serpapi", side_effect=fake_query):
            return ns_mod.get_nearby_services("CAM-X", 26.9, 75.79, "MI Road, Jaipur", force_refresh=True)

    def test_filters_and_records_reasons(self):
        out = self._lookup({
            "hospital": [_raw("SR Kalla Hospital", "Hospital", lat=26.9132), _raw("Apollo Pharmacy", "Pharmacy"),
                         _raw("City Clinic", "Clinic", lat=26.92), _raw("", "Hospital"), _raw("Hospital", "Hospital")],
            "police": [_raw("Police Station", "Police station"), _raw("G R P Police Station Jaipur", "Police station"),
                       _raw("Government Railway Police", "Police station", lat=26.905), _raw("Civil Lines Police Station", "Police station", lat=26.9091),
                       _raw("Cafe Police", "Cafe")],
            "fire": [_raw("SHRI SHYAM FIRE ENTERPRISES", "Fire protection equipment supplier"), _raw("Fire Safety Dealer", "Fire station"),
                     _raw("Rajasthan Agnishaman Seva", "Fire station", lat=26.9181)],
        })
        titles = {c: [s["title"] for s in v] for c, v in out["services"].items()}
        self.assertEqual(sorted(titles["hospital"]), ["City Clinic", "SR Kalla Hospital"])
        self.assertEqual(titles["police"], ["Civil Lines Police Station"])
        self.assertEqual(titles["fire"], ["Rajasthan Agnishaman Seva"])
        reasons = {(e["category"], e["title"]): e["reason"] for e in out["excluded"]}
        self.assertIn("no usable name", reasons[("hospital", None)])
        self.assertIn("generic name", reasons[("hospital", "Hospital")])
        self.assertIn("generic name", reasons[("police", "Police Station")])
        self.assertIn("railway police", reasons[("police", "G R P Police Station Jaipur")])
        self.assertIn("railway police", reasons[("police", "Government Railway Police")])
        self.assertIn("not a hospital", reasons[("hospital", "Apollo Pharmacy")])
        self.assertIn("equipment/supplier", reasons[("fire", "SHRI SHYAM FIRE ENTERPRISES")])
        self.assertIn("equipment/supplier", reasons[("fire", "Fire Safety Dealer")])
        self.assertIn("not police", reasons[("police", "Cafe Police")])
        cached = ns_mod._load_cache()[ns_mod.cell_key(26.9, 75.79)]
        self.assertEqual(len(cached["excluded"]), len(out["excluded"]))  # reasons persisted

    def test_phone_number_ranks_higher_within_300m(self):
        near_no_phone = {"title": "A", "distance_km": 0.50, "phone": None}
        slightly_farther_phone = {"title": "B", "distance_km": 0.75, "phone": "+911"}
        far_phone = {"title": "C", "distance_km": 0.95, "phone": "+912"}
        ranked = ns_mod.rank_services([near_no_phone, far_phone, slightly_farther_phone])
        self.assertEqual([s["title"] for s in ranked], ["B", "A", "C"])  # B within 300 m of A and has a phone; C is 450 m away


class CallTextTests(unittest.TestCase):
    PLAN = {"assignments": [{"service_category": "fire_station", "role": "primary", "status": "available", "service": {"title": "Fire Stn", "distance_km": 1.6}},
                            {"service_category": "hospital", "role": "secondary", "status": "available", "service": {"title": "SR Kalla Hospital", "distance_km": 0.98}}]}
    CRASH_PLAN = {"assignments": [{"service_category": "hospital", "role": "primary", "status": "available", "service": {"title": "SR Kalla Hospital", "distance_km": 0.98}},
                                  {"service_category": "police", "role": "secondary", "status": "unavailable"}]}
    INCIDENT = {"category": "fire", "camera_name": "Demo phone camera - CAM 001", "place_text": "MI Road, Jaipur"}

    def test_fire_names_the_fire_station_with_prefix_in_demo_mode(self):
        settings.DEMO_MODE = True
        self.assertEqual(build_call_message(self.INCIDENT, self.PLAN),
                         "This is a test call for the Room 118 demo. Fire detected at MI Road, Jaipur. Nearest fire station: Fire Stn, 1.6 kilometres.")

    def test_crash_names_the_hospital_never_a_fire_station(self):
        settings.DEMO_MODE = True
        text = build_call_message({**self.INCIDENT, "category": "road_accident"}, self.CRASH_PLAN)
        self.assertEqual(text, "This is a test call for the Room 118 demo. Crash detected at MI Road, Jaipur. Nearest hospital: SR Kalla Hospital, 0.98 kilometres.")
        self.assertNotIn("fire", text.lower())

    def test_primary_unavailable_and_no_prefix_outside_demo(self):
        settings.DEMO_MODE = False
        try:
            # Snatching is an experimental detector: the call text now says so, with confidence and threshold.
            text = build_call_message({**self.INCIDENT, "category": "snatching", "detection": {"peak_confidence": 0.81, "threshold_applied": 0.7}}, {"assignments": []})
            self.assertEqual(text, "EXPERIMENTAL detection, confidence 0.81, threshold 0.70. Snatching detected at MI Road, Jaipur. Nearest police station: unavailable.")
        finally:
            settings.DEMO_MODE = True


class CaptionTests(unittest.TestCase):
    HEAD = "Incident: fire\nCamera: Demo phone camera - Entrance\nPlace: MI Road, Jaipur\nTime: 2026-10-01T00:00:00+00:00\nPeak confidence: 0.70\nThreshold: 0.50"

    def test_normal_caption_lists_all_services(self):
        text = compose_caption(self.HEAD, ["fire: A (1.0 km)", "hospital: B (0.5 km)"], [])
        self.assertIn("Nearest services: fire: A (1.0 km); hospital: B (0.5 km)", text)
        self.assertLess(len(text), 1024)

    def test_long_services_list_is_truncated_gracefully_and_status_lines_survive(self):
        services = [f"hospital: {'Very Long Hospital Name ' * 6}{i} (1.{i} km)" for i in range(30)]
        lines = ["Acknowledged by Asha at 18:14:46 UTC+05:30 - automatic call cancelled", "No response - auto-call placed at 18:15:46 UTC+05:30"]
        text = compose_caption(self.HEAD, services, lines, footer="Tap Acknowledge to stop the automatic call; False alarm to dismiss it.")
        self.assertLess(len(text), 1024)
        self.assertLessEqual(len(text), CAPTION_LIMIT)
        self.assertIn("more)", text)
        for line in lines:
            self.assertIn(line, text)
        self.assertIn(self.HEAD, text)

    def test_absurdly_long_head_still_under_limit(self):
        text = compose_caption("x" * 3000, ["a"], ["status line"])
        self.assertLess(len(text), 1024)
        self.assertIn("status line", text)


if __name__ == "__main__":
    unittest.main()
