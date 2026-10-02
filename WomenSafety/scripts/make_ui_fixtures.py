"""UI RENDERING FIXTURE, NOT A DETECTION. Creates ONE clearly labelled test-fixture incident of an action category
(fall / assault / snatching) in a SCRATCH database, so the dashboard's dispatch card, badges and map can be checked for
categories whose real detector has not fired on a provided clip.

The incident goes through the real ActionRuntime/EventCapturePipeline/handle_finished_event path, but the pose input is
a scripted geometry sequence (tests/action_synth.py) and the frames are plain dark images stamped "TEST FIXTURE". Its
evidence note says so. It refuses to run unless INCIDENTS_DB_PATH points away from the real incidents.db, and its
output must never go into the showcase or any real demo run.

    INCIDENTS_DB_PATH=<scratch.db> EVIDENCE_ROOT_V2=<scratch dir> ALERTS_ENABLED=false python scripts/make_ui_fixtures.py fall --camera CAM-001
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import cv2
import numpy as np

from api.core.config import settings

if Path(settings.INCIDENTS_DB_PATH).resolve() == (ROOT / "incidents.db").resolve() or os.environ.get("ALERTS_ENABLED", "").lower() != "false":
    sys.exit("refusing to run: set INCIDENTS_DB_PATH to a scratch database and ALERTS_ENABLED=false (these are fixtures, not detections)")

import action_synth as S
from api.models.incident_v2 import SourceKind
from api.services import incident_service_v2 as incidents
from api.services.action_detectors.runtime import ActionRuntime
from api.services.event_capture import RingBuffer

NOTE = "TEST FIXTURE: scripted pose sequence for UI rendering checks; NOT a real detection and not from any clip"


class ScriptedPose:
    available = True

    def __init__(self, script):
        self.script, self.i = script, 0

    def infer(self, frame):
        persons = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return [(p.box, p.kp) for p in persons]


def scenario(category):
    if category == "fall":
        return "fall", S.true_fall(stay_s=4.0) + S.stand_frames(2), None
    if category == "assault":
        return "violence", S.pair_sequence(24, gap=80, swing=1.0), (lambda frame: ("street violence", 0.31))
    if category == "snatching":
        return "snatch", S.approach_and_flee(), None
    raise SystemExit("category must be fall, assault or snatching")


def frame_for(i: int) -> np.ndarray:
    img = np.full((480, 640, 3), 38, np.uint8)
    cv2.putText(img, "TEST FIXTURE", (150, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (90, 90, 90), 3)
    cv2.putText(img, "scripted pose, not a detection", (120, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (90, 90, 90), 2)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--camera", default="CAM-001")
    args = ap.parse_args()
    name, seq, clip_fn = scenario(args.category)
    created = []

    def ready(cam, ev, evidence):
        inc = incidents.handle_finished_event(cam, ev, evidence, source=SourceKind.TEST_REPLAY, evidence_note=NOTE)
        if inc:
            created.append(inc.incident_id)

    buf = RingBuffer(settings.PRE_EVENT_SECONDS)
    runtime = ActionRuntime(args.camera, [name], ready, None, buf, clip_fn=clip_fn, pose=ScriptedPose(seq))
    n = len(seq)
    start = datetime.now(timezone.utc) - timedelta(seconds=n * 0.25 + 2)
    for i in range(n):
        ts = start + timedelta(seconds=i * 0.25)
        f = frame_for(i)
        buf.add(f, ts)
        runtime.add_raw_frame(f, ts, i * 0.25)
        runtime.process(f, i * 0.25, ts, i * 0.25)
    runtime.flush(start + timedelta(seconds=n * 0.25))
    runtime.join()
    runtime.close()
    import time
    deadline = time.time() + 40            # the dispatch plan is built by the notification worker thread; wait for it
    while created and time.time() < deadline and not (incidents.get_incident(created[0]) or {}).get("dispatch_plan"):
        time.sleep(0.5)
    print("fixture incidents created:", len(created), "(category", args.category + ", camera", args.camera + ")")
    return 0 if created else 1


if __name__ == "__main__":
    sys.exit(main())
