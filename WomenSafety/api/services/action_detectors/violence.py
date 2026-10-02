"""EXPERIMENTAL violence detector: the existing CLIP zero-shot score, but only evaluated behind gates.

Gates (all must hold before CLIP is even run -- this is also the cost saving: CLIP is ~150-300 ms on CPU):
  1. two or more tracked persons, at least one pair closer than VIOLENCE_PROXIMITY body heights, and a close
     pair present in at least half of the window;
  2. sustained LIMB motion energy: elbow/wrist/knee/ankle displacement relative to the torso (so walking or
     a person simply crossing the scene does not count), in body heights per second, above
     VIOLENCE_MOTION_THRESHOLD for at least VIOLENCE_SUSTAIN_FRAC of the window, with the window spanning at
     least VIOLENCE_MIN_SPAN_S.
Then CLIP (model.py, settings.yaml labels) scores the newest frame; a violence/fight label with cosine score >=
VIOLENCE_CLIP_THRESHOLD is a raw hit. N-of-M smoothing (VIOLENCE_SMOOTH_N of the last VIOLENCE_SMOOTH_M
evaluations, gate-closed evaluations count as misses) decides the verdict. Reported score = mean score of the
raw hits in the smoothing window (a CLIP cosine similarity, which is a low-valued scale: ~0.28-0.35 is normal).
"""
from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from api.core.config import settings
from api.services.action_detectors.base import (
    ActionDetector, ActionResult, PersonPose, PoseFrame, L_ELB, R_ELB, L_WRI, R_WRI, L_KNE, R_KNE, L_ANK, R_ANK,
    L_HIP, R_HIP, L_SHO, R_SHO, KP_MIN_CONF, person_box, r3,
)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
LIMBS = (L_ELB, R_ELB, L_WRI, R_WRI, L_KNE, R_KNE, L_ANK, R_ANK)

ClipFn = Callable[[np.ndarray], tuple]   # BGR frame -> (label, cosine score)

_clip_lock = threading.Lock()
_clip_fn: Optional[ClipFn] = None
_clip_failed = False


def get_clip_fn() -> Optional[ClipFn]:
    """The project's own CLIP wrapper (model.Model + settings.yaml), loaded once per process."""
    global _clip_fn, _clip_failed
    if _clip_fn is not None or _clip_failed:
        return _clip_fn
    with _clip_lock:
        if _clip_fn is None and not _clip_failed:
            try:
                import cv2
                from model import Model
                model = Model(settings_path=str(ROOT / "settings.yaml"))

                def run(frame_bgr: np.ndarray) -> tuple:
                    pred = model.predict(image=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
                    return pred["label"], float(pred["confidence"])
                _clip_fn = run
                print("[ActionDetectors] CLIP loaded for the gated violence detector")
            except Exception as exc:  # pragma: no cover - environment dependent
                _clip_failed = True
                print(f"[ActionDetectors] CLIP unavailable ({type(exc).__name__}); violence detector disabled")
    return _clip_fn


def is_violent_label(label: str) -> bool:
    low = (label or "").lower()
    return "violence" in low or "fight" in low


def limb_energy(a: PersonPose, b: PersonPose, dt: float) -> Optional[float]:
    """Mean torso-relative limb displacement between two samples of one person, body heights per second."""
    ta, tb = a.point(L_HIP, R_HIP, L_SHO, R_SHO), b.point(L_HIP, R_HIP, L_SHO, R_SHO)
    if ta is None or tb is None or dt <= 0:
        return None
    body_h = max(a.h, b.h, 1.0)
    vals = []
    for i in LIMBS:
        if a.kp[i, 2] >= KP_MIN_CONF and b.kp[i, 2] >= KP_MIN_CONF:
            vals.append(float(np.linalg.norm((b.kp[i, :2] - tb) - (a.kp[i, :2] - ta))))
    return float(np.mean(vals)) / body_h / dt if vals else None


class ViolenceDetector(ActionDetector):
    name = "violence"
    category = "assault"
    label = "Violence"
    detector_source = "clip-gated-violence"
    model_name = "CLIP ViT-B/32 (zero-shot) + pose gates"
    needs_frame = True

    def __init__(self, clip_fn: Optional[ClipFn] = None):
        s = settings
        self._clip_fn = clip_fn
        self.window_s, self.interval_s = s.VIOLENCE_WINDOW_S, s.VIOLENCE_INTERVAL_S
        self.threshold = s.VIOLENCE_CLIP_THRESHOLD
        self.confirm_n, self.confirm_m = s.VIOLENCE_CONFIRM_N, s.VIOLENCE_CONFIRM_M
        self.end_gap_s, self.merge_s = s.VIOLENCE_END_GAP_S, s.VIOLENCE_MERGE_S
        self._hits: deque = deque(maxlen=s.VIOLENCE_SMOOTH_M)   # raw hit scores (0.0 = miss / gate closed)
        self.clip_calls = 0

    @property
    def clip_fn(self) -> Optional[ClipFn]:
        if self._clip_fn is None:
            self._clip_fn = get_clip_fn()
        return self._clip_fn

    def idle(self) -> ActionResult:
        self._hits.append(0.0)
        return ActionResult(detected=False, label="violence")

    # --- gates -----------------------------------------------------------------
    def _close_pair(self, pf: PoseFrame) -> Optional[tuple]:
        best = None
        ps = pf.persons
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                d = float(np.linalg.norm(ps[i].center - ps[j].center)) / max(ps[i].h, ps[j].h, 1.0)
                if d <= settings.VIOLENCE_PROXIMITY and (best is None or d < best[0]):
                    best = (d, ps[i], ps[j])
        return best

    def gates(self, window: list) -> dict:
        s = settings
        out = {"persons": len(window[-1].persons), "gate_open": False, "reason": ""}
        if out["persons"] < 2:
            out["reason"] = "fewer than 2 persons"
            return out
        close_now = self._close_pair(window[-1])
        close_frames = sum(1 for pf in window if len(pf.persons) >= 2 and self._close_pair(pf) is not None)
        if close_now is None or close_frames < 0.5 * len(window):
            out["reason"] = "persons not close"
            return out
        out["pair_distance"] = close_now[0]
        ids = {close_now[1].track_id, close_now[2].track_id}
        # limb energy per interval = the larger of the two persons' energies
        energies = []
        for k in range(1, len(window)):
            prev = {p.track_id: p for p in window[k - 1].persons if p.track_id in ids}
            cur = {p.track_id: p for p in window[k].persons if p.track_id in ids}
            dt = window[k].t - window[k - 1].t
            e = [limb_energy(prev[i], cur[i], dt) for i in ids if i in prev and i in cur]
            e = [x for x in e if x is not None]
            if e:
                energies.append(max(e))
        span = window[-1].t - window[0].t
        out["window_span_s"] = span
        if span < s.VIOLENCE_MIN_SPAN_S or len(energies) < 3:
            out["reason"] = "window too short"
            return out
        frac = sum(1 for e in energies if e >= s.VIOLENCE_MOTION_THRESHOLD) / len(energies)
        out["motion_energy"] = float(np.mean(energies))
        out["motion_sustained_frac"] = frac
        if frac < s.VIOLENCE_SUSTAIN_FRAC:
            out["reason"] = "limb motion not sustained"
            return out
        out["gate_open"], out["pair"] = True, close_now
        return out

    def detect(self, window: list) -> ActionResult:
        g = self.gates(window)
        signals = {"persons": g["persons"], "gate_open": g["gate_open"]}
        for key in ("pair_distance", "motion_energy", "motion_sustained_frac"):
            if key in g:
                signals[key] = r3(g[key])
        if not g["gate_open"]:
            self._hits.append(0.0)
            signals["gate_reason"] = g["reason"]
            return ActionResult(detected=False, score=0.0, label="violence", signals=signals, evaluated=False)
        fn = self.clip_fn
        if fn is None or window[-1].frame is None:
            self._hits.append(0.0)
            signals["gate_reason"] = "CLIP unavailable"
            return ActionResult(detected=False, label="violence", signals=signals, evaluated=False)
        label, score = fn(window[-1].frame)
        self.clip_calls += 1
        raw_hit = is_violent_label(label) and score >= settings.VIOLENCE_CLIP_THRESHOLD
        self._hits.append(score if raw_hit else 0.0)
        n_hit = sum(1 for v in self._hits if v > 0)
        smoothed = n_hit >= settings.VIOLENCE_SMOOTH_N
        signals.update({"clip_label": label, "clip_score": r3(score), "smoothing": f"{n_hit} of {len(self._hits)} (need {settings.VIOLENCE_SMOOTH_N} of {settings.VIOLENCE_SMOOTH_M})"})
        mean_hit = float(np.mean([v for v in self._hits if v > 0])) if n_hit else 0.0
        _, pa, pb = g["pair"]
        return ActionResult(detected=smoothed, score=mean_hit if smoothed else score if raw_hit else 0.0, label="violence", signals=signals,
                            boxes=[person_box(pa, "violence (experimental)", mean_hit), person_box(pb, "violence (experimental)", mean_hit)] if smoothed else [])
