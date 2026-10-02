"""Shared types for the EXPERIMENTAL action detectors (fall, violence, snatch).

Every action detector sees the same thing: a sliding window of PoseFrame objects (one per shared pose pass,
each holding the tracked persons of that moment) and returns an ActionResult. Nothing here is persisted:
keypoints exist only in memory while a window is evaluated and, for the overlay image, in the sampled-frame
verdicts of an event; the incident record keeps only the scalar `signals`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# COCO-17 keypoint indices
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SHO, R_SHO, L_ELB, R_ELB, L_WRI, R_WRI = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KNE, R_KNE, L_ANK, R_ANK = 11, 12, 13, 14, 15, 16
KP_MIN_CONF = 0.3


@dataclass
class PersonPose:
    track_id: int
    box: tuple          # x1, y1, x2, y2 (pixels of the frame the pose pass ran on)
    kp: np.ndarray      # (17, 3): x, y, confidence

    @property
    def w(self) -> float:
        return float(self.box[2] - self.box[0])

    @property
    def h(self) -> float:
        return float(self.box[3] - self.box[1])

    @property
    def center(self) -> np.ndarray:
        return np.array([(self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0])

    def point(self, *idx: int) -> Optional[np.ndarray]:
        """Mean of the listed keypoints that are visible, or None."""
        pts = [self.kp[i, :2] for i in idx if self.kp[i, 2] >= KP_MIN_CONF]
        return np.mean(pts, axis=0) if pts else None


@dataclass
class PoseFrame:
    t: float                                 # seconds (wall clock live, video time in replay/eval)
    persons: list
    frame_h: int
    frame_w: int
    frame: Optional[np.ndarray] = None       # only the NEWEST PoseFrame keeps its image (CLIP needs it)


@dataclass
class ActionResult:
    detected: bool
    score: float = 0.0
    label: str = ""
    boxes: list = field(default_factory=list)    # [{label, confidence, box, keypoints?}] for the overlay
    signals: dict = field(default_factory=dict)  # scalar signals that fired (stored on the incident)
    evaluated: bool = True                       # False = skipped (e.g. violence gate closed): nothing was scored


def r3(x) -> float:
    return round(float(x), 3)


class ActionDetector:
    """name/category/label identify the detector; window_s and interval_s are its own cadence; threshold is the
    score it must reach. confirm/end/merge are handed to that detector's EventCapturePipeline."""
    name: str = ""
    category: str = ""          # incident category value ("fall", "assault", "snatching")
    label: str = ""             # what the operator sees ("Fall", "Violence", "Snatch")
    detector_source: str = ""
    model_name: str = ""
    weights_file: Optional[str] = None
    needs_frame: bool = False   # True if detect() reads window[-1].frame

    window_s: float = 3.0
    interval_s: float = 0.25
    threshold: float = 0.5
    confirm_n: int = 2
    confirm_m: int = 3
    end_gap_s: float = 6.0
    merge_s: float = 30.0

    def detect(self, window: list) -> ActionResult:  # pragma: no cover - interface
        raise NotImplementedError

    def idle(self) -> ActionResult:
        """Called instead of detect() when no person is visible (the detector does no work)."""
        return ActionResult(detected=False, evaluated=True)

    def describe(self) -> dict:
        return {"name": self.name, "category": self.category, "window_s": self.window_s, "interval_s": self.interval_s,
                "threshold": self.threshold, "confirm": f"{self.confirm_n} of {self.confirm_m}",
                "end_gap_s": self.end_gap_s, "merge_s": self.merge_s}


def person_box(p: PersonPose, label: str, score: float, with_keypoints: bool = True) -> dict:
    out = {"label": label, "confidence": float(score), "box": [float(v) for v in p.box]}
    if with_keypoints:
        out["keypoints"] = [[float(x), float(y), float(c)] for x, y, c in p.kp]
    return out
