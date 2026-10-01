"""Shared frame-sampling rule (Phase 1c sampling unification), used by
BOTH main.py's live loop and every test/eval path (scripts/camera_replay.py,
scripts/eval_detectors.py) -- one function, not three duplicated copies of
frame-skip math.

Sampling is by TIME (seconds), not frame count: a frame is only handed to
a detector if at least `sample_interval_s` has elapsed since the last
sampled frame. This is deliberately different from "every Nth frame",
which silently drifts against real elapsed time whenever the source's
actual frame rate differs from its nominal one (a common real-camera
problem: a "30fps" RTSP stream that actually delivers 24-31fps
inconsistently). The ring buffer (api/services/event_capture.py) is
UNAFFECTED by this -- it keeps storing every frame it's given, for clip
quality; only DETECTION is throttled to the sampled subset.

Two modes, matching how frames actually arrive in each caller:
  - TimeBasedSampler (fast/deterministic): for a video FILE read via
    cv2.VideoCapture, where "time" is the file's own timeline
    (frame_index / native_fps) -- used by scripts/eval_detectors.py's
    --fast mode and scripts/camera_replay.py. Every frame that crosses a
    sample_interval_s boundary in VIDEO time is processed; this is
    reproducible and does not depend on how fast this machine can
    actually run inference.
  - RealtimeFrameGate (live): for a live camera loop or eval's
    --realtime mode, where "time" is the real wall clock and frames
    arrive continuously regardless of how long inference takes on the
    previous one. If inference falls behind the sample interval, stale
    frames are dropped (the gate always hands the detector the LATEST
    available frame, never queues up a backlog) and the achieved
    (post-drop) processing rate is tracked as effective_fps.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimeBasedSampler:
    """For a video FILE with a known native_fps: decides, for the frame
    at `frame_index`, whether enough VIDEO time has passed since the
    last sampled frame to process this one. Deterministic and
    reproducible -- the same video always yields the same sampled frame
    set regardless of how fast the machine reading it is."""
    native_fps: float
    sample_interval_s: float
    _last_sampled_video_t: Optional[float] = field(default=None, init=False)
    _sampled_count: int = field(default=0, init=False)

    def should_process(self, frame_index: int) -> bool:
        video_t = frame_index / self.native_fps
        if self._last_sampled_video_t is None or (video_t - self._last_sampled_video_t) >= self.sample_interval_s:
            self._last_sampled_video_t = video_t
            self._sampled_count += 1
            return True
        return False

    def video_time_of(self, frame_index: int) -> float:
        return frame_index / self.native_fps

    @property
    def sampled_count(self) -> int:
        return self._sampled_count

    @property
    def effective_sampled_fps(self) -> float:
        """The nominal sampling rate this interval implies (1/interval),
        NOT an achieved/measured rate -- fast mode is deterministic, so
        there's no "falling behind" concept to measure; this is exactly
        1/sample_interval_s, reported for symmetry with RealtimeFrameGate's
        measured effective_fps."""
        return 1.0 / self.sample_interval_s if self.sample_interval_s > 0 else float("inf")


@dataclass
class RealtimeFrameGate:
    """For a live feed (real camera, or a replay run in --realtime mode
    against the wall clock): frames arrive continuously; this gate
    decides whether enough WALL-CLOCK time has passed to process the
    next one, and always drops any frames that arrived in between
    rather than queuing them -- the live loop must process the LATEST
    frame, never fall further and further behind on old ones. Tracks
    the actually-achieved processing rate (effective_fps), which can be
    lower than 1/sample_interval_s if inference itself takes longer
    than the configured interval."""
    sample_interval_s: float
    label: str = "detection"
    _last_processed_wall_t: Optional[float] = field(default=None, init=False)
    _processed_count: int = field(default=0, init=False)
    _window_start: float = field(default_factory=time.time, init=False)
    _window_count: int = field(default=0, init=False)
    effective_fps: float = field(default=0.0, init=False)
    _fps_log_interval_s: float = field(default=5.0, init=False)

    def should_process(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        if self._last_processed_wall_t is None or (now - self._last_processed_wall_t) >= self.sample_interval_s:
            self._last_processed_wall_t = now
            self._processed_count += 1
            self._window_count += 1
            elapsed = now - self._window_start
            if elapsed >= self._fps_log_interval_s:
                self.effective_fps = self._window_count / elapsed
                print(f"[RealtimeFrameGate:{self.label}] effective processed FPS over last {elapsed:.1f}s: "
                      f"{self.effective_fps:.2f} (target: {1/self.sample_interval_s:.2f} @ {self.sample_interval_s}s interval)")
                self._window_count = 0
                self._window_start = now
            return True
        return False

    @property
    def processed_count(self) -> int:
        return self._processed_count


def confirmation_window_seconds(confirm_n: int, confirm_m: int, sample_interval_s: float) -> dict:
    """What EVENT_CONFIRM_N-of-EVENT_CONFIRM_M actually means in real
    time at a given sampling interval, now that confirmation counts
    SAMPLED frames only (not source frames) -- see
    api/services/event_capture.py's _recent_verdicts deque, which is
    fed one entry per sampled (not per raw) frame. M sampled frames
    span (M-1) sample intervals from the oldest to the newest; N hits
    within that window is the confirmation condition."""
    window_span_s = (confirm_m - 1) * sample_interval_s
    return {
        "confirm_n": confirm_n,
        "confirm_m": confirm_m,
        "sample_interval_s": sample_interval_s,
        "window_span_s": round(window_span_s, 3),
        "note": f"{confirm_n} of the last {confirm_m} SAMPLED frames must hit, "
                f"where those {confirm_m} sampled frames span {window_span_s:.2f}s of real/video time "
                f"at a {sample_interval_s}s sampling interval",
    }
