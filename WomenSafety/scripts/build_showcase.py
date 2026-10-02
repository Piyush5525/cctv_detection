"""Build demo/showcase.db from exactly the candidate incident ids you choose (1 to 5, any category).

  python scripts/build_showcase.py ID1 [ID2 ... ID5] [--source-db backups/xxx.db]

Pick the ids from demo/candidates.html (only true positives; fewer than 5 is fine). The script:
  * looks each id up in --source-db (default: newest backups/incidents_*.db
    that contains all the ids, including backups/incidents_candidates_*.db),
  * spreads them over 3 to 4 simulated camera locations (5 ids -> 4 cameras, the first with 2; 4 ids -> 3 cameras,
    the first with 2; 3 or fewer -> one camera each), rewriting camera_id / name / place / lat / lng from
    config/cameras.json and COPYING each incident's evidence folder to the new camera's evidence path (the API serves
    evidence by camera id),
  * keeps category, detection (including the EXPERIMENTAL flag and signals of fall / violence / snatching) and evidence,
  * forces source=test_replay, status=new and an empty notification list,
  * builds a full dispatch plan per incident from the cached SerpApi lookup
    (cache/nearby_services.json) if that camera has one; otherwise the plan is
    marked "estimated" (placeholder points, NOT real facilities).
It makes no network calls (Mapbox is disabled here; cached routes are reused,
otherwise straight-line fallback). It never picks ids for you. A camera with no cached services lookup shows its services as
unavailable (nothing is invented) unless you pass --allow-estimated.
"""
import argparse
import json
import os
import shutil
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
ASSIGNMENTS = {1: [0], 2: [0, 1], 3: [0, 1, 2], 4: [0, 0, 1, 2], 5: [0, 0, 1, 2, 3]}  # camera slot per incident
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


def cached_services(camera):
    """Cached lookup for the camera's ~100 m grid cell (no network)."""
    from api.services.nearby_services import lookup_cached
    hit = lookup_cached(camera.latitude, camera.longitude)
    return hit["services"] if hit else None


def estimated_services(lat, lng):
    offsets = {"hospital": (0.008, 0.004), "police": (-0.004, 0.007), "fire": (-0.008, -0.003)}
    return {cat: [{"title": f"Nearest {cat} (estimated - not a real facility)", "category": cat, "estimated": True,
                   "distance_km": 1.0, "phone": None,
                   "gps_coordinates": {"latitude": lat + dlat, "longitude": lng + dlng}}]
            for cat, (dlat, dlng) in offsets.items()}


def move_evidence(data: dict, old_camera: str, new_camera: str) -> str:
    """Copy evidence/<old camera>/<date>/<id>/ to the new camera's folder and repoint the stored paths."""
    root = Path(settings.EVIDENCE_ROOT_V2)
    date, iid = data["event_start"][:10], data["incident_id"]
    src, dst = root / old_camera / date / iid, root / new_camera / date / iid
    if src == dst:
        return "in place"
    if not src.exists():
        return f"WARNING: evidence folder missing at {old_camera}/{date}/{iid[:8]}"
    shutil.copytree(src, dst, dirs_exist_ok=True)
    for key, value in list((data.get("evidence") or {}).items()):
        if isinstance(value, str) and str(src) in value:
            data["evidence"][key] = value.replace(str(src), str(dst))
    return "copied"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="1 to 5 incident ids from demo/candidates.html")
    parser.add_argument("--source-db", help="DB holding the candidate incidents (default: search backups/)")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--allow-estimated", action="store_true",
                        help="for a camera with no cached lookup, use clearly labelled ESTIMATED placeholder points instead of showing the "
                             "services as unavailable (off by default: nothing is invented)")
    args = parser.parse_args()
    build(args.ids, args.source_db, Path(args.out), allow_estimated=args.allow_estimated)


def build(ids, source_db, out: Path, allow_estimated: bool = False):
    original_db_path = db.DB_PATH
    try:
        _build(ids, source_db, out, allow_estimated)
    finally:
        db.DB_PATH = original_db_path     # building must not leave the process pointed at showcase.db


def _build(ids, source_db, out: Path, allow_estimated: bool):
    if not 1 <= len(ids) <= 5 or len(set(ids)) != len(ids):
        raise SystemExit("ERROR: provide 1 to 5 distinct candidate incident ids (choose them from demo/candidates.html).")
    args = argparse.Namespace(ids=list(ids), source_db=source_db)
    source, rows = find_source(args.ids, args.source_db)
    if out.exists():
        out.unlink()
    db.DB_PATH = out
    out.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    summary = []
    for incident_id, slot in zip(args.ids, ASSIGNMENTS[len(args.ids)]):
        camera = get_camera(SHOWCASE_CAMERAS[slot])
        if camera is None:
            raise SystemExit(f"ERROR: {SHOWCASE_CAMERAS[slot]} missing from config/cameras.json")
        data = rows[incident_id]
        evidence_state = move_evidence(data, data["camera_id"], camera.camera_id)
        data.update({"camera_id": camera.camera_id, "camera_name": camera.display_name, "place_text": camera.place_text,
                     "latitude": camera.latitude, "longitude": camera.longitude, "location_precision": "exact",
                     "source": "test_replay", "status": "new", "notifications": [], "reviewed_by": None,
                     "reviewed_at": None, "review_note": None, "notification_status": "not_implemented"})
        services = cached_services(camera)
        origin = "cache" if services else ("estimated" if allow_estimated else "unavailable")
        plan = build_dispatch_plan(data["category"], camera.latitude, camera.longitude,
                                   services or (estimated_services(camera.latitude, camera.longitude) if allow_estimated else {}))
        plan["nearby_services_source"] = origin
        if origin == "estimated":
            plan["estimated"] = True
            plan["note"] = "Estimated placeholder points; no real SerpApi lookup was cached for this camera."
        elif origin == "unavailable":
            plan["note"] = "No cached services lookup for this camera: nothing invented, services shown as unavailable."
        data["dispatch_plan"] = plan
        db.insert_incident(incident_id, camera.camera_id, data["category"], "new", "test_replay", data["event_start"], data)
        summary.append((incident_id[:8], data["category"], camera.camera_id, origin, ("scripted" if data["detection"].get("scripted") else round(data["detection"]["peak_confidence"], 2)),
                        "experimental" if data["detection"].get("experimental") else "", evidence_state))
    print(f"source={source.name} -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    for row in summary:
        print("  ", row)
    print(f"built {len(summary)} incidents at {datetime.now(timezone.utc).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
