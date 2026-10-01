"""Device GPS for demo phones (LOCATION_MODE) -- adapters are VERIFIED AGAINST SIMULATION ONLY:
mock HTTP (IP Webcam) and mock WebSocket (SensorServer) sources, no real phone, no network, no SerpApi."""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-gps-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["NEARBY_SERVICES_CACHE_PATH"] = os.path.join(_TEST_DIR, "nearby.json")
os.environ["DISPATCH_ROUTE_CACHE_PATH"] = os.path.join(_TEST_DIR, "routes.json")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""
os.environ["PHONE_CAM001_URL"] = "http://127.0.0.1:9/video"
os.environ["PHONE_CAM001_LAT"] = "26.9124"   # the fixed (.env) coordinates
os.environ["PHONE_CAM001_LNG"] = "75.7873"

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api import db
from api.core.config import settings
from api.models.camera import get_camera
from api.services import incident_service_v2 as incidents
from api.services import nearby_services as ns_mod
from api.services import notification_service as notif
from api.services.gps_adapters import Fix, IPWebcamHttpAdapter, SensorServerWsAdapter
from api.services.phone_location import PhoneLocation, distance_m, location_fields, location_manager, resolve_location

FIXED = (26.9124, 75.7873)
GPS = (26.9150, 75.7900)          # ~370 m away from the fixed placement, so the two sources are distinguishable


def fix(lat=GPS[0], lon=GPS[1], acc=8.0, age=2.0):
    return Fix(lat, lon, acc, time.time() - age)


class ModeCase(unittest.TestCase):
    def setUp(self):
        self.saved = (settings.LOCATION_MODE, settings.MAX_FIX_AGE_S, settings.MAX_ACCURACY_M, settings.SMOOTH_FIXES, settings.NEARBY_PLAN_WAIT_S, settings.LOCATION_POLL_S)
        settings.LOCATION_MODE = "auto"
        self.saved_cache = settings.NEARBY_SERVICES_CACHE_PATH
        settings.NEARBY_SERVICES_CACHE_PATH = Path(tempfile.mkdtemp(dir=_TEST_DIR)) / "nearby.json"  # fresh cache per test
        db.init_db()
        self.provider = PhoneLocation("CAM-001")
        location_manager.providers["CAM-001"] = self.provider

    def tearDown(self):
        (settings.LOCATION_MODE, settings.MAX_FIX_AGE_S, settings.MAX_ACCURACY_M, settings.SMOOTH_FIXES, settings.NEARBY_PLAN_WAIT_S, settings.LOCATION_POLL_S) = self.saved
        location_manager.providers.clear()
        settings.NEARBY_SERVICES_CACHE_PATH = self.saved_cache

    def where(self, camera_id="CAM-001"):
        loc = resolve_location(get_camera(camera_id))
        return None if loc is None else (loc.source, round(distance_m(loc.lat, loc.lon, *GPS)), round(distance_m(loc.lat, loc.lon, *FIXED)))


class ScenarioTests(ModeCase):
    def test_scenarios_and_fallback(self):
        results = {}
        self.provider.feed(fix()); results["good fix"] = self.where()
        self.assertEqual(results["good fix"][0], "device_gps")
        self.assertLess(results["good fix"][1], 5)

        self.provider.history.clear(); self.provider.feed(fix(acc=120.0)); results["poor accuracy (120 m)"] = self.where()
        self.provider.history.clear(); self.provider.feed(fix(age=300.0)); results["stale (300 s)"] = self.where()
        self.provider.history.clear(); self.provider.feed(fix(lat=51.5, lon=-0.12)); results["outside India"] = self.where()
        for name in ("poor accuracy (120 m)", "stale (300 s)", "outside India"):
            self.assertEqual(results[name][0], "camera_registry", name)   # falls back to the .env coordinates
            self.assertLess(results[name][2], 5, name)
        self.assertEqual(self.provider.status, "rejected: outside India")

        self.provider.history.clear()
        for _ in range(4):
            self.provider.feed(fix())
        self.provider.feed(fix(lat=GPS[0] + 0.005))                      # a single ~550 m jump
        results["single jump ignored"] = self.where()
        self.assertEqual(results["single jump ignored"][0], "device_gps")
        self.assertLess(results["single jump ignored"][1], 10)
        self.provider.feed(fix(lat=GPS[0] + 0.005))                      # the next fix confirms the move
        results["confirmed jump accepted"] = self.where()
        self.assertGreater(results["confirmed jump accepted"][1], 400)

        for name, value in results.items():
            print(f"  GPS scenario {name:28} -> {value}  (source, metres from GPS point, metres from fixed point)")

    def test_no_default_coordinates_when_nothing_is_available(self):
        with patch.dict(os.environ, {"PHONE_CAM001_LAT": "", "PHONE_CAM001_LNG": ""}):
            self.assertIsNone(resolve_location(get_camera("CAM-001")))        # no fix, no .env coordinates -> offline, nothing invented
            self.provider.feed(fix())
            self.assertEqual(resolve_location(get_camera("CAM-001")).source, "device_gps")   # a good fix is enough
            settings.LOCATION_MODE = "device"
            self.provider.history.clear()
            self.assertIsNone(resolve_location(get_camera("CAM-001")))        # device-only: waits for a fix

    def test_median_smoothing(self):
        for lat in (26.9150, 26.9151, 26.9150, 26.9152, 26.9150):
            self.provider.feed(fix(lat=lat))
        self.assertAlmostEqual(self.provider.position().lat, 26.9150, places=4)

    def test_mode_fixed_and_non_phone_cameras_never_use_device_gps(self):
        self.provider.feed(fix())
        settings.LOCATION_MODE = "fixed"
        self.assertEqual(self.where()[0], "camera_registry")                  # default mode: GPS ignored
        self.assertEqual(location_fields(get_camera("CAM-001"), resolve_location(get_camera("CAM-001"))), {})
        settings.LOCATION_MODE = "auto"
        location_manager.providers["CAM-SAMPLE-001"] = self.provider          # even if a fix existed for a sample camera id
        sample = get_camera("CAM-SAMPLE-001")
        loc = resolve_location(sample)
        self.assertEqual((loc.source, loc.lat, loc.lon), ("camera_registry", sample.latitude, sample.longitude))
        self.assertEqual(location_fields(sample, loc), {})                     # no GPS labels on sample cameras

    def test_cell_change_triggers_prefetch_only_for_a_new_cell(self):
        calls = []
        provider = PhoneLocation("CAM-001", on_cell_change=lambda cid, lat, lon: calls.append((cid, round(lat, 3), round(lon, 3))))
        provider.feed(fix()); provider.feed(fix(lat=GPS[0] + 0.00005))       # ~5 m: same ~100 m cell
        self.assertEqual(len(calls), 1)
        for _ in range(5):
            provider.feed(fix(lat=GPS[0] + 0.004))                           # ~440 m away: new cell once smoothed
        self.assertEqual(len(calls), 2)


class _Handler(BaseHTTPRequestHandler):
    payload = {}

    def do_GET(self):
        body = json.dumps(type(self).payload).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class SourceAdapterTests(ModeCase):
    def test_http_source_then_dropped_connection_falls_back(self):
        _Handler.payload = {"latitude": GPS[0], "longitude": GPS[1], "accuracy": 6.5, "time": int(time.time() * 1000)}
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        settings.LOCATION_POLL_S, settings.MAX_FIX_AGE_S = 0.2, 1.0
        provider = PhoneLocation("CAM-001", IPWebcamHttpAdapter.candidates(base))
        location_manager.providers["CAM-001"] = provider
        provider.start()
        try:
            deadline = time.time() + 5
            while not provider.position() and time.time() < deadline:
                time.sleep(0.1)
            self.assertEqual(self.where()[0], "device_gps")
            server.shutdown(); server.server_close()                          # the connection drops
            time.sleep(1.6)                                                   # fixes age past MAX_FIX_AGE_S
            self.assertEqual(self.where()[0], "camera_registry")             # fixed coordinates take over, history is kept
            self.assertTrue(provider.history)
            self.assertIn(provider.status, ("no GPS source reachable", "connection lost; retrying"))
        finally:
            provider.stop()

    def test_sensors_json_and_websocket_formats(self):
        now = time.time()
        sensors = {"gps": {"data": [[now * 1000, [26.9, 75.7, 400.0, 12.0]]]}}
        fix_ = IPWebcamHttpAdapter.parse(sensors, now)
        self.assertEqual((round(fix_.lat, 1), round(fix_.lon, 1), fix_.accuracy_m), (26.9, 75.7, 12.0))
        ws_fix = SensorServerWsAdapter.parse(json.dumps({"latitude": 26.9, "longitude": 75.7, "accuracy": 9, "time": int(now * 1000)}), now)
        self.assertEqual((ws_fix.accuracy_m, round(ws_fix.age_s)), (9.0, 0))
        self.assertIsNone(SensorServerWsAdapter.parse(json.dumps({"hello": 1}), now))

    def test_websocket_stream_feeds_provider(self):
        from websockets.sync.server import serve

        def handler(ws):
            for _ in range(3):
                ws.send(json.dumps({"latitude": GPS[0], "longitude": GPS[1], "accuracy": 7, "time": int(time.time() * 1000)}))
                time.sleep(0.1)
            time.sleep(1)

        with serve(handler, "127.0.0.1", 0) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.socket.getsockname()[1]
            provider = PhoneLocation("CAM-001", [SensorServerWsAdapter(f"ws://127.0.0.1:{port}/gps")])
            location_manager.providers["CAM-001"] = provider
            provider.start()
            deadline = time.time() + 5
            while not provider.position() and time.time() < deadline:
                time.sleep(0.1)
            provider.stop()
            self.assertEqual(self.where()[0], "device_gps")
            server.shutdown()


class IncidentLocationTests(ModeCase):
    def trigger(self, camera_id):
        from api.services.demo_trigger import trigger_demo_incident
        return trigger_demo_incident(camera_id, "crash")

    def test_phone_incident_uses_gps_else_fixed_and_others_are_unchanged(self):
        # --- good GPS fix: incident snapshot, Telegram pin, dispatch plan and routes all use it ---
        self.provider.feed(fix())
        gps_incident = self.trigger("CAM-001")
        self.assertEqual(gps_incident["location_source"], "device_gps")
        self.assertAlmostEqual(gps_incident["location_accuracy_m"], 8.0)
        self.assertLess(distance_m(gps_incident["latitude"], gps_incident["longitude"], *GPS), 5)
        self.assertEqual(gps_incident["source"], "test_replay")                # a trigger stays labelled test_replay

        pins, queries = [], []

        class Bot:
            def send_message(self, chat, text, **kw): return SimpleNamespace(message_id=1)
            def send_photo(self, chat, photo, **kw): return SimpleNamespace(message_id=1)
            def send_location(self, chat, lat, lon): pins.append((lat, lon))

        def fake_query(query, lat, lng):
            queries.append((round(lat, 3), round(lng, 3)))
            return [{"title": "Test Hospital", "type": "Hospital", "types": ["Hospital"], "phone": "+91", "place_id": "h",
                     "gps_coordinates": {"latitude": lat + 0.004, "longitude": lng + 0.002}}]

        service = notif.NotificationService()
        service._bot = Bot()
        service._record = lambda *a, **k: None
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        os.environ["SERPAPI_KEY"] = "FAKE"
        try:
            with patch.object(ns_mod, "_query_serpapi", side_effect=fake_query):
                plan = service._compute_plan(gps_incident)
            service._send_telegram(gps_incident, plan)
        finally:
            os.environ["TELEGRAM_CHAT_ID"] = ""
            os.environ["SERPAPI_KEY"] = ""
        self.assertEqual(pins, [(gps_incident["latitude"], gps_incident["longitude"])])
        route = plan["assignments"][0]["route"]
        self.assertLess(distance_m(route["geometry"]["coordinates"][0][1], route["geometry"]["coordinates"][0][0], *GPS), 5)  # route starts at the GPS position
        self.assertEqual(set(queries), {(round(gps_incident["latitude"], 3), round(gps_incident["longitude"], 3))})

        # --- same incident with GPS unavailable: the .env coordinates ---
        self.provider.history.clear()
        fixed_incident = self.trigger("CAM-001")
        self.assertEqual(fixed_incident["location_source"], "camera_registry")
        self.assertLess(distance_m(fixed_incident["latitude"], fixed_incident["longitude"], *FIXED), 5)

        # --- default mode (fixed): no GPS fields at all, coordinates are the .env ones even with a fresh fix ---
        settings.LOCATION_MODE = "fixed"
        self.provider.feed(fix())
        default_incident = self.trigger("CAM-001")
        self.assertIsNone(default_incident["location_source"])
        self.assertLess(distance_m(default_incident["latitude"], default_incident["longitude"], *FIXED), 5)

        # --- replay on a sample camera: registry coordinates, no GPS labels, in every mode ---
        settings.LOCATION_MODE = "auto"
        sample_cam = get_camera("CAM-SAMPLE-001")
        sample_incident = self.trigger("CAM-SAMPLE-001")
        self.assertIsNone(sample_incident["location_source"])
        self.assertEqual((sample_incident["latitude"], sample_incident["longitude"]), (sample_cam.latitude, sample_cam.longitude))
        print("  incident records (coordinates masked):")
        for name, inc in (("phone, good GPS", gps_incident), ("phone, GPS unavailable", fixed_incident), ("phone, mode=fixed", default_incident), ("sample replay", sample_incident)):
            print(f"    {name:24} location_source={inc['location_source']!s:16} accuracy_m={inc['location_accuracy_m']} fix_age_s={inc['location_fix_age_s']} lat/lng=<masked>")

    def test_showcase_data_is_never_touched(self):
        from api.services import demo_reset
        showcase = Path(_TEST_DIR) / "showcase.db"
        old_path = db.DB_PATH
        db.DB_PATH = showcase
        db.init_db()
        row = {"incident_id": "sc-1", "camera_id": "CAM-SAMPLE-001", "camera_name": "MI Road Junction (sample)", "place_text": "MI Road, Jaipur", "latitude": 26.9124,
               "longitude": 75.7873, "category": "fire", "status": "new", "source": "test_replay", "event_start": "2026-10-01T00:00:00+00:00", "notifications": [],
               "detection": {"peak_confidence": 0.7}}
        db.insert_incident("sc-1", "CAM-SAMPLE-001", "fire", "new", "test_replay", row["event_start"], row)
        db.DB_PATH = old_path
        demo_reset.reset(True, showcase)
        before = json.dumps(db.list_incidents(), sort_keys=True)
        self.provider.feed(fix())
        settings.LOCATION_MODE = "auto"
        location_manager.providers["CAM-001"] = self.provider
        demo_reset.reset(True, showcase)                                       # "Load showcase" again, with GPS active
        after = json.dumps(db.list_incidents(), sort_keys=True)
        self.assertEqual(before, after)
        self.assertEqual(db.list_incidents()[0]["source"], "test_replay")
        self.assertNotIn("device_gps", after)


class PlanTimingTests(ModeCase):
    def setUp(self):
        super().setUp()
        self.incident = {"incident_id": "t-1", "camera_id": "CAM-001", "category": "road_accident", "place_text": "p", "latitude": GPS[0], "longitude": GPS[1]}
        self.service = notif.NotificationService()
        self.records = []
        self.service._record = lambda iid, ch, st, rc, d: self.records.append((ch, st))
        self.set_plans = []
        self.service._set_dispatch_plan = lambda iid, plan: self.set_plans.append(plan)
        os.environ["SERPAPI_KEY"] = "FAKE"
        self.queries = []

    def tearDown(self):
        os.environ["SERPAPI_KEY"] = ""
        super().tearDown()

    def fake_query(self, delay=0.0):
        def query(q, lat, lng):
            time.sleep(delay)
            self.queries.append((round(lat, 3), round(lng, 3)))
            return [{"title": "Hospital X", "type": "Hospital", "types": ["Hospital"], "phone": "+91", "place_id": q,
                     "gps_coordinates": {"latitude": lat + 0.003, "longitude": lng + 0.002}}]
        return query

    def test_cache_hit_is_fast_and_makes_no_serpapi_calls(self):
        with patch.object(ns_mod, "_query_serpapi", side_effect=self.fake_query()):
            ns_mod.get_nearby_services("prefetch", GPS[0], GPS[1], "p")      # the prefetch
            warmed = len(self.queries)
            small_drift = dict(self.incident, latitude=GPS[0] + 0.0001)      # ~11 m away, same ~100 m cell
            started = time.time()
            plan = self.service._plan_for(small_drift)
            elapsed = time.time() - started
        self.assertEqual(warmed, 3)                                          # hospital, police, fire
        self.assertEqual(len(self.queries), 3)                               # the incident made no further calls
        self.assertEqual(plan["nearby_services_source"], "cache")
        self.assertLess(elapsed, 1.0)
        print(f"  cache-hit incident-to-plan: {elapsed:.3f} s, SerpApi calls at incident time: 0")

    def test_miss_waits_at_most_the_deadline_then_fills_the_plan_in(self):
        settings.NEARBY_PLAN_WAIT_S = 0.4
        with patch.object(ns_mod, "_query_serpapi", side_effect=self.fake_query(delay=0.4)):
            started = time.time()
            plan = self.service._plan_for(self.incident)
            elapsed = time.time() - started
            self.assertTrue(plan["lookup_pending"])
            self.assertTrue(all(a["status"] == "unavailable" and a["reason"] == "Lookup in progress" for a in plan["assignments"]))
            self.assertLess(elapsed, 0.9)                                    # alert is not held back past the deadline
            self.service._tg["t-1"] = {"chat_id": 1, "message_id": 1, "photo": False, "head": "h", "services": ["x"], "lines": [], "ack": False, "fp": False, "call": False}
            deadline = time.time() + 5
            while not self.set_plans and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(self.set_plans[-1]["assignments"][0]["status"], "available")   # filled in later
        self.assertIn(("dispatch", "plan_ready"), self.records)
        self.assertTrue(any("hospital: Hospital X" in line for line in self.service._tg["t-1"]["services"]))
        print(f"  cache-miss incident-to-alert: {elapsed:.2f} s (deadline 0.4 s in this test; 5 s by default), plan filled in afterwards")

    def test_other_locations_never_reuse_cached_results(self):
        with patch.object(ns_mod, "_query_serpapi", side_effect=self.fake_query()):
            ns_mod.get_nearby_services("a", GPS[0], GPS[1], "p")
            before = len(self.queries)
            ns_mod.get_nearby_services("b", GPS[0] + 0.02, GPS[1], "p")      # ~2 km away: a different cell
        self.assertEqual(len(self.queries) - before, 3)


if __name__ == "__main__":
    unittest.main()
