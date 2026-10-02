"""ActionRuntime: one ActionEngine plus one EventCapturePipeline per listed action detector, wired together.

Used by BOTH the live CameraWorker and the demo/clip replay, so a replayed clip goes through exactly the same
engine -> verdict -> per-detector pipeline -> evidence path as a live camera (the only difference is the clock:
wall time live, video time in a replay).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Callable, Optional

import numpy as np

from api.services.action_detectors.engine import ActionEngine
from api.services.action_detectors.pose import pose_weights_path
from api.services.event_capture import EventCapturePipeline, RingBuffer


class ActionRuntime:
    def __init__(self, camera_id: str, names, on_incident_ready: Callable, on_quarantine: Optional[Callable],
                 pre_buffer: RingBuffer, engine_factory: Callable = ActionEngine, **engine_kwargs):
        self.camera_id = camera_id
        self.engine = engine_factory(camera_id, names, on_verdict=self._verdict, **engine_kwargs)
        self.pipelines: dict = {}
        self.verdicts: list = []       # (video/wall t is not known here) kept only when record=True
        self.record = False
        path = pose_weights_path()
        self._pose_weights = (str(path), hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)
        if self.engine.enabled:
            for d in self.engine.detectors:
                # own confirmation / end / merge settings per detector, sharing the camera's ring buffer
                self.pipelines[d.name] = EventCapturePipeline(
                    camera_id, on_incident_ready, on_quarantine,
                    confirm_n=d.confirm_n, confirm_m=d.confirm_m, end_gap_s=d.end_gap_s, merge_s=d.merge_s,
                    shared_pre_buffer=pre_buffer, overlay_best_frame=True)

    @property
    def enabled(self) -> bool:
        return self.engine.enabled

    def _verdict(self, detector, result, frame: np.ndarray, ts: datetime, video_offset_s: Optional[float]) -> None:
        if self.record:
            self.verdicts.append((detector.name, ts, video_offset_s, result))
        file, sha = self._pose_weights if detector.name != "violence" else (None, None)
        self.pipelines[detector.name].feed_detection(
            frame, ts, detector.category if result.detected else None, result.score if result.detected else 0.0,
            result.boxes if result.detected else [], detector.detector_source, detector.model_name, detector.threshold,
            weights_file=file, weights_sha256=sha, video_offset_s=video_offset_s,
            signals=result.signals, experimental=True)

    def add_raw_frame(self, frame: np.ndarray, ts: datetime, video_offset_s: Optional[float] = None) -> None:
        for p in self.pipelines.values():
            p.add_raw_frame(frame, ts, video_offset_s)

    def process(self, frame: np.ndarray, t: float, ts: datetime, video_offset_s: Optional[float] = None) -> list:
        return self.engine.process(frame, t, ts, video_offset_s)

    def flush(self, ts: datetime) -> None:
        for p in self.pipelines.values():
            p.flush(ts)

    def join(self) -> None:
        for p in self.pipelines.values():
            p._encode_queue.join()

    def close(self) -> None:
        for p in self.pipelines.values():
            p.close()
