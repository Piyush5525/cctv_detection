"""DISPATCH_RULES: which services each incident category needs (backend plan, API output, caption)."""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-rules-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import unittest
from unittest.mock import patch

from api.core.config import DISPATCH_RULES, required_services
from api.services import notification_service as ns
from api.services.dispatch_routing import build_dispatch_plan, conform_plan
from api.services.public_view import public_view


def _svc(title, km, phone="+91"):
    return {"title": title, "distance_km": km, "phone": phone, "gps_coordinates": {"latitude": 26.92, "longitude": 75.79}}


ALL = {"hospital": [_svc("H1", 1.0), _svc("H2", 1.5), _svc("H3", 2.0), _svc("H4", 3.0)],
       "police": [_svc("P1", 0.5)], "fire": [_svc("F1", 1.2), _svc("F2", 1.9)]}

EXPECTED = {
    "fire": ["fire_station", "hospital"],
    "road_accident": ["hospital", "police"],
    "crash": ["hospital", "police"],
    "assault": ["police"],
    "snatching": ["police"],
    "fall": ["hospital"],
    "other": ["police"],
    "women_safety": ["police"],  # not in the table -> "other"
    "some_new_category": ["police"],
}


class RulesTests(unittest.TestCase):
    def test_every_category_returns_exactly_the_required_types_primary_first(self):
        for category, expected in EXPECTED.items():
            plan = build_dispatch_plan(category, 26.91, 75.79, ALL)
            self.assertEqual([a["service_category"] for a in plan["assignments"]], expected, category)
            self.assertEqual(plan["required_services"], expected, category)
            self.assertEqual([a["role"] for a in plan["assignments"]], ["primary"] + ["secondary"] * (len(expected) - 1))
            self.assertEqual(list(required_services(category)), expected)

    def test_crash_never_contains_fire_station_and_fire_never_police(self):
        for category in ("road_accident", "crash"):
            self.assertNotIn("fire_station", [a["service_category"] for a in build_dispatch_plan(category, 26.9, 75.8, ALL)["assignments"]])
        self.assertNotIn("police", [a["service_category"] for a in build_dispatch_plan("fire", 26.9, 75.8, ALL)["assignments"]])
        for types in DISPATCH_RULES.values():
            self.assertEqual(len(set(types)), len(types))

    def test_missing_type_is_unavailable_never_replaced(self):
        plan = build_dispatch_plan("fire", 26.9, 75.8, {"hospital": [_svc("H1", 1.0)], "police": [_svc("P1", 0.4)], "fire": []})
        fire, hospital = plan["assignments"]
        self.assertEqual((fire["service_category"], fire["status"], fire["reason"]), ("fire_station", "unavailable", "No fire station found nearby"))
        self.assertNotIn("service", fire)
        self.assertEqual(hospital["service"]["title"], "H1")
        self.assertEqual(len(plan["assignments"]), 2)  # police (which exists) is not offered for a fire

    def test_nearest_first_with_up_to_two_alternatives_and_route_for_nearest_only(self):
        plan = build_dispatch_plan("road_accident", 26.9, 75.8, ALL)
        hospital = plan["assignments"][0]
        self.assertEqual(hospital["service"]["title"], "H1")
        self.assertEqual([a["title"] for a in hospital["alternatives"]], ["H2", "H3"])  # H4 dropped (max 2 more)
        self.assertEqual(hospital["route"]["route_source"], "straight_line_fallback")
        self.assertNotIn("route", hospital["alternatives"][0])

    def test_old_stored_plan_is_conformed_on_output(self):
        old = {"assignments": [{"service_category": "hospital", "status": "available", "service": _svc("H1", 1)},
                               {"service_category": "police", "status": "available", "service": _svc("P1", 1)},
                               {"service_category": "fire", "status": "available", "service": _svc("F1", 1)}]}
        crash = conform_plan("road_accident", old)
        self.assertEqual([a["service_category"] for a in crash["assignments"]], ["hospital", "police"])
        fire = conform_plan("fire", old)
        self.assertEqual([(a["service_category"], a["role"]) for a in fire["assignments"]], [("fire_station", "primary"), ("hospital", "secondary")])
        missing = conform_plan("fire", {"assignments": [old["assignments"][0]]})
        self.assertEqual(missing["assignments"][0]["status"], "unavailable")
        shown = public_view({"category": "road_accident", "dispatch_plan": old})
        self.assertEqual([a["service_category"] for a in shown["dispatch_plan"]["assignments"]], ["hospital", "police"])
        self.assertEqual(conform_plan("fire", {"lookup_error": "x", "assignments": []})["assignments"], [])  # error plans pass through

    def test_telegram_caption_lists_only_required_services(self):
        class Bot:
            sent = []

            def send_message(self, chat, text, **kw):
                Bot.sent.append(text)
                return type("M", (), {"message_id": 1})()

            def send_location(self, *a, **k):
                pass

        service = ns.NotificationService()
        service._bot = Bot()
        service._record = lambda *a, **k: None
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        try:
            incident = {"incident_id": "i1", "category": "road_accident", "camera_name": "C", "place_text": "P", "latitude": 1, "longitude": 1,
                        "detection": {"peak_confidence": 0.7, "threshold_applied": 0.5}}
            plan = build_dispatch_plan("road_accident", 26.9, 75.8, ALL)
            self.assertTrue(service._send_telegram(incident, plan))
            text = Bot.sent[-1]
            self.assertIn("hospital: H1 (1.0 km)", text)
            self.assertIn("police station: P1 (0.5 km)", text)
            self.assertNotIn("fire", text.lower())
            plan_missing = build_dispatch_plan("fire", 26.9, 75.8, {"hospital": [_svc("H1", 1.0)], "fire": []})
            service._send_telegram({**incident, "incident_id": "i2", "category": "fire"}, plan_missing)
            self.assertIn("fire station: none found nearby", Bot.sent[-1])
            self.assertNotIn("police", Bot.sent[-1])
        finally:
            os.environ["TELEGRAM_CHAT_ID"] = ""


if __name__ == "__main__":
    unittest.main()
