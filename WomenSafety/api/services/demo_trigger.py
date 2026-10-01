"""Create a clearly-labelled test replay incident from a stored sample frame."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import cv2

from api.models.incident_v2 import SourceKind
from api.services.event_capture import EventCapturePipeline
from api.services import incident_service_v2 as incidents

SAMPLES = {"fire": Path("data/fire.mp4"), "road_accident": Path("data/crash.mp4"), "crash": Path("data/crash.mp4")}

def trigger_demo_incident(camera_id: str, category: str):
    source = SAMPLES.get(category)
    if source is None: raise ValueError("category must be fire, crash, or road_accident")
    root = Path(__file__).parent.parent.parent
    cap = cv2.VideoCapture(str(root / source)); ok, frame = cap.read(); cap.release()
    if not ok: raise RuntimeError(f"stored sample clip unavailable: {source}")
    created = []
    def ready(cam, event, evidence):
        incident = incidents.handle_finished_event(cam, event, evidence, source=SourceKind.TEST_REPLAY)
        if incident: created.append(incident.to_dict())
    pipeline = EventCapturePipeline(camera_id, ready, lambda *args: incidents.handle_encode_failure(*args))
    now = datetime.now(timezone.utc); mapped = "crash" if category in {"crash", "road_accident"} else category
    for index in range(3):
        ts = now + timedelta(seconds=index)
        pipeline.add_raw_frame(frame, ts)
        pipeline.feed_detection(frame, ts, mapped, .99, [{"label": mapped, "confidence": .99, "box": [0, 0, frame.shape[1], frame.shape[0]]}], "demo-trigger", "stored-sample", .0)
    pipeline.flush(now + timedelta(seconds=9)); pipeline._encode_queue.join()
    if not created: raise RuntimeError("sample event was quarantined; check ffmpeg and evidence output")
    return created[0]
