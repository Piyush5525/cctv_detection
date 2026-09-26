from dataclasses import dataclass
import numpy as np
from typing import List, Tuple
from ultralytics import YOLO

@dataclass
class DetectionResult:
    bbox: np.ndarray # [x1, y1, x2, y2]
    confidence: float
    class_id: int

class PersonDetector:
    def __init__(self, model_path: str = 'yolov8n.pt', conf_thresh: float = 0.5):
        """
        Initializes the YOLOv8 person detector.
        Optionally load a model fine-tuned on CrowdHuman.
        """
        self.model = YOLO(model_path)
        self.conf_thresh = conf_thresh

    def detect(self, frame: np.ndarray) -> List[DetectionResult]:
        """
        Detects persons in a given frame.

        Args:
            frame: OpenCV image frame (BGR).

        Returns:
            List of DetectionResult containing bounding boxes and confidences for persons.
        """
        results = self.model(frame, verbose=False, classes=[0], conf=self.conf_thresh)
        detections = []
        
        for result in results:
            boxes = result.boxes
            for box in boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                conf = box.conf[0].cpu().item()
                cls = int(box.cls[0].cpu().item())
                
                if cls == 0: # person class
                    detections.append(DetectionResult(
                        bbox=xyxy,
                        confidence=conf,
                        class_id=cls
                    ))
                    
        return detections
