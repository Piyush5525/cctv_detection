"""Evidence endpoint: photo and clip 200/206 with the right content-type and Accept-Ranges, HEAD, suffix and bad ranges,
path traversal still blocked, missing file -> clean JSON 404 the UI can show."""
import os
import tempfile
from pathlib import Path

_TEST_DIR = tempfile.mkdtemp(prefix="ws-evidence-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""

import unittest

from api.core.config import settings
from api.routes.evidence import _parse_range

CAM, DAY, IID = "CAM-SAMPLE-001", "2026-10-02", "11111111-2222-3333-4444-555555555555"
CLIP = bytes(range(256)) * 40          # 10240 bytes
JPEG = b"\xff\xd8\xff" + b"j" * 997    # 1000 bytes


class EvidenceServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(settings.EVIDENCE_ROOT_V2) / CAM / DAY / IID
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "clip.mp4").write_bytes(CLIP)
        (folder / "best_frame.jpg").write_bytes(JPEG)
        (folder / "thumbnail.jpg").write_bytes(JPEG)
        from fastapi.testclient import TestClient
        from api.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.base = f"/api/v1/evidence/v2/{CAM}/{DAY}/{IID}"

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)

    def test_photo_200_and_range_206_with_type_and_accept_ranges(self):
        r = self.client.get(f"{self.base}/best_frame.jpg")
        self.assertEqual((r.status_code, r.headers["content-type"], r.headers["accept-ranges"]), (200, "image/jpeg", "bytes"))
        self.assertEqual(len(r.content), 1000)
        r = self.client.get(f"{self.base}/thumbnail.jpg", headers={"Range": "bytes=0-99"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers["content-range"], "bytes 0-99/1000")

    def test_clip_200_then_206_ranges_seek(self):
        r = self.client.get(f"{self.base}/clip.mp4")
        self.assertEqual((r.status_code, r.headers["content-type"], r.headers["accept-ranges"], int(r.headers["content-length"])), (200, "video/mp4", "bytes", 10240))
        self.assertEqual(r.content, CLIP)
        r = self.client.get(f"{self.base}/clip.mp4", headers={"Range": "bytes=5000-5999"})
        self.assertEqual((r.status_code, r.headers["content-range"], r.content), (206, "bytes 5000-5999/10240", CLIP[5000:6000]))
        r = self.client.get(f"{self.base}/clip.mp4", headers={"Range": "bytes=10000-"})
        self.assertEqual((r.status_code, r.content), (206, CLIP[10000:]))
        r = self.client.get(f"{self.base}/clip.mp4", headers={"Range": "bytes=-240"})            # suffix range (used by some players)
        self.assertEqual((r.status_code, r.headers["content-range"], r.content), (206, "bytes 10000-10239/10240", CLIP[-240:]))

    def test_unsatisfiable_range_is_416_and_garbage_range_serves_the_whole_file(self):
        r = self.client.get(f"{self.base}/clip.mp4", headers={"Range": "bytes=20000-"})
        self.assertEqual((r.status_code, r.headers["content-range"]), (416, "bytes */10240"))
        r = self.client.get(f"{self.base}/clip.mp4", headers={"Range": "bytes=abc-def"})
        self.assertEqual((r.status_code, len(r.content)), (200, 10240))

    def test_head_requests_work_for_photo_and_clip(self):
        for name, ctype, size in (("clip.mp4", "video/mp4", "10240"), ("best_frame.jpg", "image/jpeg", "1000")):
            r = self.client.head(f"{self.base}/{name}")
            self.assertEqual((r.status_code, r.headers["content-type"], r.headers["content-length"]), (200, ctype, size), name)

    def test_missing_file_is_a_clean_json_404(self):
        r = self.client.get(f"{self.base}/annotated_frame.jpg")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "Evidence file not found"})
        r = self.client.get(f"/api/v1/evidence/v2/{CAM}/{DAY}/no-such-incident/clip.mp4")
        self.assertEqual(r.status_code, 404)

    def test_path_traversal_is_still_blocked(self):
        for bad in ("..%2F..%2F..%2Fincidents.db", "%2e%2e%2f%2e%2e%2fincidents.db", "..%5C..%5Cincidents.db"):
            r = self.client.get(f"/api/v1/evidence/v2/{CAM}/{DAY}/{bad}/clip.mp4")
            self.assertIn(r.status_code, (403, 404))
        r = self.client.get(f"/api/v1/evidence/v2/..%2F..%2Fx/{DAY}/{IID}/clip.mp4")
        self.assertIn(r.status_code, (403, 404))

    def test_parse_range_unit(self):
        self.assertEqual(_parse_range("bytes=0-99", 1000), (0, 99))
        self.assertEqual(_parse_range("bytes=900-", 1000), (900, 999))
        self.assertEqual(_parse_range("bytes=0-5000", 1000), (0, 999))
        self.assertEqual(_parse_range("bytes=-100", 1000), (900, 999))
        self.assertIsNone(_parse_range("bytes=0-1,5-9", 1000))
        self.assertIsNone(_parse_range("items=0-1", 1000))
        with self.assertRaises(ValueError):
            _parse_range("bytes=1000-", 1000)
        with self.assertRaises(ValueError):
            _parse_range("bytes=-0", 1000)


if __name__ == "__main__":
    unittest.main()
