"""CCTV-only incident schema (CHANGELOG.md "CCTV Incident Capture
Pipeline" phase). Replaces the mobile/upload/news-scrape provenance
model in api/models/incident.py + api/models/provenance.py for the
live product -- those modules are kept only because
archive/news_scrape_incidents.json and the archived scraper scripts
still reference their shapes, not because the live API uses them.

Every incident here comes from a registered fixed camera (live feed or
a --test-replay of a local video file standing in for one). There is
no source_type variant, no device_id, no GPS accuracy, no manual pin:
location is always an exact snapshot of the camera registry entry at
creation time.
"""
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List
import uuid

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


MAX_FUTURE_SKEW_SECONDS = 5  # small allowance for clock drift between camera-loop threads


class Category(str, Enum):
    ROAD_ACCIDENT = "road_accident"
    FIRE = "fire"
    ASSAULT = "assault"
    SNATCHING = "snatching"
    FALL = "fall"
    WOMEN_SAFETY = "women_safety"
    OTHER = "other"


class IncidentStatus(str, Enum):
    NEW = "new"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"


class SourceKind(str, Enum):
    LIVE = "live"
    TEST_REPLAY = "test_replay"


class BBox(BaseModel):
    label: str
    conf: float
    box: List[float]  # [x1, y1, x2, y2] in the frame's own pixel space


class Detection(BaseModel):
    detector_source: str  # e.g. "yolov8-crash", "clip-fallback", "st-gcn-snatch"
    model_name: str
    weights_file: Optional[str] = None
    weights_sha256: Optional[str] = None
    peak_confidence: float = Field(ge=0.0, le=1.0)
    mean_confidence: float = Field(ge=0.0, le=1.0)
    threshold_applied: float
    frames_confirmed: str  # "N of M", e.g. "3 of 5"
    best_frame_bbox: List[BBox] = Field(default_factory=list)
    # Action detectors (fall / violence / snatch) only. `experimental` drives the dashboard badge, the Telegram/call
    # wording and the alert policy (no automatic call). `signals` are the scalar signals that fired on the peak
    # frame (e.g. drop velocity, stay-down seconds) -- never keypoints or any biometric data.
    experimental: bool = False
    signals: dict = Field(default_factory=dict)


class Evidence(BaseModel):
    best_frame_path: str
    annotated_frame_path: Optional[str] = None
    thumbnail_path: str
    clip_path: Optional[str] = None
    clip_duration_s: Optional[float] = None
    width: int
    height: int
    fps: float
    sha256_clip: Optional[str] = None
    sha256_frame: str
    note: Optional[str] = None  # e.g. "synthetic demo trigger" (fix pass item 9)


class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str

    # Camera snapshot at creation time -- see module docstring. Always
    # "exact": this product has no other location precision level.
    camera_name: str
    place_text: str
    latitude: float
    longitude: float
    location_precision: str = "exact"
    # Set only for phone cameras when LOCATION_MODE != fixed ("device_gps" | "camera_registry"); else None.
    location_source: Optional[str] = None
    location_accuracy_m: Optional[float] = None
    location_fix_age_s: Optional[float] = None

    category: Category

    event_start: datetime
    event_end: datetime
    duration_s: float
    detected_at: datetime = Field(default_factory=utcnow)

    # Phase 1c hardening item 3: video-relative offsets (source video's
    # own elapsed seconds, frame_index / source_fps), populated ONLY for
    # source="test_replay" incidents -- there is no "source video" a live
    # incident could be relative to, so these stay null for source="live".
    video_offset_start_s: Optional[float] = None
    video_offset_end_s: Optional[float] = None

    detection: Detection
    evidence: Evidence

    status: IncidentStatus = IncidentStatus.NEW
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None

    source: SourceKind

    # Dispatch Backend phase: replaces the old "not_implemented"
    # placeholder with a real per-channel notification timeline. Each
    # entry is one row from NotificationRecord (channel, status,
    # timestamps, redacted recipient label, error text). Kept as a
    # plain List[dict] here (not a typed sub-model) so the notification
    # service, which is the only writer, owns the exact shape -- see
    # api/services/notification_service.py's NotificationRecord.
    notifications: List[dict] = Field(default_factory=list)

    # Dispatch Backend phase: the computed dispatch plan (nearest
    # required services per category, distance, route/ETA) -- built
    # once at incident-creation time and stored here so the incident
    # detail endpoint can expose it without recomputing on every read.
    dispatch_plan: Optional[dict] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("event_start", "event_end", "detected_at", "reviewed_at", "created_at", "updated_at", mode="before")
    @classmethod
    def _assume_utc_if_naive(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("event_start")
    @classmethod
    def _event_start_not_future(cls, v):
        now = datetime.now(timezone.utc)
        if v > now + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
            raise ValueError(f"event_start {v.isoformat()} is in the future (now={now.isoformat()}) -- "
                              f"a camera incident's event_start comes from the capture-time clock and cannot be ahead of it")
        return v

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None


class QuarantinedEvent(BaseModel):
    """An event that failed the camera-incident validation rules (Part 4:
    must have coordinates, event_start, best_frame and clip). Kept for
    operator visibility instead of being silently dropped."""
    quarantine_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: Optional[str] = None
    category: Optional[str] = None
    reason: str
    event_start: Optional[datetime] = None
    raw_data: dict = Field(default_factory=dict)
    quarantined_at: datetime = Field(default_factory=utcnow)
