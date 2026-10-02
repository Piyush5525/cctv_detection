"""build_showcase.py for 1-5 incidents of ANY category (EXPERIMENTAL badge fields kept, evidence moved with the camera),
and the Load showcase / Reset demo mechanism restoring exactly that state. Uses a scratch source DB and evidence tree."""
import os
import sys
import tempfile
from pathlib import Path

_TEST_DIR = tempfile.mkdtemp(prefix="ws-showcase-tests-")
os.environ["INCIDENTS_DB_PATH"] = os.path.join(_TEST_DIR, "incidents.db")
os.environ["EVIDENCE_ROOT_V2"] = os.path.join(_TEST_DIR, "evidence")
os.environ["LIVE_CAMERA_WORKERS_ENABLED"] = "false"
os.environ["ALERTS_ENABLED"] = "false"
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "OMNIDIM_AGENT_ID", "SERPAPI_KEY", "MAPBOX_TOKEN"):
    os.environ[_key] = ""
os.environ["DEMO_PHONE_NUMBER"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import json
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from api import db
from api.core.config import settings
from api.services import demo_reset
from api.services import incident_service_v2 as incidents
import build_showcase

CAMS = ["CAM-SAMPLE-001", "CAM-SAMPLE-002", "CAM-SAMPLE-003", "CAM-SAMPLE-004"]
SERVICES = {"hospital": [{"title": "Hosp", "category": "hospital", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
            "police": [{"title": "Pol", "category": "police", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}],
            "fire": [{"title": "Fire", "category": "fire", "distance_km": 1.0, "gps_coordinates": {"latitude": 26.9, "longitude": 75.8}}]}


@contextmanager
def db_at(path):
    original = db.DB_PATH
    db.DB_PATH = Path(path)
    try:
        yield
    finally:
        db.DB_PATH = original


def make_source(tmp: Path, categories):
    """A scratch candidates DB + evidence folders under CAM-SAMPLE-001, like scripts/replay_candidates.py produces."""
    src = tmp / "incidents_candidates_test.db"
    ids = []
    with db_at(src):
        db.init_db()
        for category in categories:
            iid = str(uuid.uuid4())
            exp = category in ("fall", "assault", "snatching")
            folder = Path(settings.EVIDENCE_ROOT_V2) / "CAM-SAMPLE-001" / "2026-10-02" / iid
            folder.mkdir(parents=True, exist_ok=True)
            for name in ("best_frame.jpg", "thumbnail.jpg", "annotated_frame.jpg", "clip.mp4"):
                (folder / name).write_bytes(b"x" * 10)
            data = {"incident_id": iid, "camera_id": "CAM-SAMPLE-001", "camera_name": "x", "place_text": "x", "latitude": 26.9, "longitude": 75.8,
                    "category": category, "status": "new", "source": "test_replay", "event_start": "2026-10-02T10:00:00+00:00",
                    "detected_at": "2026-10-02T10:00:00+00:00",
                    "detection": {"peak_confidence": 0.8, "threshold_applied": 0.5, "frames_confirmed": "3 of 5", "experimental": exp,
                                  "signals": {"stay_down_s": 3.1} if exp else {}},
                    "evidence": {"best_frame_path": str(folder / "best_frame.jpg"), "thumbnail_path": str(folder / "thumbnail.jpg"),
                                 "clip_path": str(folder / "clip.mp4")}, "notifications": [{"channel": "telegram", "status": "sent"}]}
            db.insert_incident(iid, "CAM-SAMPLE-001", category, "new", "test_replay", data["event_start"], data)
            ids.append(iid)
    return src, ids


def read_all(path):
    with db_at(path):
        return {r["incident_id"]: r for r in incidents.list_incidents()}


class ShowcaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ws-showcase-"))
        self.p = patch.object(build_showcase, "cached_services", return_value=SERVICES)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_four_incidents_of_mixed_categories_use_three_cameras_one_with_two(self):
        src, ids = make_source(self.tmp, ["fire", "fall", "assault", "snatching"])
        out = self.tmp / "showcase.db"
        build_showcase.build(ids, str(src), out)
        rows = read_all(out)
        self.assertEqual(set(rows), set(ids))
        self.assertEqual([rows[i]["camera_id"] for i in ids], ["CAM-SAMPLE-001", "CAM-SAMPLE-001", "CAM-SAMPLE-002", "CAM-SAMPLE-003"])
        for iid, category in zip(ids, ["fire", "fall", "assault", "snatching"]):
            r = rows[iid]
            self.assertEqual(r["category"], category)
            self.assertEqual((r["source"], r["status"], r["notifications"]), ("test_replay", "new", []))
            exp = category != "fire"
            self.assertEqual(r["detection"]["experimental"], exp)                       # EXPERIMENTAL badge data kept
            self.assertEqual(r["detection"]["signals"], {"stay_down_s": 3.1} if exp else {})
        types = {c: [a["service_category"] for a in rows[i]["dispatch_plan"]["assignments"]] for i, c in zip(ids, ["fire", "fall", "assault", "snatching"])}
        self.assertEqual(types, {"fire": ["fire_station", "hospital"], "fall": ["hospital"], "assault": ["police"], "snatching": ["police"]})
        self.assertEqual(rows[ids[0]]["dispatch_plan"]["nearby_services_source"], "cache")

    def test_evidence_is_copied_to_the_new_camera_and_paths_repointed(self):
        src, ids = make_source(self.tmp, ["fire", "fall", "assault"])
        out = self.tmp / "showcase.db"
        build_showcase.build(ids, str(src), out)
        rows = read_all(out)
        for iid in ids:
            cam = rows[iid]["camera_id"]
            folder = Path(settings.EVIDENCE_ROOT_V2) / cam / "2026-10-02" / iid
            self.assertTrue((folder / "clip.mp4").exists(), cam)
            self.assertTrue(rows[iid]["evidence"]["clip_path"].startswith(str(folder)), cam)

    def test_uncached_camera_shows_services_unavailable_never_invented(self):
        src, ids = make_source(self.tmp, ["fall"])
        out = self.tmp / "showcase.db"
        with patch.object(build_showcase, "cached_services", return_value=None):
            build_showcase.build(ids, str(src), out)
        plan = read_all(out)[ids[0]]["dispatch_plan"]
        self.assertEqual(plan["nearby_services_source"], "unavailable")
        self.assertEqual([a["status"] for a in plan["assignments"]], ["unavailable"])
        self.assertNotIn("estimated", plan)

    def test_counts_one_to_five_accepted_zero_six_and_duplicates_refused(self):
        src, ids = make_source(self.tmp, ["fire", "fall", "assault", "snatching", "road_accident", "fire"])
        for n in (1, 2, 3, 5):
            out = self.tmp / f"s{n}.db"
            build_showcase.build(ids[:n], str(src), out)
            self.assertEqual(len(read_all(out)), n)
        for bad in ([], ids[:6], [ids[0], ids[0]]):
            with self.assertRaises(SystemExit):
                build_showcase.build(bad, str(src), self.tmp / "bad.db")

    def test_building_does_not_leave_the_process_pointed_at_the_showcase_db(self):
        src, ids = make_source(self.tmp, ["fall"])
        before = db.DB_PATH
        build_showcase.build(ids, str(src), self.tmp / "showcase.db")
        self.assertEqual(db.DB_PATH, before)


class LoadShowcaseResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ws-showcase-"))
        self.p = [patch.object(build_showcase, "cached_services", return_value=SERVICES), patch.object(demo_reset, "BACKUP_DIR", self.tmp / "backups"),
                  patch.object(demo_reset, "ROOT", self.tmp)]
        for p in self.p:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.p:
            p.stop()
        db.clear_all()

    def test_load_showcase_and_reset_restore_exactly_that_state(self):
        src, ids = make_source(self.tmp, ["fire", "fall", "assault", "snatching"])
        out = self.tmp / "showcase.db"
        build_showcase.build(ids, str(src), out)
        expected = read_all(out)
        # some unrelated incident exists in the live DB first
        db.insert_incident("x-live", "CAM-SAMPLE-004", "fire", "new", "live", "2026-10-02T09:00:00+00:00",
                           {"incident_id": "x-live", "category": "fire", "detection": {}, "notifications": []})
        r = demo_reset.reset(load_showcase=True, showcase_path=out)
        self.assertEqual(r["loaded_showcase_rows"], 4)
        after = {i["incident_id"]: i for i in incidents.list_incidents()}
        self.assertEqual(after, expected)                                              # exactly the showcase, nothing else
        # user acknowledges one, then Reset demo empties, then Load showcase restores the identical state
        demo_reset.reset(load_showcase=False)
        self.assertEqual(incidents.list_incidents(), [])
        demo_reset.reset(load_showcase=True, showcase_path=out)
        self.assertEqual({i["incident_id"]: i for i in incidents.list_incidents()}, expected)
        self.assertTrue(any(a["detection"]["experimental"] for a in after.values()))   # Experimental badge data survives the round trip
        self.assertEqual(sorted(p.name for p in (self.tmp / "backups").glob("*.db")).__len__(), 3)   # each reset backed the DB up first

    def test_missing_showcase_is_a_clear_error(self):
        with self.assertRaises(demo_reset.ShowcaseMissing):
            demo_reset.reset(load_showcase=True, showcase_path=self.tmp / "nope.db")


if __name__ == "__main__":
    unittest.main()
