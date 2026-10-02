"""One shared pose pass per sampled frame, and a light per-camera tracker.

The pose model (YOLOv8n-pose) is loaded once per process and shared by every camera and every action
detector; each camera has its own SimpleTracker so track ids never mix between cameras. The tracker is a
greedy nearest-centroid matcher with constant-velocity prediction (a sprinting person moves about one body
height per sample at 4 Hz, which defeats IoU matching).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import numpy as np

from api.core.config import settings
from api.services.action_detectors.base import PersonPose

ROOT = Path(__file__).resolve().parent.parent.parent.parent

_pose_lock = threading.Lock()
_pose_model = None
_pose_failed = False


def pose_weights_path() -> Path:
    p = Path(settings.ACTION_POSE_MODEL)
    return p if p.is_absolute() else ROOT / p


def get_pose_model():
    """Lazy process-wide singleton. Returns None (and remembers) if it cannot be loaded."""
    global _pose_model, _pose_failed
    if _pose_model is not None or _pose_failed:
        return _pose_model
    with _pose_lock:
        if _pose_model is None and not _pose_failed:
            try:
                from ultralytics import YOLO
                _pose_model = YOLO(str(pose_weights_path()))
                print(f"[ActionDetectors] shared pose model loaded: {pose_weights_path().name}")
            except Exception as exc:  # pragma: no cover - environment dependent
                _pose_failed = True
                print(f"[ActionDetectors] pose model unavailable ({type(exc).__name__}); action detectors disabled")
    return _pose_model


class SharedPose:
    """infer(frame) -> [(box, kp(17,3))] for every person found. Callers serialise access with a lock
    (the model object is shared across cameras)."""

    def __init__(self, model=None):
        self.model = model if model is not None else get_pose_model()

    @property
    def available(self) -> bool:
        return self.model is not None

    def infer(self, frame: np.ndarray) -> list:
        res = self.model(frame, verbose=False, conf=settings.ACTION_POSE_CONF, classes=[0])
        out = []
        r = res[0]
        if r.keypoints is None or r.boxes is None or len(r.boxes) == 0:
            return out
        xyxy = r.boxes.xyxy.cpu().numpy()
        xy = r.keypoints.xy.cpu().numpy()
        kc = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(xy.shape[:2])
        for i in range(len(xyxy)):
            kp = np.concatenate([xy[i], kc[i][:, None]], axis=1)
            out.append((tuple(float(v) for v in xyxy[i]), kp))
        return out


class SimpleTracker:
    def __init__(self, max_missing_s: Optional[float] = None, gate: float = 1.3):
        self.max_missing_s = settings.ACTION_TRACK_MAX_MISSING_S if max_missing_s is None else max_missing_s
        self.gate = gate          # max match distance, in body heights
        self._tracks: dict = {}   # id -> dict(center, v, t, h)
        self._next_id = 1

    def update(self, detections: list, t: float) -> list:
        """detections: [(box, kp)] -> [PersonPose with stable track ids]."""
        cands = []
        for box, kp in detections:
            c = np.array([(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0])
            cands.append((box, kp, c, max(box[3] - box[1], 1.0)))
        pairs = []
        for ci, (_, _, c, h) in enumerate(cands):
            for tid, tr in self._tracks.items():
                dt = max(t - tr["t"], 1e-3)
                pred = tr["center"] + tr["v"] * dt
                scale = max(h, tr["h"])
                d = min(np.linalg.norm(c - pred), np.linalg.norm(c - tr["center"])) / scale
                if d <= self.gate:
                    pairs.append((d, ci, tid))
        pairs.sort()
        used_c, used_t, assign = set(), set(), {}
        for d, ci, tid in pairs:
            if ci in used_c or tid in used_t:
                continue
            used_c.add(ci); used_t.add(tid); assign[ci] = tid
        out = []
        for ci, (box, kp, c, h) in enumerate(cands):
            tid = assign.get(ci)
            if tid is None:
                tid = self._next_id; self._next_id += 1
                self._tracks[tid] = {"center": c, "v": np.zeros(2), "t": t, "h": h}
            else:
                tr = self._tracks[tid]
                dt = max(t - tr["t"], 1e-3)
                tr["v"] = (c - tr["center"]) / dt
                tr["center"], tr["t"], tr["h"] = c, t, h
            out.append(PersonPose(track_id=tid, box=box, kp=kp))
        for tid in [k for k, tr in self._tracks.items() if t - tr["t"] > self.max_missing_s]:
            del self._tracks[tid]
        return out
