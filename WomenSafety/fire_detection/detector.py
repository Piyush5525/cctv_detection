import os
import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, NamedTuple
from ultralytics import YOLO


class FireDetectionResult(NamedTuple):
    detection: Optional[str]
    confidence: float
    boxes: list


class FireDetector:
    def __init__(
        self,
        model_path: Path,
        target_height: int = 640,
        iou_threshold: float = 0.2,
        min_confidence: float = 0.5,
        smoke_confidence: float = 0.75
    ):
        self.model = YOLO(str(model_path))
        self.target_height = target_height
        self.iou_threshold = iou_threshold
        self.min_confidence = min_confidence
        self.smoke_confidence = smoke_confidence
        self.names = self.model.model.names

        self.colors = {
            "fire": (0, 0, 255),
            "smoke": (128, 128, 128)
        }

    def resize_frame(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        aspect_ratio = width / height
        new_width = int(self.target_height * aspect_ratio)
        return cv2.resize(frame, (new_width, self.target_height))

    def draw_detection(
        self,
        frame: np.ndarray,
        box: np.ndarray,
        class_name: str,
        confidence: float
    ) -> None:
        x1, y1, x2, y2 = box
        color = self.colors.get(class_name.lower(), (0, 255, 0))

        text = f"{class_name}: {confidence:.2f}"

        label_height = 30
        if y1 < label_height:
            text_y = y2 + label_height
        else:
            text_y = y1 - 5

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        corner_length = 20
        thickness = 2
        cv2.line(frame, (x1, y1), (x1 + corner_length, y1), color, thickness)
        cv2.line(frame, (x1, y1), (x1, y1 + corner_length), color, thickness)
        cv2.line(frame, (x2, y1), (x2 - corner_length, y1), color, thickness)
        cv2.line(frame, (x2, y1), (x2, y1 + corner_length), color, thickness)
        cv2.line(frame, (x1, y2), (x1 + corner_length, y2), color, thickness)
        cv2.line(frame, (x1, y2), (x1, y2 - corner_length), color, thickness)
        cv2.line(frame, (x2, y2), (x2 - corner_length, y2), color, thickness)
        cv2.line(frame, (x2, y2), (x2, y2 - corner_length), color, thickness)

        cv2.putText(frame, text, (x1, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    def process_frame(self, frame: np.ndarray) -> FireDetectionResult:
        try:
            resized_frame = self.resize_frame(frame)
            results = self.model(
                resized_frame, iou=self.iou_threshold, conf=self.min_confidence, verbose=False)

            detection = None
            max_confidence = 0.0
            boxes = []

            if results and len(results[0].boxes) > 0:
                boxes_data = results[0].boxes.xyxy.cpu().numpy().astype(int)
                class_ids = results[0].boxes.cls.cpu().numpy().astype(int)
                confidences = results[0].boxes.conf.cpu().numpy()

                sort_idx = np.argsort(-confidences)
                boxes_data = boxes_data[sort_idx]
                class_ids = class_ids[sort_idx]
                confidences = confidences[sort_idx]

                for box, class_id, confidence in zip(boxes_data, class_ids, confidences):
                    class_name = self.names[class_id]
                    boxes.append({
                        'box': box,
                        'class': class_name,
                        'confidence': float(confidence)
                    })

                    if detection is None:
                        if "fire" == class_name.lower() and confidence >= self.min_confidence:
                            detection = "Fire"
                            max_confidence = float(confidence)
                        elif "smoke" == class_name.lower() and confidence >= self.smoke_confidence:
                            detection = "Smoke"
                            max_confidence = float(confidence)

                    self.draw_detection(resized_frame, box, class_name, confidence)

            return FireDetectionResult(
                detection=detection,
                confidence=max_confidence,
                boxes=boxes
            )

        except Exception as e:
            print(f'[Warning] Fire detection frame error: {e}')
            return FireDetectionResult(detection=None, confidence=0.0, boxes=[])


def build_fire_pipeline():
    if os.environ.get('FIRE_DETECTION', '1') == '0':
        print('Fire detection disabled via FIRE_DETECTION=0')
        return None

    try:
        model_path = Path(__file__).parent.parent / 'models' / 'best_nano_111.pt'
        if not model_path.exists():
            print(f'[Warning] Fire detection model not found at {model_path}')
            return None

        detector = FireDetector(model_path)
        print('Fire detection: ON')
        return detector
    except Exception as e:
        print(f'[Warning] Fire detection unavailable, continuing without it: {e}')
        return None