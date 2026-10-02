import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Fix pass Phase 1 item 1: os.environ-based reads (SERPAPI_KEY, MAPBOX_TOKEN,
# TELEGRAM_*, OMNIDIM_*) only worked when main.py happened to call
# load_dotenv() first. Load the project .env here, by absolute path, so every
# run mode (uvicorn, run_dashboard --mode api, tests, scripts) sees it.
# override=False: a real shell/OS env var always wins over the file.
ENV_FILE = Path(__file__).parent.parent.parent / ".env"

load_dotenv(ENV_FILE, override=False)

# Directions API: the backend reads MAPBOX_TOKEN. If it is not set, reuse the
# dashboard's public token (frontend/.env VITE_MAPBOX_TOKEN, a browser-safe pk.*
# token that is also valid for Directions) rather than silently losing road
# routes. Value is never logged.
if "MAPBOX_TOKEN" not in os.environ:  # an explicit empty value (tests, offline runs) is respected
    from dotenv import dotenv_values
    _vite_token = dotenv_values(Path(__file__).parent.parent.parent / "frontend" / ".env").get("VITE_MAPBOX_TOKEN")
    if _vite_token:
        os.environ["MAPBOX_TOKEN"] = _vite_token


class Settings(BaseSettings):
    PROJECT_NAME: str = "Incident Command Dashboard"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Fix pass item 8: bind to localhost and only allow the dashboard origins.
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://127.0.0.1:8000", "http://localhost:8000",
        "http://127.0.0.1:3000", "http://localhost:3000",
    ]
    # Fix pass item 8: header X-Demo-Token must equal this value for
    # /demo/*, PATCH and DELETE routes. Unset => those routes are refused.
    DEMO_TOKEN: str = ""

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
    LEGACY_DETECTORS_ENABLED: bool = False

    # API-owned multi-camera demo workers.  They use the existing fire/crash
    # detector interface only; this changes no model or threshold.
    LIVE_CAMERA_WORKERS_ENABLED: bool = True
    # Fix pass item 3: file-replay "sample" CCTV cameras are OFF by default;
    # only camera_type "phone" cameras auto-start.
    SAMPLE_CAMERA_WORKERS_ENABLED: bool = False
    CAMERA_OPEN_TIMEOUT_S: float = 5.0
    DETECT_MAX_WIDTH: int = 640
    CAMERA_RECONNECT_INITIAL_S: float = 1.0
    CAMERA_RECONNECT_MAX_S: float = 15.0
    LIVE_VIEW_MAX_FPS: float = 8.0

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
    # Fix pass item 5 (2026-10-01): demo value is 0.5 (matches the eval
    # harness / camera_replay floor). Previously 0.0 (current-live behaviour)
    # which let 0.3-0.4 confidence detections become incidents.
    FIRE_CRASH_CONFIDENCE_FLOOR: float = 0.5

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

    # --- Dispatch backend (CHANGELOG.md "Dispatch Backend" phase) ---
    # DEMO_MODE defaults true: calls/Telegram messages go ONLY to the
    # allowlisted demo recipients below, never to a real looked-up
    # hospital/police/fire number -- see api/services/safety_guard.py,
    # the single place this rule (and the hard emergency-number block,
    # which applies regardless of DEMO_MODE) is enforced.
    DEMO_MODE: bool = True
    # DEMO_DRY_RUN: Telegram stays real, but NO call is ever placed (recorded "suppressed: dry run"). Can also be
    # flipped at runtime from the Demo panel (POST /api/v1/demo/dry-run, audited).
    DEMO_DRY_RUN: bool = False
    DEMO_PHONE_NUMBER: str = ""
    # If set, Telegram sends are restricted to exactly this chat_id
    # (DEMO_MODE allowlist) -- defaults to TELEGRAM_CHAT_ID itself when
    # unset, so an operator who only sets TELEGRAM_CHAT_ID (the existing
    # env var) gets the allowlist "for free" without a second value to
    # configure.
    TELEGRAM_CHAT_ID_ALLOWLIST: str = ""

    # SerpApi nearby-services lookup (api/services/nearby_services.py).
    # Reuses the same SERPAPI_KEY already used by the archived news-scrape
    # scripts -- read directly from the environment (not logged, not a
    # Settings field) via os.environ.get("SERPAPI_KEY"), same pattern as
    # scripts/fetch_india_incidents.py.
    NEARBY_SERVICES_CACHE_PATH: Path = Path(__file__).parent.parent.parent / "cache" / "nearby_services.json"
    NEARBY_SERVICES_CACHE_TTL_DAYS: int = 30
    NEARBY_SERVICES_MAX_API_CALLS_PER_RUN: int = 30  # hard cap: 4 cameras x 3 categories = 12 calls typical; 30 covers headroom without being unbounded
    NEARBY_SERVICES_TIMEOUT_S: float = 15.0
    NEARBY_SERVICES_KEEP_TOP_N: int = 3

    # Dispatch routing (api/services/dispatch_routing.py): Mapbox
    # Directions for route polyline/ETA, cached per camera-service pair.
    # MAPBOX_TOKEN read directly from env (not logged), same pattern as
    # frontend/.env's VITE_MAPBOX_TOKEN but this is the BACKEND's own
    # server-side key (Directions API is not a browser-safe call the
    # frontend should make with its own public token for this purpose).
    DISPATCH_ROUTE_CACHE_PATH: Path = Path(__file__).parent.parent.parent / "cache" / "dispatch_routes.json"
    DISPATCH_ROUTE_CACHE_TTL_DAYS: int = 30
    MAPBOX_DIRECTIONS_TIMEOUT_S: float = 10.0

    # Notification service (api/services/notification_service.py).
    ESCALATION_DELAY_S: float = 60.0
    DEMO_ESCALATION_DELAY_S: float = 20.0
    CALL_MIN_CONFIDENCE: float = 0.6  # fire at/above this confidence escalates to a call immediately, bypassing the delay
    # --- Device GPS for demo phones (api/services/phone_location.py) ---
    # "fixed" (DEFAULT): nothing GPS-related runs, behaviour/labels/incidents unchanged. Flip to "auto"
    # yourself once scripts/check_phone_gps.py confirms a source. See docs/GPS_BRINGUP.md.
    LOCATION_MODE: str = "fixed"          # fixed | auto | device
    MAX_FIX_AGE_S: float = 60.0
    MAX_ACCURACY_M: float = 50.0
    SMOOTH_FIXES: int = 5
    LOCATION_JUMP_M: float = 100.0
    LOCATION_POLL_S: float = 3.0
    NEARBY_PLAN_WAIT_S: float = 5.0       # max wait for a services lookup at incident time (phone, mode != fixed)
    DEMO_COOLDOWN_S: float = 15.0  # used instead of NOTIFICATION_COOLDOWN_S when DEMO_MODE=true (outbound only)
    NOTIFICATION_COOLDOWN_S: float = 120.0  # at most one alert per camera+category per this many seconds
    MAX_CALLS_PER_HOUR: int = 5
    # Spoken first on every call while DEMO_MODE=true so the recipient knows it is a demo.
    CALL_MESSAGE_PREFIX: str = "This is a test call for the Room 118 demo."
    NOTIFICATION_QUEUE_MAX_SIZE: int = 50
    NOTIFICATION_MAX_RETRIES: int = 3
    NOTIFICATION_RETRY_BACKOFF_S: float = 2.0
    TELEGRAM_VIDEO_MAX_BYTES: int = 50 * 1024 * 1024  # Telegram's own bot-API upload limit

    # --- Action detectors: fall / violence / snatch (api/services/action_detectors/) ---
    # EXPERIMENTAL. They only run on a camera whose "detectors" list (config/cameras.json, or the env
    # override DETECTORS_<CAMERA_ID>) names them. All thresholds live here; none is shared with fire/crash.
    AUTO_CALL_CATEGORIES: str = "fire,crash"   # only these may be called automatically; everything else needs "Escalate now"
    ACTION_COOLDOWN_S: float = 60.0            # outbound cooldown per camera+experimental category (>= the generic one)
    ACTION_POSE_INTERVAL_S: float = 0.25       # shared pose pass cadence (one YOLOv8n-pose pass feeds all action detectors)
    ACTION_POSE_MODEL: str = "yolov8n-pose.pt"
    ACTION_POSE_CONF: float = 0.35
    ACTION_MIN_PERSON_H_FRAC: float = 0.12     # ignore persons whose box is shorter than this fraction of the frame height
    ACTION_TRACK_MAX_MISSING_S: float = 1.5
    MIN_USEFUL_FPS: float = 2.0                # fire/crash effective fps below this => action detectors back off
    ACTION_MAX_THROTTLE: int = 8               # max interval multiplier while throttled
    # fall
    FALL_WINDOW_S: float = 6.0
    FALL_INTERVAL_S: float = 0.25
    FALL_UPRIGHT_ANGLE_DEG: float = 35.0       # torso angle from vertical below this = upright
    FALL_DOWN_ANGLE_DEG: float = 60.0          # torso angle at/above this = horizontal
    FALL_ASPECT_FLIP: float = 1.1              # box width/height at/above this = lying
    FALL_TRANSITION_S: float = 1.2             # upright -> down must happen within this (slower = lying down on purpose)
    FALL_HEAD_DROP_FRAC: float = 0.35          # head height drop, in standing box heights
    FALL_HIP_DROP_FRAC: float = 0.20           # hip height drop (bending forward drops the head, not the hips)
    FALL_DROP_VEL: float = 0.5                 # peak drop velocity, standing heights per second
    FALL_STAY_DOWN_S: float = 2.0
    FALL_SCORE_THRESHOLD: float = 0.6
    FALL_CONFIRM_N: int = 2
    FALL_CONFIRM_M: int = 3
    FALL_END_GAP_S: float = 6.0
    FALL_MERGE_S: float = 30.0
    # violence (CLIP zero-shot base score, gated)
    VIOLENCE_WINDOW_S: float = 3.0
    VIOLENCE_INTERVAL_S: float = 1.0           # CLIP cadence, only evaluated when the gates pass
    VIOLENCE_PROXIMITY: float = 1.2            # persons closer than this many body heights count as "close"
    VIOLENCE_MOTION_THRESHOLD: float = 1.0     # limb motion energy (body heights / s, torso motion removed)
    VIOLENCE_SUSTAIN_FRAC: float = 0.5         # fraction of the window that must exceed the motion threshold
    VIOLENCE_MIN_SPAN_S: float = 1.5           # minimum window coverage before the gate can open
    VIOLENCE_CLIP_THRESHOLD: float = 0.28      # CLIP cosine score for a violence/fight label
    VIOLENCE_SMOOTH_N: int = 3
    VIOLENCE_SMOOTH_M: int = 5
    VIOLENCE_CONFIRM_N: int = 2
    VIOLENCE_CONFIRM_M: int = 3
    VIOLENCE_END_GAP_S: float = 6.0
    VIOLENCE_MERGE_S: float = 30.0
    # snatch (tracking prototype, high thresholds)
    SNATCH_WINDOW_S: float = 3.0
    SNATCH_INTERVAL_S: float = 0.25
    SNATCH_FAR: float = 1.8                    # distance (body heights) before the approach
    SNATCH_NEAR: float = 0.8                   # distance at contact
    SNATCH_APPROACH_S: float = 1.5             # far -> near within this = sudden approach
    SNATCH_FLEE_SPEED: float = 2.5             # runner speed after contact, body heights per second
    SNATCH_ACCEL_RATIO: float = 2.0            # flee speed / approach speed
    SNATCH_FLEE_S: float = 1.5                 # flee must develop within this after contact
    SNATCH_SEPARATE: float = 1.5               # separation reached (body heights)
    SNATCH_SCORE_THRESHOLD: float = 0.7
    SNATCH_CONFIRM_N: int = 2
    SNATCH_CONFIRM_M: int = 3
    SNATCH_END_GAP_S: float = 6.0
    SNATCH_MERGE_S: float = 30.0

    class Config:
        case_sensitive = True
        env_file = str(ENV_FILE)
        extra = "allow"



# --- Dispatch rules (single source of truth) --------------------------------
# Which responders each incident category needs, PRIMARY FIRST (the first entry
# is the primary service, the rest are secondary). The backend dispatch_plan,
# the dashboard (card + map layer), the Telegram caption and the call text all
# read this table; the UI gets the already-filtered plan, it hard-codes nothing.
# Service types: "hospital", "police", "fire_station". Categories not listed
# (women_safety, any future one) use "other".
DISPATCH_RULES: dict[str, tuple[str, ...]] = {
    "fire": ("fire_station", "hospital"),
    "road_accident": ("hospital", "police"),
    "crash": ("hospital", "police"),
    "assault": ("police",),
    "snatching": ("police",),
    "fall": ("hospital",),
    "other": ("police",),
}
# Rule type -> key used by the SerpApi lookup / cache ("fire" there).
SERVICE_LOOKUP_KEY = {"hospital": "hospital", "police": "police", "fire_station": "fire"}
SERVICE_LABELS = {"hospital": "hospital", "police": "police station", "fire_station": "fire station"}


def required_services(category: str) -> tuple[str, ...]:
    return DISPATCH_RULES.get(category) or DISPATCH_RULES["other"]


settings = Settings()

settings.EVIDENCE_CLIPS_DIR.mkdir(parents=True, exist_ok=True)
