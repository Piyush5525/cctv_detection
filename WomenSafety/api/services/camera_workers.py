"""Latest-frame multi-camera workers for CCTV and demo phone streams."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2

from api.core.config import settings
from api.models.camera import all_cameras, get_camera, resolve_stream_source
from api.models.incident_v2 import SourceKind
from api.services import incident_service_v2 as incidents
from api.services.detector_interface import DetectorRegistry
from api.services.event_capture import EventCapturePipeline
from api.services.frame_sampler import RealtimeFrameGate


def _weights(name: str):
    path = Path(__file__).parent.parent.parent / "models" / name
    if not path.exists():
        return str(path), None
    import hashlib
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


class CameraWorker:
    def __init__(self, camera, registry: DetectorRegistry, detector_lock: threading.Lock):
        self.camera, self.registry, self.detector_lock = camera, registry, detector_lock
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._frame = self._annotated = None
        self.last_frame_at: Optional[float] = None
        self.status, self.error = "offline", None
        self.effective_fps, self.frames_read = 0.0, 0
        self.thread = threading.Thread(target=self._run, name=f"camera-{camera.camera_id}", daemon=True)
        self.gate = RealtimeFrameGate(settings.SAMPLE_INTERVAL_S, label=camera.camera_id)
        self.pipeline = EventCapturePipeline(camera.camera_id, self._incident_ready, self._quarantine)

    def start(self): self.thread.start()
    def stop(self):
        self._stop.set(); self.thread.join(timeout=3)

    def snapshot(self, annotated=True):
        with self._lock:
            frame = self._annotated if annotated else self._frame
            return None if frame is None else frame.copy()

    def detail(self):
        age = None if self.last_frame_at is None else round(time.time() - self.last_frame_at, 2)
        return {"camera_id": self.camera.camera_id, "camera_name": self.camera.display_name,
                "camera_type": self.camera.camera_type, "status": self.status, "last_frame_age_s": age,
                "effective_fps": round(self.gate.effective_fps, 2), "frames_read": self.frames_read, "error": self.error}

    def _incident_ready(self, camera_id, ev, evidence):
        incidents.handle_finished_event(camera_id, ev, evidence, source=SourceKind.LIVE)

    def _quarantine(self, *args): incidents.handle_encode_failure(*args)

    def _run(self):
        backoff = settings.CAMERA_RECONNECT_INITIAL_S
        while not self._stop.is_set():
            source = resolve_stream_source(self.camera)
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                self.status, self.error = "offline", "stream unreachable"
                self._stop.wait(backoff); backoff = min(backoff * 2, settings.CAMERA_RECONNECT_MAX_S); continue
            self.status, self.error, backoff = "online", None, settings.CAMERA_RECONNECT_INITIAL_S
            while not self._stop.is_set():
                ok, original = cap.read()
                if not ok:
                    self.status, self.error = "offline", "stream lost; reconnecting"
                    break
                now, ts = time.time(), datetime.now(timezone.utc)
                self.last_frame_at, self.frames_read = now, self.frames_read + 1
                self.pipeline.add_raw_frame(original, ts)
                annotated = original.copy()
                if self.gate.should_process(now):
                    detection = self._detect(original)
                    self.pipeline.feed_detection(original, ts, **detection)
                    for box in detection["boxes"]:
                        try:
                            x1, y1, x2, y2 = map(int, box["box"])
                            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(annotated, f"{box['label']} {box['confidence']:.2f}", (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 255), 2)
                        except Exception: pass
                with self._lock:
                    self._frame, self._annotated = original, annotated
            cap.release(); self._stop.wait(backoff); backoff = min(backoff * 2, settings.CAMERA_RECONNECT_MAX_S)

    def _detect(self, original):
        h, w = original.shape[:2]
        scale = min(1.0, settings.DETECT_MAX_WIDTH / w)
        frame = original if scale == 1 else cv2.resize(original, (int(w * scale), int(h * scale)))
        best = None
        with self.detector_lock:
            for detector in self.registry.all():
                result = detector.detect(frame)
                if result.detection and result.confidence >= settings.FIRE_CRASH_CONFIDENCE_FLOOR and (best is None or result.confidence > best[1].confidence):
                    best = (detector, result)
        if best is None:
            return {"category": None, "confidence": 0.0, "boxes": [], "detector_source": "none", "model_name": "none", "threshold_applied": settings.FIRE_CRASH_CONFIDENCE_FLOOR, "weights_file": None, "weights_sha256": None}
        detector, result = best
        category = "fire" if detector.name == "fire" else "crash"
        boxes = []
        for item in result.boxes:
            box = [round(float(v) / scale, 2) for v in item.get("box", (0, 0, 0, 0))]
            boxes.append({"label": item.get("class", category), "confidence": item.get("confidence", result.confidence), "box": box})
        file, sha = _weights("best_nano_111.pt" if detector.name == "fire" else "crash_best.pt")
        return {"category": category, "confidence": result.confidence, "boxes": boxes, "detector_source": f"yolov8-{detector.name}", "model_name": Path(file).name, "threshold_applied": detector.threshold, "weights_file": file, "weights_sha256": sha}


class CameraWorkerManager:
    def __init__(self): self.workers = {}; self.registry = None; self.detector_lock = threading.Lock()
    def start(self):
        if not settings.LIVE_CAMERA_WORKERS_ENABLED or self.workers: return
        self.registry = DetectorRegistry(confidence_floor=settings.FIRE_CRASH_CONFIDENCE_FLOOR)
        for camera in all_cameras():
            if camera.enabled:
                worker = CameraWorker(camera, self.registry, self.detector_lock); self.workers[camera.camera_id] = worker; worker.start()
    def stop(self):
        for worker in list(self.workers.values()): worker.stop()
        self.workers.clear()
    def status(self): return {"cameras": [worker.detail() for worker in self.workers.values()]}
    def frame(self, camera_id):
        worker = self.workers.get(camera_id)
        return worker.snapshot() if worker else None


camera_workers = CameraWorkerManager()
