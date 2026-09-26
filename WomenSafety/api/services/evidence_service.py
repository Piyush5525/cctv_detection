import os
import cv2
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Deque
from collections import deque
from pathlib import Path
import uuid
import threading
import time

from api.core.config import settings


class FrameBuffer:
    def __init__(self, max_seconds: int = 60, fps: float = 10.0):
        self.max_frames = int(max_seconds * fps)
        self.fps = fps
        self.buffer: Deque[tuple] = deque(maxlen=self.max_frames)
        self.lock = threading.Lock()
        # Track actual fps from real frame timestamps
        self._fps_samples: Deque[float] = deque(maxlen=30)
        self._last_ts: Optional[datetime] = None

    def add_frame(self, frame: np.ndarray, timestamp: datetime):
        with self.lock:
            if self._last_ts is not None:
                diff = (timestamp - self._last_ts).total_seconds()
                if 0 < diff < 2.0:  # ignore gaps from pauses
                    self._fps_samples.append(1.0 / diff)
            self._last_ts = timestamp
            self.buffer.append((frame.copy(), timestamp))

    @property
    def actual_fps(self) -> float:
        if len(self._fps_samples) < 3:
            return self.fps
        return sum(self._fps_samples) / len(self._fps_samples)

    def get_clip_frames(self, start_time: datetime, end_time: datetime) -> List[np.ndarray]:
        with self.lock:
            frames = []
            for frame, ts in self.buffer:
                if start_time <= ts <= end_time:
                    frames.append(frame)
            return frames

    def get_last_n_seconds(self, seconds: float) -> List[np.ndarray]:
        with self.lock:
            if not self.buffer:
                return []
            cutoff = self.buffer[-1][1] - timedelta(seconds=seconds)
            frames = [f for f, ts in self.buffer if ts >= cutoff]
            return frames


class EvidenceService:
    def __init__(self):
        self.buffers: dict[str, FrameBuffer] = {}
        self.clips_dir = settings.EVIDENCE_CLIPS_DIR
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def get_or_create_buffer(self, camera_id: str, fps: float = 10.0) -> FrameBuffer:
        with self._lock:
            if camera_id not in self.buffers:
                self.buffers[camera_id] = FrameBuffer(max_seconds=60, fps=fps)
            return self.buffers[camera_id]

    def add_frame(self, camera_id: str, frame: np.ndarray, timestamp: datetime = None, fps: float = 30.0):
        if timestamp is None:
            timestamp = datetime.utcnow()
        buffer = self.get_or_create_buffer(camera_id, fps)
        buffer.add_frame(frame, timestamp)

    def save_evidence_clip(
        self,
        camera_id: str,
        incident_timestamp: datetime,
        incident_id: str,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0
    ) -> Optional[dict]:
        buffer = self.buffers.get(camera_id)
        if not buffer:
            return None

        start_time = incident_timestamp - timedelta(seconds=pre_seconds)
        end_time = incident_timestamp + timedelta(seconds=post_seconds)

        frames = buffer.get_clip_frames(start_time, end_time)
        if not frames:
            return None

        write_fps = max(1.0, buffer.actual_fps)  # use measured fps for correct playback speed
        clip_filename = f"{incident_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4"
        clip_path = self.clips_dir / clip_filename

        height, width = frames[0].shape[:2]
        # Try codecs in order of browser compatibility
        for fourcc_str in ('avc1', 'H264', 'mp4v', 'XVID'):
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            out = cv2.VideoWriter(str(clip_path), fourcc, write_fps, (width, height))
            if out.isOpened():
                break
            out.release()

        for frame in frames:
            out.write(frame)
        out.release()

        thumb_filename = f"{incident_id}_thumb.jpg"
        thumb_path = self.clips_dir / thumb_filename
        mid_frame = frames[len(frames) // 2]
        cv2.imwrite(str(thumb_path), mid_frame)

        return {
            "video_path": str(clip_path),
            "thumbnail_path": str(thumb_path),
            "duration": len(frames) / buffer.fps,
            "start_time": start_time,
            "end_time": end_time
        }

    def list_clips(self) -> List[dict]:
        clips = []
        for f in self.clips_dir.glob("*.mp4"):
            stat = f.stat()
            clips.append({
                "filename": f.name,
                "path": str(f),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
            })
        return sorted(clips, key=lambda x: x["created"], reverse=True)

    def get_clip_path(self, filename: str) -> Optional[Path]:
        path = self.clips_dir / filename
        if path.exists():
            return path
        return None


evidence_service = EvidenceService()