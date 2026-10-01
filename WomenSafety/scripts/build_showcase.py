"""Build demo/showcase.db from exactly the candidate incident ids you choose.

  python scripts/build_showcase.py ID1 ID2 ID3 ID4 ID5 [--source-db backups/xxx.db]

Pick the ids from demo/candidates.html. The script:
  * looks each id up in --source-db (default: newest backups/incidents_*.db
    that contains all the ids; the pre-fix live DB is in backups/),
  * spreads them over 4 simulated camera locations (first camera gets 2),
    rewriting camera_id / name / place / lat / lng from config/cameras.json,
  * forces source=test_replay, status=new and an empty notification list,
  * builds a full dispatch plan per incident from the cached SerpApi lookup
    (cache/nearby_services.json) if that camera has one; otherwise the plan is
    marked "estimated" (placeholder points, NOT real facilities).
It makes no network calls (Mapbox is disabled here; cached routes are reused,
otherwise straight-line fallback). It never picks ids for you.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ["MAPBOX_TOKEN"] = ""  # offline build

from api import db  # noqa: E402
from api.core.config import settings  # noqa: E402
from api.models.camera import get_camera  # noqa: E402
from api.services.dispatch_routing import REQUIRED_SERVICES, build_dispatch_plan  # noqa: E402

SHOWCASE_CAMERAS = ["CAM-SAMPLE-001", "CAM-SAMPLE-002", "CAM-SAMPLE-003", "CAM-SAMPLE-004"]
ASSIGNMENT = [0, 0, 1, 2, 3]  # one camera with 2 incidents, three with 1
OUT = ROOT / "demo" / "showcase.db"


def find_source(ids, explicit):
    candidates = [Path(explicit)] if explicit else sorted((ROOT / "backups").glob("incidents_*.db"), reverse=True)
    for path in candidates:
        if not path.exists():
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = {r[0]: json.loads(r[1]) for r in con.execute(
                f"SELECT incident_id, data FROM incidents WHERE incident_id IN ({','.join('?' * len(ids))})", ids)}
        except sqlite3.Error:
            rows = {}
        finally:
            con.close()
        if len(rows) == len(ids):
            return path, rows
    raise SystemExit(f"ERROR: could not find all {len(ids)} ids in {[str(c) for c in candidates][:3]}...; pass --source-db")


def cached_services(camera_id):
    path = settings.NEARBY_SERVICES_CACHE_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(camera_id, {}).get("services")
    except Exception:
        return None


def estimated_services(lat, lng):
    offsets = {"hospital": (0.008, 0.004), "police": (-0.004, 0.007), "fire": (-0.008, -0.003)}
    return {cat: [{"title": f"Nearest {cat} (estimated - not a real facility)", "category": cat, "estimated": True,
                   "distance_km": 1.0, "phone": None,
                   "gps_coordinates": {"latitude": lat + dlat, "longitude": lng + dlng}}]
            for cat, (dlat, dlng) in offsets.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="exactly 5 incident ids from demo/candidates.html")
    parser.add_argument("--source-db", help="DB holding the candidate incidents (default: search backups/)")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    if len(args.ids) != 5 or len(set(args.ids)) != 5:
        raise SystemExit("ERROR: provide exactly 5 distinct candidate incident ids (choose them from demo/candidates.html).")
    source, rows = find_source(args.ids, args.source_db)
    out = Path(args.out)
    if out.exists():
        out.unlink()
    db.DB_PATH = out
    out.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    summary = []
    for incident_id, slot in zip(args.ids, ASSIGNMENT):
        camera = get_camera(SHOWCASE_CAMERAS[slot])
        if camera is None:
            raise SystemExit(f"ERROR: {SHOWCASE_CAMERAS[slot]} missing from config/cameras.json")
        data = rows[incident_id]
        data.update({"camera_id": camera.camera_id, "camera_name": camera.name, "place_text": camera.place_text,
                     "latitude": camera.latitude, "longitude": camera.longitude, "location_precision": "exact",
                     "source": "test_replay", "status": "new", "notifications": [], "reviewed_by": None,
                     "reviewed_at": None, "review_note": None, "notification_status": "not_implemented"})
        services = cached_services(camera.camera_id)
        origin = "cache" if services else "estimated"
        plan = build_dispatch_plan(data["category"], camera.latitude, camera.longitude,
                                   services or estimated_services(camera.latitude, camera.longitude))
        plan["nearby_services_source"] = origin
        if origin == "estimated":
            plan["estimated"] = True
            plan["note"] = "Estimated placeholder points; no real SerpApi lookup was cached for this camera."
        data["dispatch_plan"] = plan
        db.insert_incident(incident_id, camera.camera_id, data["category"], "new", "test_replay", data["event_start"], data)
        summary.append((incident_id[:8], data["category"], camera.camera_id, origin, round(data["detection"]["peak_confidence"], 2)))
    print(f"source={source.name} -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    for row in summary:
        print("  ", row)
    print(f"built {len(summary)} incidents at {datetime.now(timezone.utc).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
