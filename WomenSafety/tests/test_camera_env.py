"""CAM-001 phone camera: registry shape, env-driven coordinates / stream / password, no leaks."""
import json
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="ws-cam-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import threading
import time
import unittest
from unittest.mock import patch

from api.models import camera as cam_mod
from api.models.camera import CAMERAS_CONFIG_PATH, Camera, get_camera, resolve_stream_source
from api.services import camera_workers

PHONE_ENV = {"PHONE_CAM001_URL": "http://10.0.0.5:8080/video", "PHONE_CAM001_LAT": "26.9124", "PHONE_CAM001_LNG": "75.7873"}


class RegistryFileTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(CAMERAS_CONFIG_PATH.read_text(encoding="utf-8"))["cameras"]

    def test_phone_cameras_cam_001_and_002_driven_by_env_refs(self):
        phones = {c["camera_id"]: c for c in self.raw if c["camera_type"] == "phone"}
        self.assertEqual(sorted(phones), ["CAM-001", "CAM-002"])
        for number, (cam_id, name) in enumerate((("CAM-001", "CAM 001"), ("CAM-002", "CAM 002")), start=1):
            phone = phones[cam_id]
            self.assertEqual(phone["name"], name)
            self.assertEqual(phone["location_basis"], "real_installation")
            self.assertEqual((phone["stream_source"], phone["latitude"], phone["longitude"]),
                             (f"env:PHONE_CAM00{number}_URL", f"env:PHONE_CAM00{number}_LAT", f"env:PHONE_CAM00{number}_LNG"))
            self.assertNotIn("://", json.dumps(phone))  # no URL anywhere in the file entry
        self.assertEqual(len({c["camera_id"] for c in self.raw}), len(self.raw))  # no duplicate ids
        self.assertFalse([c for c in self.raw if c["camera_id"].startswith("PHONE-")])

    def test_display_name_exactly_once(self):
        with patch.dict(os.environ, PHONE_ENV):
            self.assertEqual(get_camera("CAM-001").display_name, "Demo phone camera - CAM 001")
        self.assertEqual(Camera(camera_id="X", name="Demo phone camera - CAM 001", place_text="p", latitude=26.9, longitude=75.8,
                                stream_source="0", camera_type="phone").display_name, "Demo phone camera - CAM 001")


class EnvResolutionTests(unittest.TestCase):
    def _location(self, **env):
        with patch.dict(os.environ, {**PHONE_ENV, **env}):
            return get_camera("CAM-001")

    def test_valid_env_coordinates_resolve(self):
        cam = self._location()
        self.assertIsNone(cam.location_error)
        self.assertEqual((cam.latitude, cam.longitude), (26.9124, 75.7873))

    def test_unset_invalid_or_out_of_range_never_default(self):
        for env, needle in ((dict(PHONE_CAM001_LAT=""), "is unset"), (dict(PHONE_CAM001_LAT="not-a-number"), "not a number"),
                            (dict(PHONE_CAM001_LAT="51.5"), "outside the India bounding box"), (dict(PHONE_CAM001_LNG="200"), "outside the India bounding box")):
            cam = self._location(**env)
            self.assertIsNone(cam.latitude)
            self.assertIsNone(cam.longitude)
            self.assertIn(needle, cam.location_error)
            for value in env.values():
                if value:
                    self.assertNotIn(value, cam.location_error)  # names, never values
        with patch.dict(os.environ, PHONE_ENV):
            os.environ.pop("PHONE_CAM001_LNG")
            self.assertIn("PHONE_CAM001_LNG is unset", get_camera("CAM-001").location_error)

    def test_credentials_in_config_value_rejected(self):
        with self.assertRaises(Exception):
            Camera(camera_id="X", name="n", place_text="p", latitude=26.9, longitude=75.8, stream_source="http://user:secret@10.0.0.5/video")

    def test_password_built_in_memory_and_never_in_errors(self):
        camera = get_camera("CAM-001")
        with patch.dict(os.environ, {**PHONE_ENV, "PHONE_CAM001_USER": "ann", "PHONE_CAM001_PASSWORD": "p@ss word"}):
            self.assertEqual(resolve_stream_source(camera), "http://ann:p%40ss%20word@10.0.0.5:8080/video")
        with patch.dict(os.environ, {**PHONE_ENV, "PHONE_CAM001_PASSWORD": "topsecret"}):
            os.environ.pop("PHONE_CAM001_USER", None)
            with self.assertRaises(ValueError) as ctx:
                resolve_stream_source(camera)
            self.assertIn("PHONE_CAM001_USER", str(ctx.exception))
            self.assertNotIn("topsecret", str(ctx.exception))
        with patch.dict(os.environ, {"PHONE_CAM001_URL": ""}):
            with self.assertRaises(ValueError) as ctx:
                resolve_stream_source(camera)
            self.assertEqual(str(ctx.exception), "env var PHONE_CAM001_URL is not set")

    def test_worker_stays_offline_with_clear_error_and_never_opens_stream(self):
        camera = self._location(PHONE_CAM001_LAT="")
        worker = camera_workers.CameraWorker(camera, registry=None, detector_lock=threading.Lock())
        with patch.object(camera_workers, "_open_capture", side_effect=AssertionError("must not open the stream")):
            worker.reader.start()
            time.sleep(0.4)
            detail = worker.detail()
            worker._stop.set()
        self.assertEqual(detail["status"], "offline")
        self.assertIn("location not configured", detail["error"])
        self.assertNotIn("10.0.0.5", json.dumps(detail))
        self.assertEqual(detail["camera_name"], "Demo phone camera - CAM 001")


if __name__ == "__main__":
    unittest.main()
