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
        out = None
        for fourcc_str in ('avc1', 'H264', 'mp4v', 'XVID'):
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            candidate = cv2.VideoWriter(str(clip_path), fourcc, write_fps, (width, height))
            if candidate.isOpened():
                out = candidate
                break
            candidate.release()

        if out is None:
            print(f"[Evidence] No usable video codec for {clip_filename}, skipping clip")
            return None

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
        """Lists saved evidence videos with their real thumbnail filename.
        Video names vary by how they were created -- a live-camera clip is
        "{incident_id}_{timestamp}.mp4" (save_evidence_clip) and an uploaded
        video is "{incident_id}_upload.mp4" (save_uploaded_media) -- but the
        thumbnail is always "{incident_id}_thumb.jpg" either way, so we
        can't derive it by string-trimming the video filename (a prior
        version of the frontend tried exactly that and got a filename that
        never existed). Report the actual thumbnail name only when that
        file is really on disk."""
        clips = []
        for f in self.clips_dir.glob("*.mp4"):
            stat = f.stat()
            incident_id = f.stem
            if incident_id.endswith("_upload"):
                incident_id = incident_id[: -len("_upload")]
            else:
                # live-camera clips: "{incident_id}_{YYYYMMDD_HHMMSS}"
                parts = incident_id.rsplit("_", 2)
                if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                    incident_id = parts[0]

            thumb_name = f"{incident_id}_thumb.jpg"
            has_thumb = (self.clips_dir / thumb_name).exists()

            clips.append({
                "filename": f.name,
                "path": str(f),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "thumbnail_filename": thumb_name if has_thumb else None,
            })
        return sorted(clips, key=lambda x: x["created"], reverse=True)

    def get_clip_path(self, filename: str) -> Optional[Path]:
        path = self.clips_dir / filename
        if path.exists():
            return path
        return None

    def save_uploaded_media(
        self,
        incident_id: str,
        frame: np.ndarray,
        raw_video_bytes: Optional[bytes] = None,
    ) -> dict:
        """Save evidence for an uploaded photo/video (as opposed to a clip cut
        from a live camera's rolling buffer): the detected frame always
        becomes the thumbnail, and if the upload was a video, the original
        file bytes are stored as-is so the operator can review the full
        source clip, not just the one frame that triggered detection."""
        thumb_filename = f"{incident_id}_thumb.jpg"
        thumb_path = self.clips_dir / thumb_filename
        cv2.imwrite(str(thumb_path), frame)

        video_path = None
        if raw_video_bytes is not None:
            video_filename = f"{incident_id}_upload.mp4"
            video_path = self.clips_dir / video_filename
            video_path.write_bytes(raw_video_bytes)

        return {
            "video_path": str(video_path) if video_path else None,
            "thumbnail_path": str(thumb_path),
        }


evidence_service = EvidenceService()