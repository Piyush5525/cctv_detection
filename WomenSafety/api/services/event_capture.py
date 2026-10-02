"""Shared event-lifecycle and evidence-capture pipeline, used by BOTH
main.py's live camera loop and the test-replay path (CHANGELOG.md "CCTV
Incident Capture Pipeline" phase, Part 3). One place defines: the rolling
pre/post-event frame buffer, temporal confirmation (N of M), event
start/extend/end/merge rules, and turning a finished event into saved
evidence files (best frame + thumbnail + annotated frame + ffmpeg clip).

Capture and encoding run on a background thread per camera (via
EventCapturePipeline.feed_frame being cheap and _finish_event/_encode_clip
being dispatched to a worker thread) so a slow ffmpeg encode never blocks
the detection loop's frame rate.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Full
from typing import Callable, Deque, Optional

import cv2
import numpy as np

from api.core.config import settings

EVIDENCE_ROOT: Path = settings.EVIDENCE_ROOT_V2
THUMBNAIL_WIDTH: int = settings.THUMBNAIL_WIDTH

# Ring-buffer/active-event memory fix (Phase 1c hardening item 2): a raw
# BGR frame at 1080p is ~5.9MB; an 8s pre-buffer at 25fps alone would be
# ~1.2GB PER CAMERA, and a 120s max-length event ~20GB. Frames are now
# stored JPEG-encoded instead of raw, cutting that by roughly 20-40x
# (see CHANGELOG.md "Phase 1c Hardening" for the measured before/after
# numbers) at the cost of decode time when a frame is actually used
# (best-frame selection, clip re-encoding) -- decode only happens for the
# handful of frames actually needed, never for the whole buffer at once.
# Phase 1c follow-ups item 2: made configurable (was hardcoded 85),
# default raised to 90 -- see CHANGELOG.md for the measured compress-time/
# FPS/CPU overhead and PSNR/SSIM quality comparison that justified keeping
# the default this high rather than trading more quality for speed.
JPEG_QUALITY = settings.JPEG_QUALITY


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


FFMPEG_TIMEOUT_S = 30  # Phase 1c hardening item 4: a hung ffmpeg must not hang the encoder thread forever


class EvidenceBuildError(RuntimeError):
    """Raised when clip encoding fails (missing ffmpeg, non-zero exit,
    or timeout) AFTER the best-frame/annotated/thumbnail images were
    already written successfully. Carries the best-frame path (and
    whatever else was built) so the caller can quarantine the incident
    while still keeping that evidence on disk and referencing it in the
    quarantine reason, rather than losing track of it."""
    def __init__(self, message: str, partial_evidence: dict):
        super().__init__(message)
        self.partial_evidence = partial_evidence


def _encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("cv2.imencode failed to JPEG-encode a frame")
    return buf.tobytes()


def _decode_jpeg(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("cv2.imdecode failed to decode a stored frame")
    return frame


@dataclass
class FrameSample:
    """`frame` is JPEG-encoded bytes, not a raw ndarray -- see the memory
    note above. Use `.decode()` to get the ndarray back when actually
    needed (never for a whole buffer/event's worth of frames at once).

    `video_offset_s` is only meaningful in test_replay mode (Phase 1c
    hardening item 3): the source video's own elapsed seconds
    (frame_index / source_fps) at capture time, as opposed to
    `timestamp` which is always a real wall-clock moment regardless of
    mode. None in live mode, where there is no "source video" to be
    offset from."""
    frame: bytes
    timestamp: datetime
    confidence: float
    boxes: list  # [{label, conf, box}]
    video_offset_s: Optional[float] = None
    best: bool = False  # scripted demo events only: the frame chosen as the best frame (no score exists)

    @staticmethod
    def from_ndarray(frame: np.ndarray, timestamp: datetime, confidence: float, boxes: list,
                      video_offset_s: Optional[float] = None, best: bool = False) -> "FrameSample":
        return FrameSample(_encode_jpeg(frame), timestamp, confidence, boxes, video_offset_s, best)

    def decode(self) -> np.ndarray:
        return _decode_jpeg(self.frame)


@dataclass
class ActiveEvent:
    category: str
    event_start: datetime
    last_detection_at: datetime
    frames: list = field(default_factory=list)  # FrameSample, includes pre-buffer + event + post window
    confirmations: str = ""  # "N of M" snapshot at confirmation time
    detector_source: str = ""
    model_name: str = ""
    weights_file: Optional[str] = None
    weights_sha256: Optional[str] = None
    threshold_applied: float = 0.0
    # Action detectors (fall/violence/snatch): the signals that fired on the peak-score frame (plain numbers only,
    # never keypoints), the peak score so far, and the experimental flag. Fire/crash leave these at the defaults.
    signals: dict = field(default_factory=dict)
    peak_score: float = 0.0
    experimental: bool = False
    scripted: bool = False   # demo script, not a detector: no score, no threshold, best frame chosen by the script


# COCO skeleton for the best-frame overlay (drawn into an image only; keypoints are never persisted as data).
SKELETON_EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


def _draw_overlay(img: np.ndarray, boxes: list) -> None:
    for b in boxes:
        try:
            x1, y1, x2, y2 = [int(v) for v in b["box"]]
            if not b.get("skeleton_only"):
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(img, f"{b['label']} {b['confidence']:.2f}" if "confidence" in b else b["label"],
                            (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            kp = b.get("keypoints")
            if kp:
                for a, c in SKELETON_EDGES:
                    if kp[a][2] >= 0.3 and kp[c][2] >= 0.3:
                        cv2.line(img, (int(kp[a][0]), int(kp[a][1])), (int(kp[c][0]), int(kp[c][1])), (0, 255, 255), 2)
                for x, y, c in kp:
                    if c >= 0.3:
                        cv2.circle(img, (int(x), int(y)), 3, (0, 200, 0), -1)
        except Exception:
            continue


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RingBuffer:
    """Rolling pre-event buffer of (JPEG-encoded frame bytes, timestamp),
    bounded by wall-clock seconds rather than frame count, so it stays
    correct regardless of the camera's actual FPS. Stores JPEG bytes, not
    raw ndarrays -- see the memory note above FrameSample."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._buf: Deque[tuple] = deque()
        self._lock = threading.Lock()

    def add(self, frame: np.ndarray, ts: datetime):
        encoded = _encode_jpeg(frame)
        with self._lock:
            self._buf.append((encoded, ts))
            cutoff = ts.timestamp() - self.seconds
            while self._buf and self._buf[0][1].timestamp() < cutoff:
                self._buf.popleft()

    def snapshot(self) -> list:
        with self._lock:
            return list(self._buf)


class EventCapturePipeline:
    """One instance per camera. Feed it every sampled frame plus that
    frame's detector verdict (class name or None, confidence, boxes); it
    handles temporal confirmation, event lifecycle, and dispatches
    finished events to a background encoder thread.

    on_incident_ready(camera_id, ActiveEvent, evidence_dict) is called
    from the background encoder thread once evidence files are written.
    on_quarantine(camera_id, category, reason, event_start, partial_evidence)
    is called if an event can't produce valid evidence (e.g. ffmpeg
    missing/failed/timed out) -- partial_evidence is the dict of
    best-frame/annotated/thumbnail paths that WERE written successfully
    before the failure, or None if nothing was built at all (e.g. no
    confirmed-detection frames to pick a best frame from in the first
    place).
    """

    def __init__(
        self,
        camera_id: str,
        on_incident_ready: Callable[[str, ActiveEvent, dict], None],
        on_quarantine: Optional[Callable[[str, str, str, Optional[datetime], Optional[dict]], None]] = None,
        *,
        confirm_n: Optional[int] = None,
        confirm_m: Optional[int] = None,
        end_gap_s: Optional[float] = None,
        merge_s: Optional[float] = None,
        shared_pre_buffer: Optional[RingBuffer] = None,
        overlay_best_frame: bool = False,
    ):
        """The keyword-only arguments exist for the action detectors (one pipeline per detector per camera):
        per-detector confirmation/end/merge settings, a ring buffer shared with the camera's main pipeline (whose
        owner keeps filling it -- this pipeline then never adds to it), and best_frame.jpg carrying the box/skeleton
        overlay. Left at their defaults, behaviour is exactly the original (fire/crash)."""
        self.camera_id = camera_id
        self.on_incident_ready = on_incident_ready
        self.on_quarantine = on_quarantine
        self.confirm_n = settings.EVENT_CONFIRM_N if confirm_n is None else confirm_n
        self.confirm_m = settings.EVENT_CONFIRM_M if confirm_m is None else confirm_m
        self.end_gap_s = settings.EVENT_END_GAP_SECONDS if end_gap_s is None else end_gap_s
        self.merge_s = settings.EVENT_MERGE_SECONDS if merge_s is None else merge_s
        self.overlay_best_frame = overlay_best_frame

        self._owns_buffer = shared_pre_buffer is None
        self.pre_buffer = shared_pre_buffer or RingBuffer(settings.PRE_EVENT_SECONDS)
        self._recent_verdicts: Deque[tuple] = deque(maxlen=self.confirm_m)  # (is_hit, confidence, boxes, category)
        self._active: Optional[ActiveEvent] = None
        self._last_ended: dict[str, datetime] = {}  # category -> event_end, for merge-window check
        self._post_window_until: Optional[datetime] = None
        self._last_raw_sample: Optional[FrameSample] = None  # most recent add_raw_frame() entry, updated in place by feed_detection() if sampled
        self._lock = threading.Lock()

        self._encode_queue: Queue = Queue(maxsize=settings.MAX_ENCODE_QUEUE_SIZE)
        self._encoder_thread = threading.Thread(target=self._encoder_loop, daemon=True)
        self._encoder_thread.start()

        # FPS/encode-time logging (Part 3.5)
        self._frame_count = 0
        self._fps_window_start = time.time()
        self.last_logged_fps: float = 0.0
        self.last_encode_time_s: float = 0.0

    def add_raw_frame(self, frame: np.ndarray, ts: datetime, video_offset_s: Optional[float] = None, best: bool = False,
                      best_boxes: Optional[list] = None):
        """Call on EVERY frame the camera produces, regardless of the
        detection sampling interval (sampling frame-sampler unification):
        keeps the pre-event ring buffer, and an already-active event's
        frame list, filled with every real frame for clip quality/
        smoothness -- only DETECTION is throttled to sampled frames (see
        feed_detection). Every raw frame is appended with confidence=0/
        no boxes (meaning "not evaluated for detection" -- not "no
        detection"); when this SAME frame is also a sampled one,
        feed_detection() (called right after, by every caller of this
        pipeline) updates that exact list entry in place with the real
        detector verdict, rather than appending a second, duplicate
        entry for one real frame."""
        if self._owns_buffer:
            self.pre_buffer.add(frame, ts)
        with self._lock:
            if self._active is not None:
                sample = FrameSample.from_ndarray(frame, ts, 0.0, best_boxes or [], video_offset_s, best)
                self._active.frames.append(sample)
                self._last_raw_sample = sample  # feed_detection() may update this in place if sampled

    def feed_detection(
        self,
        frame: np.ndarray,
        ts: datetime,
        category: Optional[str],
        confidence: float,
        boxes: list,
        detector_source: str,
        model_name: str,
        threshold_applied: float,
        weights_file: Optional[str] = None,
        weights_sha256: Optional[str] = None,
        video_offset_s: Optional[float] = None,
        signals: Optional[dict] = None,
        experimental: bool = False,
    ):
        """Call once per SAMPLED frame only (see api/services/frame_sampler.py),
        always AFTER add_raw_frame() for that same frame -- this is
        where confirmation counting and the event lifecycle (start/
        extend/end/merge) actually happen. category=None/confidence=0
        means "no detection this sampled frame" for whatever class is
        being tracked.

        video_offset_s (Phase 1c hardening item 3): pass this in
        test_replay mode as frame_index / source_fps -- the source
        video's own elapsed time at this sampled frame, independent of
        wall-clock `ts`. Left None in live mode (main.py)."""
        self._frame_count += 1
        now = time.time()
        if now - self._fps_window_start >= 5.0:
            self.last_logged_fps = self._frame_count / (now - self._fps_window_start)
            print(f"[EventCapture:{self.camera_id}] detection FPS (sampled) over last {now - self._fps_window_start:.1f}s: {self.last_logged_fps:.2f}")
            self._frame_count = 0
            self._fps_window_start = now

        with self._lock:
            is_hit = category is not None
            self._recent_verdicts.append((is_hit, confidence, boxes, category))

            if self._active is None:
                if is_hit and self._confirmed(category):
                    # NOTE on "merge": the previous ActiveEvent for this
                    # category (if any, within EVENT_MERGE_SECONDS) was
                    # already finalized and handed to the encoder queue
                    # by _end_event -- there is no live object to resume.
                    # _try_merge()'s only real effect is therefore
                    # informational/logging today (see _start_event's log
                    # line); a genuinely separate incident is created
                    # either way. Fusing two already-encoded incidents
                    # back together after the fact (e.g. at the API/UI
                    # layer, linking them as one logical event) would be
                    # a different, larger feature than this pipeline's
                    # per-event capture/evidence job -- not implemented.
                    self._try_merge(category, ts)
                    self._start_event(category, ts, frame, confidence, boxes,
                                       detector_source, model_name, threshold_applied,
                                       weights_file, weights_sha256, video_offset_s)
                    self._active.experimental = experimental
                    self._active.signals = dict(signals or {})
                    self._active.peak_score = confidence
                return

            # An active event is running. If this sampled frame was the
            # one add_raw_frame() just appended (the normal case -- every
            # caller calls add_raw_frame() then feed_detection() for the
            # same frame in the same iteration), update that entry in
            # place with the real detection verdict instead of appending
            # a duplicate. If somehow no such entry exists (defensive;
            # shouldn't happen given the calling convention above), fall
            # back to appending one.
            if self._last_raw_sample is not None and self._last_raw_sample in self._active.frames:
                self._last_raw_sample.confidence = confidence if (category == self._active.category and is_hit) else 0.0
                self._last_raw_sample.boxes = boxes if (category == self._active.category and is_hit) else []
            else:
                self._active.frames.append(FrameSample.from_ndarray(
                    frame, ts, confidence if is_hit else 0.0, boxes if is_hit else [], video_offset_s))

            if category == self._active.category and is_hit:
                self._active.last_detection_at = ts
                if confidence > self._active.peak_score:
                    self._active.peak_score = confidence
                    self._active.signals = dict(signals or {})

            gap = (ts - self._active.last_detection_at).total_seconds()
            duration = (ts - self._active.event_start).total_seconds()
            if gap >= self.end_gap_s or duration >= settings.MAX_EVENT_SECONDS:
                self._end_event(ts)

    def _confirmed(self, category: str) -> bool:
        hits = sum(1 for is_hit, _, _, c in self._recent_verdicts if is_hit and c == category)
        return hits >= self.confirm_n

    def _try_merge(self, category: str, ts: datetime) -> bool:
        last_end = self._last_ended.get(category)
        return last_end is not None and (ts - last_end).total_seconds() <= self.merge_s

    def _start_event(self, category, ts, frame, confidence, boxes, detector_source, model_name,
                      threshold_applied, weights_file, weights_sha256, video_offset_s=None):
        n = sum(1 for is_hit, _, _, c in self._recent_verdicts if is_hit and c == category)
        m = len(self._recent_verdicts)
        # pre_buffer.snapshot() already returns JPEG-encoded bytes (RingBuffer
        # encodes on add()), so these FrameSamples are built directly, not
        # via from_ndarray() -- only the current raw `frame` needs encoding.
        # Pre-buffer frames have no video_offset_s recorded (the ring buffer
        # doesn't track it) -- only frames from event_start onward do, which
        # is sufficient to compute video_offset_start_s (see _build_evidence).
        pre_frames = [FrameSample(f, t, 0.0, []) for f, t in self.pre_buffer.snapshot() if t < ts]
        self._active = ActiveEvent(
            category=category,
            event_start=ts,
            last_detection_at=ts,
            frames=pre_frames + [FrameSample.from_ndarray(frame, ts, confidence, boxes, video_offset_s)],
            confirmations=f"{n} of {m}",
            detector_source=detector_source,
            model_name=model_name,
            weights_file=weights_file,
            weights_sha256=weights_sha256,
            threshold_applied=threshold_applied,
        )
        print(f"[EventCapture:{self.camera_id}] EVENT START category={category} at {ts.isoformat()} "
              f"(confirmed {n} of {m})" + (f" video_offset_s={video_offset_s:.2f}" if video_offset_s is not None else ""))

    def start_scripted_event(self, category: str, ts: datetime, frame: np.ndarray, video_offset_s: Optional[float] = None,
                             best: bool = False, best_boxes: Optional[list] = None) -> None:
        """Scripted demo incident (api/services/demo_trigger.py): opens an event WITHOUT any detector verdict. Same ring
        buffer pre-event frames, same encoder and evidence writer as every other event; no confirmation counting, no
        score, no threshold. Frames after this one come from add_raw_frame(); finish with finish_scripted_event()."""
        with self._lock:
            pre_frames = [FrameSample(f, t, 0.0, []) for f, t in self.pre_buffer.snapshot() if t < ts]
            self._active = ActiveEvent(
                category=category, event_start=ts, last_detection_at=ts, confirmations="scripted", detector_source="scripted_demo",
                model_name="scripted_demo", experimental=True, scripted=True,
                frames=pre_frames + [FrameSample.from_ndarray(frame, ts, 0.0, best_boxes or [], video_offset_s, best)])
        print(f"[EventCapture:{self.camera_id}] SCRIPTED EVENT START category={category} at {ts.isoformat()}")

    def finish_scripted_event(self, end_ts: datetime) -> None:
        with self._lock:
            if self._active is not None:
                self._active.last_detection_at = end_ts
                self._end_event(end_ts)

    def _end_event(self, ts: datetime):
        ev = self._active
        self._active = None
        self._last_ended[ev.category] = ev.last_detection_at
        duration = (ev.last_detection_at - ev.event_start).total_seconds()
        print(f"[EventCapture:{self.camera_id}] EVENT END category={ev.category} "
              f"duration={duration:.1f}s frames={len(ev.frames)}")
        try:
            # Non-blocking: if the encoder can't keep up and the bounded
            # queue (MAX_ENCODE_QUEUE_SIZE) is full, this event is
            # quarantined immediately rather than blocking the detection
            # thread waiting for queue space (which would drop detection
            # FPS -- the one thing this whole pipeline must not do).
            self._encode_queue.put_nowait(ev)
        except Full:
            reason = (f"encode queue full (>= {settings.MAX_ENCODE_QUEUE_SIZE} pending) -- "
                      f"encoder cannot keep up with event rate, dropping this event's evidence build")
            print(f"[EventCapture:{self.camera_id}] {reason}")
            if self.on_quarantine:
                self.on_quarantine(self.camera_id, ev.category, reason, ev.event_start, None)

    def flush(self, ts: datetime):
        """Force-close an active event (e.g. end of a replay file)."""
        with self._lock:
            if self._active is not None:
                self._end_event(ts)

    def close(self):
        """Stops the encoder thread once everything queued so far has been built (replays create short-lived
        pipelines; this keeps them from leaking one idle thread each). The live pipelines never call it."""
        self._encode_queue.put(None)

    def _encoder_loop(self):
        while True:
            ev: ActiveEvent = self._encode_queue.get()
            if ev is None:
                self._encode_queue.task_done()
                return
            t0 = time.time()
            try:
                evidence = self._build_evidence(ev)
                self.last_encode_time_s = time.time() - t0
                print(f"[EventCapture:{self.camera_id}] encoded evidence for event starting "
                      f"{ev.event_start.isoformat()} in {self.last_encode_time_s:.2f}s")
                self.on_incident_ready(self.camera_id, ev, evidence)
            except EvidenceBuildError as e:
                # Clip encoding failed, but best_frame/annotated/thumbnail
                # were already written successfully -- keep them, and put
                # their real paths in the quarantine record (not just
                # buried in a message string) so an operator can still
                # review the incident visually even without a clip.
                print(f"[EventCapture:{self.camera_id}] FAILED to encode clip (best-frame evidence kept): {e}")
                if self.on_quarantine:
                    self.on_quarantine(self.camera_id, ev.category, str(e), ev.event_start, e.partial_evidence)
            except Exception as e:
                print(f"[EventCapture:{self.camera_id}] FAILED to build evidence: {e}")
                if self.on_quarantine:
                    self.on_quarantine(self.camera_id, ev.category, str(e), ev.event_start, None)
            finally:
                self._encode_queue.task_done()

    def _build_evidence(self, ev: ActiveEvent) -> dict:
        """Builds best_frame/annotated/thumbnail first (image-only, no
        ffmpeg dependency, effectively always succeeds if we get this
        far), THEN attempts clip encoding. Phase 1c hardening item 4: if
        ffmpeg is missing, times out, or exits non-zero, raises
        EvidenceBuildError carrying the already-written best-frame
        evidence -- the caller quarantines the incident but the
        best-frame files stay on disk and their paths are in the
        quarantine reason, not silently orphaned."""
        if ev.scripted:
            hit_frames = [fs for fs in ev.frames if fs.best]       # the script's chosen best frame; no detector score exists
            if not hit_frames:
                raise RuntimeError("scripted event has no best frame")
            best = hit_frames[0]
        else:
            hit_frames = [fs for fs in ev.frames if fs.confidence > 0]
            if not hit_frames:
                raise RuntimeError("event had no confirmed-detection frames to pick a best frame from")
            best = max(hit_frames, key=lambda fs: fs.confidence)

        # This incident_id is also used as the real Incident.incident_id
        # (see incident_service_v2.handle_finished_event, which is passed
        # it via evidence["incident_id"]) -- generated here, once, so the
        # evidence folder name and the incident's own id are the same
        # value rather than two independently-random UUIDs.
        incident_id = str(uuid.uuid4())
        day_dir = EVIDENCE_ROOT / self.camera_id / ev.event_start.strftime("%Y-%m-%d") / incident_id
        day_dir.mkdir(parents=True, exist_ok=True)

        best_decoded = best.decode()

        best_frame_path = day_dir / "best_frame.jpg"
        annotated = best_decoded.copy()
        _draw_overlay(annotated, best.boxes)
        annotated_path = day_dir / "annotated_frame.jpg"
        if ev.scripted and not best.boxes:
            annotated_path = None          # nothing real to draw: no annotated frame, no overlay of any kind
        else:
            cv2.imwrite(str(annotated_path), annotated)
        if self.overlay_best_frame:
            # Action detectors: the peak-score frame WITH the box/skeleton overlay is the best frame
            # (it is what Telegram and the dashboard show first).
            best_frame_path.write_bytes(_encode_jpeg(annotated))
        else:
            # best.frame is already JPEG bytes at JPEG_QUALITY -- write it
            # directly rather than decode+re-encode (avoids a second lossy
            # generation loss on the one frame that matters most).
            best_frame_path.write_bytes(best.frame)

        h, w = best_decoded.shape[:2]
        thumb_w = THUMBNAIL_WIDTH
        thumb_h = max(1, int(h * (thumb_w / w)))
        thumb = cv2.resize(best_decoded, (thumb_w, thumb_h))
        thumb_path = day_dir / "thumbnail.jpg"
        cv2.imwrite(str(thumb_path), thumb)

        # Phase 1c hardening item 3: video-relative offsets, only ever
        # populated in test_replay mode (feed_frame's video_offset_s is
        # None in live mode, so these stay None too -- there is no
        # "source video" a live incident could be relative to).
        offsets = [fs.video_offset_s for fs in ev.frames if fs.video_offset_s is not None]
        video_offset_start_s = min(offsets) if offsets else None
        video_offset_end_s = max(offsets) if offsets else None

        partial_evidence = {
            "incident_id": incident_id,
            "best_frame_path": str(best_frame_path),
            "annotated_frame_path": str(annotated_path) if annotated_path else None,
            "thumbnail_path": str(thumb_path),
            "sha256_frame": _sha256_file(best_frame_path),
            "best": best,
            "hit_frames": hit_frames,
            "video_offset_start_s": video_offset_start_s,
            "video_offset_end_s": video_offset_end_s,
        }

        if not ffmpeg_available():
            raise EvidenceBuildError(
                f"ffmpeg is not installed/on PATH -- best-frame evidence kept at {best_frame_path}, "
                f"no clip produced (no silent fallback to an unplayable format)",
                partial_evidence,
            )

        raw_clip_path = day_dir / "_raw.mp4"
        est_fps = self._estimate_fps(ev.frames)
        out = cv2.VideoWriter(str(raw_clip_path), cv2.VideoWriter_fourcc(*"mp4v"), est_fps, (w, h))
        for fs in ev.frames:
            frame = fs.decode()
            if frame.shape[:2] != (h, w):
                frame = cv2.resize(frame, (w, h))
            out.write(frame)
        out.release()

        clip_path = day_dir / "clip.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", str(raw_clip_path),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(clip_path),
                ],
                check=True,
                capture_output=True,
                timeout=FFMPEG_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise EvidenceBuildError(
                f"ffmpeg timed out after {FFMPEG_TIMEOUT_S}s -- best-frame evidence kept at {best_frame_path}, "
                f"no clip produced", partial_evidence,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace")[:500] if e.stderr else ""
            raise EvidenceBuildError(
                f"ffmpeg exited {e.returncode} -- best-frame evidence kept at {best_frame_path}, "
                f"no clip produced. stderr: {stderr}", partial_evidence,
            )
        finally:
            raw_clip_path.unlink(missing_ok=True)

        return {
            **partial_evidence,
            "clip_path": str(clip_path),
            "clip_duration_s": round(len(ev.frames) / est_fps, 2),
            "width": w,
            "height": h,
            "fps": est_fps,
            "sha256_clip": _sha256_file(clip_path),
        }

    @staticmethod
    def _estimate_fps(frames: list) -> float:
        if len(frames) < 2:
            return 10.0
        span = (frames[-1].timestamp - frames[0].timestamp).total_seconds()
        if span <= 0:
            return 10.0
        return max(1.0, round(len(frames) / span, 2))
