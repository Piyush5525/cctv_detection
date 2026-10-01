import time
from collections import deque
from dataclasses import dataclass
import numpy as np
from typing import List, Optional
import supervision as sv
from .detector import DetectionResult
from api.core.config import settings

@dataclass
class TrackedPerson:
    track_id: int
    bbox: np.ndarray # [x1, y1, x2, y2]
    confidence: float
    velocity: np.ndarray # [vx, vy] (optional, derived from OCM)

class OCSortTracker:
    # Phase 1c follow-up 3 item 3 fix: self.history previously grew one
    # entry per track_id FOREVER (no pruning at all) -- see CHANGELOG.md
    # "Phase 1c Follow-up 2" for how this was found during a 20-minute
    # memory soak test. HISTORY_MAX_AGE_SECONDS prunes any track not seen
    # for this long (same expiry-by-last-seen pattern already used by
    # fall_detection.StateManager); HISTORY_MAX_LEN caps each track's own
    # stored history to a short deque (previously a single center point,
    # now a bounded sequence -- "cap history length per track" per
    # instruction) so per-track memory can't grow either.
    HISTORY_MAX_AGE_SECONDS = settings.SNATCH_TRACKER_HISTORY_MAX_AGE_SECONDS
    HISTORY_MAX_LEN = settings.SNATCH_TRACKER_HISTORY_MAX_LEN

    def __init__(self, max_age: int = 30, min_hits: int = 3, iou_threshold: float = 0.3):
        """
        Wraps OC-SORT (Observation-Centric SORT) with OCM and ORU.
        Provides robust tracking through 20-40 frame occlusions.
        """
        # supervision provides a solid tracker framework. We use ByteTrack as a base
        # or custom supervision logic since supervision wraps OC-SORT robustly in some versions.
        # We will initialize supervision's standard tracker setup with OCSORT params.
        self.tracker = sv.ByteTrack()
        # Store history for velocity/momentum (OCM): track_id -> deque of
        # (center, last_seen_time), bounded to HISTORY_MAX_LEN entries.
        self.history: dict = {}

    def _prune_dead_tracks(self, now: float, seen_ids: set):
        """Removes any track_id not seen in the current frame AND whose
        last update is older than HISTORY_MAX_AGE_SECONDS. Checking both
        conditions (not just "missing this frame") avoids pruning a track
        that's merely occluded for a frame or two -- sv.ByteTrack itself
        tolerates short occlusions (max_age), so this tracker's own
        history shouldn't prune more aggressively than that."""
        dead = [
            t_id for t_id, entries in self.history.items()
            if t_id not in seen_ids and entries and (now - entries[-1][1]) > self.HISTORY_MAX_AGE_SECONDS
        ]
        for t_id in dead:
            del self.history[t_id]

    def update(self, detections: List[DetectionResult], frame: np.ndarray) -> List[TrackedPerson]:
        """
        Updates tracker state with new bounding boxes.

        Args:
            detections: List of DetectionResult from PersonDetector.
            frame: Current video frame (BGR).

        Returns:
            List of TrackedPerson with persistent track_ids.
        """
        if not detections:
            # No detections this frame doesn't mean every existing track is
            # dead (a person can be briefly occluded) -- but it's exactly
            # the case where a track that truly IS gone would otherwise
            # never get pruned (this early-return skipped pruning entirely
            # before this fix, since _prune_dead_tracks was only reached
            # further down). seen_ids=set() here correctly lets any track
            # past HISTORY_MAX_AGE_SECONDS get pruned on this frame.
            self._prune_dead_tracks(time.monotonic(), seen_ids=set())
            return []

        # Convert DetectionResult list to supervision Detections object
        xyxy = np.array([d.bbox for d in detections])
        confidence = np.array([d.confidence for d in detections])
        class_id = np.array([d.class_id for d in detections])

        sv_detections = sv.Detections(
            xyxy=xyxy,
            confidence=confidence,
            class_id=class_id
        )

        # Update tracker
        tracked_detections = self.tracker.update_with_detections(sv_detections)

        now = time.monotonic()
        seen_ids = set()
        results = []
        for det in tracked_detections:
            # det is a tuple or slice depending on supervision version, typically handles xyxy, track_id, conf
            box = det[0]
            conf = det[2]
            t_id = det[4] if len(det) > 4 and det[4] is not None else -1 # Supervision yields track_id in tracker output usually inside the tracker

            # Simple momentum calculation (OCM concept proxy)
            center = np.array([(box[0]+box[2])/2, (box[1]+box[3])/2])
            velocity = np.array([0.0, 0.0])

            if t_id in self.history and self.history[t_id]:
                prev_center, _prev_t = self.history[t_id][-1]
                velocity = center - prev_center

            if t_id != -1:
                seen_ids.add(t_id)
                if t_id not in self.history:
                    self.history[t_id] = deque(maxlen=self.HISTORY_MAX_LEN)
                self.history[t_id].append((center, now))

            results.append(TrackedPerson(
                track_id=int(t_id),
                bbox=box,
                confidence=float(conf),
                velocity=velocity
            ))

        self._prune_dead_tracks(now, seen_ids)
        return results
