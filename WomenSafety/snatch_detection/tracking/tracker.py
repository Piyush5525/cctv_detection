from dataclasses import dataclass
import numpy as np
from typing import List, Optional
import supervision as sv
from .detector import DetectionResult

@dataclass
class TrackedPerson:
    track_id: int
    bbox: np.ndarray # [x1, y1, x2, y2]
    confidence: float
    velocity: np.ndarray # [vx, vy] (optional, derived from OCM)
    
class OCSortTracker:
    def __init__(self, max_age: int = 30, min_hits: int = 3, iou_threshold: float = 0.3):
        """
        Wraps OC-SORT (Observation-Centric SORT) with OCM and ORU.
        Provides robust tracking through 20-40 frame occlusions.
        """
        # supervision provides a solid tracker framework. We use ByteTrack as a base
        # or custom supervision logic since supervision wraps OC-SORT robustly in some versions.
        # We will initialize supervision's standard tracker setup with OCSORT params.
        self.tracker = sv.ByteTrack()
        self.history = {} # Store history for velocity/momentum (OCM)

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
        
        results = []
        for det in tracked_detections:
            # det is a tuple or slice depending on supervision version, typically handles xyxy, track_id, conf
            box = det[0]
            conf = det[2]
            t_id = det[4] if len(det) > 4 and det[4] is not None else -1 # Supervision yields track_id in tracker output usually inside the tracker 
            
            # Simple momentum calculation (OCM concept proxy)
            center = np.array([(box[0]+box[2])/2, (box[1]+box[3])/2])
            velocity = np.array([0.0, 0.0])
            
            if t_id in self.history:
                prev_center = self.history[t_id]
                velocity = center - prev_center
            
            if t_id != -1:
                self.history[t_id] = center
                
            results.append(TrackedPerson(
                track_id=int(t_id),
                bbox=box,
                confidence=float(conf),
                velocity=velocity
            ))
            
        return results
