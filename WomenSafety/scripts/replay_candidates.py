"""Phase 6: replay ONLY the provided clips through the real detectors and the same pipeline into a SCRATCH database, so
real detections can be reviewed as showcase candidates (scripts/build_candidates_gallery.py renders them).

Clips: data/demo/{fall,violence,snatch}.mp4 and the fire / crash sample clips data/fire.mp4, data/crash.mp4. All five
detectors run on every clip, so a detection can come from another detector than the clip's own class (labelled as such).
Nothing is forced, padded or duplicated: every candidate is a real confirmed event with its own incident id; a detector
that did not fire contributes nothing.

The scratch DB is backups/incidents_candidates_<timestamp>.db (git-ignored; the real incidents.db is never touched).
Evidence files are written under evidence/ (git-ignored). Alerts are forced off and no credentials are loaded.

    python scripts/replay_candidates.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STAMP = time.strftime("%Y%m%d_%H%M%S")
DB_PATH = ROOT / "backups" / f"incidents_candidates_{STAMP}.db"
DB_PATH.parent.mkdir(exist_ok=True)
os.environ.update(INCIDENTS_DB_PATH=str(DB_PATH), ALERTS_ENABLED="false", LIVE_CAMERA_WORKERS_ENABLED="false", KMP_DUPLICATE_LIB_OK="TRUE",
                  TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="", OMNIDIM_API_KEY="", OMNIDIM_AGENT_ID="", SERPAPI_KEY="", MAPBOX_TOKEN="", DEMO_PHONE_NUMBER="")

from api.models.incident_v2 import SourceKind
from api.services import incident_service_v2 as incidents
from api.services.action_detectors import ACTION_NAMES
from api.services.clip_replay import replay_clip

CAMERA = "CAM-SAMPLE-001"   # the replay camera; build_showcase.py later moves chosen incidents (and their evidence) to showcase cameras
CLIPS = ["data/demo/fall.mp4", "data/demo/violence.mp4", "data/demo/snatch.mp4", "data/fire.mp4", "data/crash.mp4"]


def main() -> int:
    total = 0
    for rel in CLIPS:
        path = ROOT / rel
        if not path.exists():
            print(f"skip (missing): {rel}")
            continue

        def on_event(cam, ev, evidence, _rel=rel):
            a, b = evidence.get("video_offset_start_s"), evidence.get("video_offset_end_s")
            span = f"{a:.1f}-{b:.1f} s" if a is not None and b is not None else "unknown span"
            note = (f"candidate replay of {_rel} ({span}); real detection, peak score {ev.peak_score:.2f} vs threshold {ev.threshold_applied}"
                    + ("; EXPERIMENTAL" if ev.experimental else ""))
            inc = incidents.handle_finished_event(cam, ev, evidence, source=SourceKind.TEST_REPLAY, evidence_note=note)
            return inc.to_dict() if inc else None

        print(f"replaying {rel} ...", flush=True)
        rep = replay_clip(path, CAMERA, action_names=ACTION_NAMES, fire_crash=True, on_event=on_event)
        made = [e for e in rep.events if e.incident]
        total += len(made)
        for e in rep.events:
            print(f"   {e.detector:9s} {e.start_s:6.1f}-{e.end_s:6.1f} s  peak={e.peak_score}  {e.confirmations}  "
                  f"{'incident ' + e.incident['incident_id'][:8] if e.incident else 'NOT CREATED (quarantined)'}")
        if not rep.events:
            print("   (no detector fired)")
    print(f"\ncandidates created: {total}\nscratch DB: {DB_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
