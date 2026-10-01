"""Detector interface (Phase 1c hardening item 7). A thin, uniform
wrapper around this project's existing per-model detectors (fire, crash
today) so the event-capture pipeline and any future eval harness can
call every registered detector the same way: name, the classes it can
report, its threshold, and a detect(frame) method returning a uniform
result shape.

Per explicit instruction: only fire and crash are registered here.
Violence (CLIP)/fall/snatch are NOT wrapped or registered -- they stay
exactly as they are in main.py/detection_service.py, called directly,
untouched. A class asked about that no class of ANY registered detector
covers (e.g. "snatching", "fall") must be reported by the eval harness
as "not supported", never silently counted as a miss -- see
DetectorRegistry.supports_class() and eval_detectors.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

MODELS_DIR = Path(__file__).parent.parent.parent / "models"


@dataclass
class DetectorResult:
    detection: Optional[str]  # class name if hit, else None
    confidence: float
    boxes: list  # [{class, confidence, box}]


@dataclass
class Detector:
    name: str
    classes: list[str]  # class names this detector can ever report
    threshold: float
    weights_file: Optional[str]
    weights_sha256: Optional[str]
    _detect_fn: Callable[[np.ndarray], DetectorResult]

    def detect(self, frame: np.ndarray) -> DetectorResult:
        return self._detect_fn(frame)


def _sha256_of(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_fire_detector(threshold: float = 0.5) -> Optional[Detector]:
    from fire_detection.detector import build_fire_pipeline
    impl = build_fire_pipeline()
    if impl is None:
        return None

    def _detect(frame: np.ndarray) -> DetectorResult:
        r = impl.process_frame(frame)
        return DetectorResult(detection=r.detection, confidence=r.confidence, boxes=r.boxes)

    weights_path = MODELS_DIR / "best_nano_111.pt"
    return Detector(
        name="fire", classes=["fire", "smoke"], threshold=threshold,
        weights_file=str(weights_path), weights_sha256=_sha256_of(weights_path),
        _detect_fn=_detect,
    )


def _build_crash_detector(threshold: float = 0.5) -> Optional[Detector]:
    from crash_detection.detector import build_crash_pipeline
    impl = build_crash_pipeline()
    if impl is None:
        return None

    def _detect(frame: np.ndarray) -> DetectorResult:
        r = impl.process_frame(frame)
        return DetectorResult(detection=r.detection, confidence=r.confidence, boxes=r.boxes)

    weights_path = MODELS_DIR / "crash_best.pt"
    return Detector(
        name="crash", classes=["Accident"], threshold=threshold,
        weights_file=str(weights_path), weights_sha256=_sha256_of(weights_path),
        _detect_fn=_detect,
    )


class DetectorRegistry:
    """Only fire and crash are registered, per explicit instruction --
    violence/fall/snatch are deliberately NOT added here.

    confidence_floor (Phase 1c follow-up 2, HIGH-priority finding, see
    CHANGELOG.md): defaults to 0.5, this harness's historical behavior
    -- NOT settings.FIRE_CRASH_CONFIDENCE_FLOOR (which defaults to 0.0,
    matching the LIVE loop's current no-floor behavior). These are
    DELIBERATELY different right now; Phase 2 should run this harness
    at both 0.5 and settings.FIRE_CRASH_CONFIDENCE_FLOOR and report
    both, before deciding whether the live loop should adopt a floor."""

    def __init__(self, confidence_floor: float = 0.5):
        self.confidence_floor = confidence_floor
        self._detectors: dict[str, Detector] = {}
        fire = _build_fire_detector(threshold=confidence_floor)
        if fire:
            self._detectors["fire"] = fire
        crash = _build_crash_detector(threshold=confidence_floor)
        if crash:
            self._detectors["crash"] = crash

    def all(self) -> list[Detector]:
        return list(self._detectors.values())

    def get(self, name: str) -> Optional[Detector]:
        return self._detectors.get(name)

    def all_supported_classes(self) -> set[str]:
        classes = set()
        for d in self._detectors.values():
            classes.update(d.classes)
        return classes

    def supports_class(self, class_name: str) -> bool:
        return class_name in self.all_supported_classes()
