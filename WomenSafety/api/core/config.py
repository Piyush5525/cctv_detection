import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Incident Command Dashboard"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    EVIDENCE_CLIPS_DIR: Path = Path(__file__).parent.parent.parent / "evidence_clips"
    EVIDENCE_CLIP_DURATION_SECONDS: int = 10
    EVIDENCE_PRE_BUFFER_SECONDS: int = 5

    DETECTION_CONFIDENCE_THRESHOLD: float = 0.5

    # --- CCTV event-capture pipeline (CHANGELOG.md "CCTV Incident Capture
    # Pipeline" phase) -- shared by the live loop and the test-replay path.
    PRE_EVENT_SECONDS: float = 8.0
    POST_EVENT_SECONDS: float = 8.0
    EVENT_CONFIRM_N: int = 3
    EVENT_CONFIRM_M: int = 5
    EVENT_END_GAP_SECONDS: float = 5.0
    MAX_EVENT_SECONDS: float = 120.0
    EVENT_MERGE_SECONDS: float = 15.0
    EVIDENCE_ROOT_V2: Path = Path(__file__).parent.parent.parent / "evidence"
    THUMBNAIL_WIDTH: int = 320
    RETENTION_DAYS: int = 30
    INCIDENTS_DB_PATH: Path = Path(__file__).parent.parent.parent / "incidents.db"
    # Phase 1c hardening item 4: bounds the encoder queue so a camera
    # producing events faster than ffmpeg can encode them backs up and
    # sheds load (quarantines the overflow) instead of growing memory
    # unboundedly. 8 covers a burst of near-simultaneous events across
    # this project's few sample cameras with real margin.
    MAX_ENCODE_QUEUE_SIZE: int = 8

    # Phase 1c follow-ups item 1: the legacy Telegram/call alert path
    # (main.py's send_telegram_alert/send_call_alert) is now OFF by
    # default. Notification routing is being redesigned (see
    # CHANGELOG.md "routing phase" note); until that lands, alerts must
    # be explicitly opted into, not fire silently just because a camera
    # loop happens to be running.
    ALERTS_ENABLED: bool = False

    # Phase 1c follow-ups item 2: JPEG quality for ring-buffer/event
    # frame storage (api/services/event_capture.py). Raised from the
    # hardening phase's hardcoded 85 to a configurable value, default
    # raised to 90 per this follow-up's instruction.
    JPEG_QUALITY: int = 90

    # Phase 1c sampling unification: detection now samples frames by
    # video/wall-clock TIME (seconds), not by frame count, via one shared
    # function (api/services/frame_sampler.py) used by main.py's live
    # loop, scripts/camera_replay.py, and scripts/eval_detectors.py.
    # 0.25s (~4 fps) is close to what fire+crash YOLO inference actually
    # sustains on this machine's CPU (measured ~200-400ms/frame combined
    # in the Phase 1c follow-ups JPEG-overhead report) -- deliberately
    # NOT 0 (which would mean "every frame", reintroducing the risk of
    # inference falling behind real time with no defined fallback).
    SAMPLE_INTERVAL_S: float = 0.25

    # Phase 1c sampling unification (follow-up): lets main.py's live loop
    # run fire+crash ONLY (matching what the eval harness and
    # camera_replay.py measure/replay) for apples-to-apples FPS
    # comparison and testing. Defaults to True so ordinary live-deployment
    # behavior (violence/fall/snatch all running) is UNCHANGED unless
    # explicitly turned off.
    LEGACY_DETECTORS_ENABLED: bool = True

    # Phase 1c follow-up 2 (HIGH-priority finding, see CHANGELOG.md): the
    # eval harness (scripts/eval_detectors.py) and scripts/camera_replay.py
    # both apply VIDEO_MIN_CONFIDENCE=0.5 as a floor before ever counting a
    # fire/crash detection as a hit -- main.py's live loop applies NO such
    # floor, passing each detector's raw confidence straight through.
    # This means eval results do NOT describe live behavior: a detection
    # at e.g. 0.36 confidence is silently dropped by eval/replay but WOULD
    # create a real incident in live mode. Moved into one shared config
    # value so the three call sites can eventually agree -- but the
    # default here is set to CURRENT LIVE behavior (no floor, i.e. 0.0)
    # so NOTHING changes yet; eval_detectors.py/camera_replay.py must be
    # explicitly told to use the stricter floor (see --confidence-floor).
    # Phase 2 should run eval at BOTH FIRE_CRASH_CONFIDENCE_FLOOR (this
    # value) and 0.5, and report both, before deciding which one the
    # live loop should actually use.
    FIRE_CRASH_CONFIDENCE_FLOOR: float = 0.0

    # Phase 1c follow-up 2 item 3: a TEMPORARY measurement-only flag.
    # When true, main.py's live loop still runs fire/crash detection and
    # the sampling gate exactly as normal, but does NOT call
    # EventCapturePipeline.feed_detection() at all -- so no event ever
    # starts, no clip is ever encoded, and no incident is ever created.
    # Exists purely to isolate "detection throughput" from "detection +
    # event-lifecycle + ffmpeg-encode" for FPS measurement; not meant to
    # be a permanent deployment mode. Default False (normal behavior).
    DETECTION_ONLY_MODE: bool = False

    # Phase 1c follow-up 3 item 3: bounds for OCSortTracker.history
    # (snatch_detection/tracking/tracker.py), which previously grew one
    # entry per track_id FOREVER with no pruning at all (found via the
    # Phase 1c follow-up 2 memory soak test). Same semantics as
    # fall_detection.StateManager's expiry_seconds pattern (prune by
    # last-seen age) plus a per-track history cap.
    SNATCH_TRACKER_HISTORY_MAX_AGE_SECONDS: float = 30.0
    SNATCH_TRACKER_HISTORY_MAX_LEN: int = 30

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "allow"


settings = Settings()

settings.EVIDENCE_CLIPS_DIR.mkdir(parents=True, exist_ok=True)