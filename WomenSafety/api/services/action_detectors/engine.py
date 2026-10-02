"""Per-camera action engine: ONE shared pose pass per sampled frame, one tracker, one sliding window, and the
camera's listed action detectors each evaluated at their own cadence.

Cost rules:
  * nothing runs unless the camera's detector list names an action detector (the engine is not even built);
  * the pose pass is the person detector: with nobody in frame the detectors do no work (violence's CLIP never
    runs without persons, fall/snatch only get idle verdicts that let an open event wind down);
  * auto-throttle: the owner reports the camera's fire/crash effective fps; below MIN_USEFUL_FPS every action
    interval is multiplied (x2 per step, up to ACTION_MAX_THROTTLE) and relaxed again once fps recovers.
All times are seconds supplied by the caller (wall clock live, video time in replay/eval), never read here, so
replays are deterministic.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Callable, Optional

import cv2
import numpy as np

from api.core.config import settings
from api.services.action_detectors.base import ActionDetector, ActionResult, PoseFrame
from api.services.action_detectors.fall import FallDetector
from api.services.action_detectors.pose import SharedPose, SimpleTracker
from api.services.action_detectors.snatch import SnatchDetector
from api.services.action_detectors.violence import ViolenceDetector

ACTION_NAMES = ("fall", "violence", "snatch")
_FACTORIES = {"fall": FallDetector, "violence": ViolenceDetector, "snatch": SnatchDetector}

# One lock for the shared pose/CLIP models (the objects are shared by every camera in the process).
model_lock = threading.Lock()

# on_verdict(detector, result, frame, ts, video_offset_s) -- boxes/keypoints in `frame` coordinates
VerdictCb = Callable[[ActionDetector, ActionResult, np.ndarray, datetime, Optional[float]], None]


def build_detectors(names, clip_fn=None) -> list:
    out = []
    for n in names:
        if n == "violence":
            out.append(ViolenceDetector(clip_fn=clip_fn))
        elif n in _FACTORIES:
            out.append(_FACTORIES[n]())
    return out


class ActionEngine:
    def __init__(self, camera_id: str, names, on_verdict: Optional[VerdictCb] = None, pose: Optional[SharedPose] = None, clip_fn=None,
                 pose_interval_s: Optional[float] = None, max_width: Optional[int] = None):
        self.camera_id = camera_id
        self.detectors = build_detectors([n for n in names if n in ACTION_NAMES], clip_fn=clip_fn)
        self.on_verdict = on_verdict
        self.pose = pose if pose is not None else SharedPose()
        self.tracker = SimpleTracker()
        self.pose_interval_s = settings.ACTION_POSE_INTERVAL_S if pose_interval_s is None else pose_interval_s
        self.max_width = settings.DETECT_MAX_WIDTH if max_width is None else max_width
        self._window: deque = deque()
        self._last_pose_t: Optional[float] = None
        self._last_eval: dict = {}
        self.throttle = 1
        self._last_throttle_check: Optional[float] = None
        # measured cost counters (reported by the perf script / status)
        self.pose_passes = 0
        self.pose_time_s = 0.0
        self.detector_runs: dict = {d.name: 0 for d in self.detectors}

    @property
    def enabled(self) -> bool:
        return bool(self.detectors) and self.pose.available

    # --- throttle --------------------------------------------------------------
    def update_throttle(self, base_fps: Optional[float], t: float) -> None:
        """base_fps = the camera's measured fire/crash effective fps (None = no fire/crash on this camera)."""
        if base_fps is None or (self._last_throttle_check is not None and t - self._last_throttle_check < 2.0):
            return
        self._last_throttle_check = t
        if base_fps < settings.MIN_USEFUL_FPS and self.throttle < settings.ACTION_MAX_THROTTLE:
            self.throttle = min(self.throttle * 2, settings.ACTION_MAX_THROTTLE)
            print(f"[ActionEngine:{self.camera_id}] fire/crash fps {base_fps:.2f} < MIN_USEFUL_FPS {settings.MIN_USEFUL_FPS}: action interval x{self.throttle}")
        elif base_fps >= 1.5 * settings.MIN_USEFUL_FPS and self.throttle > 1:
            self.throttle //= 2

    # --- main ------------------------------------------------------------------
    def process(self, frame: np.ndarray, t: float, ts: datetime, video_offset_s: Optional[float] = None) -> list:
        """Returns [(detector, ActionResult)] for the detectors evaluated on this call ([] when it was not due)."""
        if not self.enabled:
            return []
        if self._last_pose_t is not None and t - self._last_pose_t < self.pose_interval_s * self.throttle:
            return []
        self._last_pose_t = t
        h, w = frame.shape[:2]
        scale = min(1.0, self.max_width / w)
        small = frame if scale == 1.0 else cv2.resize(frame, (int(w * scale), int(h * scale)))
        sh, sw = small.shape[:2]

        import time as _time
        t0 = _time.perf_counter()
        with model_lock:
            dets = self.pose.infer(small)
        self.pose_time_s += _time.perf_counter() - t0
        self.pose_passes += 1
        dets = [(b, k) for b, k in dets if max(b[3] - b[1], b[2] - b[0]) >= settings.ACTION_MIN_PERSON_H_FRAC * sh]
        persons = self.tracker.update(dets, t)

        if self._window:
            self._window[-1].frame = None          # only the newest PoseFrame keeps its image
        self._window.append(PoseFrame(t=t, persons=persons, frame_h=sh, frame_w=sw, frame=small))
        horizon = max(d.window_s for d in self.detectors) + 1e-6
        while len(self._window) > 1 and t - self._window[0].t > horizon:
            self._window.popleft()

        out = []
        for d in self.detectors:
            last = self._last_eval.get(d.name)
            if last is not None and t - last < d.interval_s * self.throttle:
                continue
            self._last_eval[d.name] = t
            win = [pf for pf in self._window if t - pf.t <= d.window_s + 1e-6]
            if not any(pf.persons for pf in win):      # nobody in the whole window: nothing to evaluate (pose drops out between passes)
                res = d.idle()
            else:
                res = d.detect(win)
                self.detector_runs[d.name] += 1
            res = self._scale_result(res, 1.0 / scale)
            out.append((d, res))
            if self.on_verdict is not None:
                self.on_verdict(d, res, frame, ts, video_offset_s)
        return out

    @staticmethod
    def _scale_result(res: ActionResult, k: float) -> ActionResult:
        if k == 1.0:
            return res
        for b in res.boxes:
            b["box"] = [round(v * k, 2) for v in b["box"]]
            if "keypoints" in b:
                b["keypoints"] = [[round(x * k, 2), round(y * k, 2), c] for x, y, c in b["keypoints"]]
        return res

    def describe(self) -> list:
        return [d.describe() for d in self.detectors]
