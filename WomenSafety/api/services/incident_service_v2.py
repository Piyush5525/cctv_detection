"""CCTV-only incident service (CHANGELOG.md "CCTV Incident Capture
Pipeline" phase). Bridges EventCapturePipeline's finished-evidence
callback to a real Incident row in SQLite (api/db.py), enforcing the
Part 4 validation rules: a camera incident MUST have coordinates,
event_start, a best_frame and a clip, or it is quarantined with a
reason instead of silently dropped or stored incomplete. Confidence is
never null for a camera incident (unlike the archived news-scrape
model) -- every incident here was scored by a real detector run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from api import db
from api.models.camera import get_camera
from api.models.incident_v2 import (
    Incident, Detection, Evidence, BBox, Category, IncidentStatus,
    SourceKind, IncidentStatusUpdate, QuarantinedEvent, utcnow,
)
from api.services.event_capture import ActiveEvent

db.init_db()

_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []


def subscribe() -> asyncio.Queue:
    """Called from the WebSocket route (inside the event loop)."""
    q = asyncio.Queue()
    _subscribers.append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers[:] = [(loop, queue) for loop, queue in _subscribers if queue is not q]


def publish_created(incident: Incident) -> None:
    """Fix pass item 13: thread-safe push to WebSocket subscribers. Called
    from the encoder/worker thread right after the durable insert; the
    dashboard keeps its 2 s polling as the fallback."""
    for loop, queue in list(_subscribers):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, incident)
        except RuntimeError:  # loop closed
            pass


class IncidentQuarantineError(ValueError):
    pass


def _category_from_class_name(name: str) -> Category:
    mapping = {
        "crash": Category.ROAD_ACCIDENT, "accident": Category.ROAD_ACCIDENT,
        "fire": Category.FIRE, "smoke": Category.FIRE,
        "violence": Category.ASSAULT, "fight": Category.ASSAULT,
        "snatch": Category.SNATCHING, "snatching": Category.SNATCHING,
        "fall": Category.FALL,
        "women_safety": Category.WOMEN_SAFETY,
    }
    return mapping.get(name.lower(), Category.OTHER)


def handle_finished_event(camera_id: str, ev: ActiveEvent, evidence_raw: dict, source: SourceKind = SourceKind.LIVE, evidence_note: Optional[str] = None) -> Optional[Incident]:
    """Synchronous entry point called from the event-capture encoder
    thread (not the asyncio loop). Validates, persists, and schedules
    the async WebSocket notification. Returns the created Incident, or
    None if the event was quarantined."""
    cam = get_camera(camera_id)
    reason = None
    if cam is None:
        reason = f"unknown camera_id {camera_id!r} -- not in the camera registry"
    elif cam.latitude is None or cam.longitude is None:
        reason = "camera registry entry has no coordinates"
    elif ev.event_start is None:
        reason = "event has no event_start"
    elif not evidence_raw.get("best_frame_path"):
        reason = "event produced no best_frame"
    elif not evidence_raw.get("clip_path"):
        reason = "event produced no clip"

    best = evidence_raw.get("best")
    hit_frames = evidence_raw.get("hit_frames", [])
    if reason is None and (best is None or not hit_frames):
        reason = "event had no confirmed-detection frames (confidence would be null, which is not allowed for camera incidents)"

    if reason:
        q = QuarantinedEvent(
            camera_id=camera_id,
            category=ev.category if ev else None,
            reason=reason,
            event_start=ev.event_start if ev else None,
            raw_data={"confirmations": getattr(ev, "confirmations", None)},
        )
        db.insert_quarantine(q.quarantine_id, camera_id, q.quarantined_at.isoformat(), q.model_dump(mode="json"))
        print(f"[IncidentService] QUARANTINED camera={camera_id} reason={reason}")
        return None

    mean_conf = sum(fs.confidence for fs in hit_frames) / len(hit_frames)
    peak_conf = max(fs.confidence for fs in hit_frames)
    bboxes = [BBox(label=b["label"], conf=b.get("confidence", best.confidence), box=list(b["box"])) for b in best.boxes]

    try:
        incident = Incident(
            incident_id=evidence_raw["incident_id"],
            camera_id=cam.camera_id,
            camera_name=cam.name,
            place_text=cam.place_text,
            latitude=cam.latitude,
            longitude=cam.longitude,
            location_precision="exact",
            category=_category_from_class_name(ev.category),
            event_start=ev.event_start,
            event_end=ev.last_detection_at,
            duration_s=round((ev.last_detection_at - ev.event_start).total_seconds(), 2),
            detected_at=utcnow(),
            video_offset_start_s=evidence_raw.get("video_offset_start_s"),
            video_offset_end_s=evidence_raw.get("video_offset_end_s"),
            detection=Detection(
                detector_source=ev.detector_source,
                model_name=ev.model_name,
                weights_file=ev.weights_file,
                weights_sha256=ev.weights_sha256,
                peak_confidence=round(peak_conf, 4),
                mean_confidence=round(mean_conf, 4),
                threshold_applied=ev.threshold_applied,
                frames_confirmed=ev.confirmations,
                best_frame_bbox=bboxes,
            ),
            evidence=Evidence(
                best_frame_path=evidence_raw["best_frame_path"],
                annotated_frame_path=evidence_raw.get("annotated_frame_path"),
                thumbnail_path=evidence_raw["thumbnail_path"],
                clip_path=evidence_raw.get("clip_path"),
                clip_duration_s=evidence_raw.get("clip_duration_s"),
                width=evidence_raw["width"],
                height=evidence_raw["height"],
                fps=evidence_raw["fps"],
                sha256_clip=evidence_raw.get("sha256_clip"),
                sha256_frame=evidence_raw["sha256_frame"],
                note=evidence_note,
            ),
            source=source,
        )
    except Exception as e:
        # e.g. Incident's own event_start-not-future validator -- a bad
        # value here is a real anomaly (a clock issue, or code feeding it
        # a bogus timestamp), not something to coerce quietly. Quarantine
        # with the real validation error rather than crash the encoder
        # thread or silently store an invalid incident.
        q = QuarantinedEvent(
            camera_id=camera_id, category=ev.category, reason=f"incident validation failed: {e}",
            event_start=ev.event_start, raw_data={"confirmations": ev.confirmations},
        )
        db.insert_quarantine(q.quarantine_id, camera_id, q.quarantined_at.isoformat(), q.model_dump(mode="json"))
        print(f"[IncidentService] QUARANTINED camera={camera_id} reason=incident validation failed: {e}")
        return None

    db.insert_incident(
        incident.incident_id, incident.camera_id, incident.category.value,
        incident.status.value, incident.source.value, incident.event_start.isoformat(),
        incident.to_dict(),
    )
    # Dispatch work (SerpApi/Mapbox/Telegram) is deliberately queued only
    # after the durable incident insert.  The encoder thread never waits on
    # network I/O and every notification update has a real incident to edit.
    from api.services.notification_service import notification_service
    notification_service.enqueue(incident)
    publish_created(incident)
    print(f"[IncidentService] INCIDENT CREATED {incident.incident_id} camera={camera_id} "
          f"category={incident.category.value} peak_conf={peak_conf:.2f}")
    return incident


def handle_encode_failure(camera_id: str, category: Optional[str], reason: str,
                           event_start, partial_evidence: Optional[dict] = None) -> None:
    """Persists a quarantine record for an event whose CLIP ENCODING
    failed (Phase 1c hardening item 4: missing ffmpeg, non-zero exit, or
    timeout) -- this is the on_quarantine callback path, distinct from
    handle_finished_event's validation-failure quarantines, because a
    clip-encode failure means handle_finished_event never runs at all
    (on_incident_ready is never called). partial_evidence, when present,
    carries the real best_frame_path/annotated_frame_path/thumbnail_path
    that WERE written successfully before ffmpeg failed -- stored in the
    quarantine record's raw_data so that evidence stays discoverable
    instead of being an orphaned file no record points to."""
    q = QuarantinedEvent(
        camera_id=camera_id,
        category=category,
        reason=reason,
        event_start=event_start,
        raw_data={"kept_evidence": {
            k: v for k, v in (partial_evidence or {}).items()
            if k in ("best_frame_path", "annotated_frame_path", "thumbnail_path", "sha256_frame")
        }} if partial_evidence else {},
    )
    db.insert_quarantine(q.quarantine_id, camera_id, q.quarantined_at.isoformat(), q.model_dump(mode="json"))
    print(f"[IncidentService] QUARANTINED (encode failure) camera={camera_id} reason={reason}")


def get_incident(incident_id: str) -> Optional[dict]:
    return db.get_incident(incident_id)


def list_incidents(camera_id=None, category=None, status=None, source=None,
                    start_date=None, end_date=None, limit=None, offset=0) -> list[dict]:
    rows = db.list_incidents(camera_id, category, status, source, start_date, end_date)
    if limit is not None:
        return rows[offset:offset + limit]
    return rows


def count_all() -> int:
    return db.count_incidents()


def update_status(incident_id: str, update: IncidentStatusUpdate) -> Optional[dict]:
    data = db.get_incident(incident_id)
    if data is None:
        return None
    data["status"] = update.status.value
    data["reviewed_by"] = update.reviewed_by
    data["review_note"] = update.review_note
    data["reviewed_at"] = utcnow().isoformat()
    data["updated_at"] = utcnow().isoformat()
    db.update_incident_data(incident_id, update.status.value, data)
    return data


def append_notification(incident_id: str, record: dict) -> Optional[dict]:
    """Append one delivery-timeline item atomically to an existing incident."""
    def mutate(data):
        data.setdefault("notifications", []).append(record)
        data["updated_at"] = utcnow().isoformat()
    return db.mutate_incident_data(incident_id, mutate)


def set_dispatch_plan(incident_id: str, plan: dict) -> Optional[dict]:
    def mutate(data):
        data["dispatch_plan"] = plan
        data["updated_at"] = utcnow().isoformat()
    return db.mutate_incident_data(incident_id, mutate)


def list_quarantine() -> list[dict]:
    return db.list_quarantine()
