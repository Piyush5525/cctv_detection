"""EXPERIMENTAL violence detector: the existing CLIP zero-shot score, but only evaluated behind pose gates.

Gates (all must hold before CLIP is even run -- this is also the cost saving: CLIP is ~150-300 ms on CPU):
  1. people: either two or more tracked persons with a pair closer than VIOLENCE_PROXIMITY body heights (in at least half of the
     window), OR a single person box that is large (>= VIOLENCE_MERGED_MIN_H of the frame height): tangled fighters very often
     merge into ONE pose box, so a lone large blob is allowed -- the motion gate below still has to pass;
  2. sustained LIMB motion energy: elbow/wrist/knee/ankle displacement relative to the torso (walking or crossing the scene does
     not count), in body heights per second, above VIOLENCE_MOTION_THRESHOLD for at least VIOLENCE_SUSTAIN_FRAC of the window,
     measured between successive appearances of the same track (gaps up to VIOLENCE_MAX_GAP_S are bridged because pose on a
     struggle drops out often), with the window spanning at least VIOLENCE_MIN_SPAN_S.
Then CLIP (the repo's ViT-B/32 and settings.yaml labels) scores the newest frame. The label is the TOP-1 over all labels (violence
labels compete with the normal/crash/fire labels) and counts when it is a violence/fight label with cosine >= VIOLENCE_CLIP_THRESHOLD.
The old cutoff (0.28) is the legacy "Unknown" fallback of model.py; CLIP cosines on real fight frames sit at 0.22-0.25, so the
detector reads the raw top-1 itself (model.py is untouched). N-of-M smoothing (VIOLENCE_SMOOTH_N of the last VIOLENCE_SMOOTH_M
evaluations, gate-closed evaluations count as misses) decides the verdict. Reported score = mean score of the raw hits in the
smoothing window (a CLIP cosine similarity, a low-valued scale).
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

ClipFn = Callable[[np.ndarray], tuple]   # BGR frame -> (top-1 label, cosine score)

_clip_lock = threading.Lock()
_clip_fn: Optional[ClipFn] = None
_clip_failed = False


def get_clip_fn() -> Optional[ClipFn]:
    """The project's own CLIP (model.Model + settings.yaml labels), loaded once per process. Returns the raw top-1 label and its cosine
    score, WITHOUT model.py's 'Unknown' cutoff."""
    global _clip_fn, _clip_failed
    if _clip_fn is not None or _clip_failed:
        return _clip_fn
    with _clip_lock:
        if _clip_fn is None and not _clip_failed:
            try:
                import cv2
                import torch
                from model import Model
                model = Model(settings_path=str(ROOT / "settings.yaml"))
                text = model.text_features / model.text_features.norm(dim=-1, keepdim=True)

                @torch.no_grad()
                def run(frame_bgr: np.ndarray) -> tuple:
                    feats = model.model.encode_image(model.transform_image(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)))
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                    sims = (feats @ text.T)[0]
                    idx = int(sims.argmax().item())
                    return model.labels[idx], float(sims[idx].item())
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

    def _people_gate(self, window: list) -> tuple:
        """-> (ok, info dict, boxes to draw)"""
        s = settings
        latest = next((pf for pf in reversed(window) if pf.persons), None)
        if latest is None:
            return False, {"reason": "no person in the window"}, []
        frames_with_people = sum(1 for pf in window if pf.persons)
        if frames_with_people < 0.4 * len(window):
            return False, {"reason": "person present in too little of the window"}, []
        pair = self._close_pair(latest)
        close_frames = sum(1 for pf in window if len(pf.persons) >= 2 and self._close_pair(pf) is not None)
        if pair is not None and close_frames >= 0.4 * len(window):
            return True, {"mode": "close_pair", "pair_distance": pair[0]}, [pair[1], pair[2]]
        big = [p for p in latest.persons if p.h >= s.VIOLENCE_MERGED_MIN_H * latest.frame_h]
        if len(latest.persons) == 1 and big:
            return True, {"mode": "merged_blob", "blob_height_frac": big[0].h / latest.frame_h}, big
        return False, {"reason": "persons not close" if len(latest.persons) >= 2 else "single person too small to be a merged pair"}, []

    def _motion_gate(self, window: list) -> tuple:
        s = settings
        last: dict = {}
        energies = []
        for pf in window:
            for p in pf.persons:
                prev = last.get(p.track_id)
                if prev is not None and 0 < pf.t - prev[0] <= s.VIOLENCE_MAX_GAP_S:
                    e = limb_energy(prev[1], p, pf.t - prev[0])
                    if e is not None:
                        energies.append(e)
                last[p.track_id] = (pf.t, p)
        span = window[-1].t - window[0].t
        if span < s.VIOLENCE_MIN_SPAN_S or len(energies) < 3:
            return False, {"window_span_s": span, "reason": "window too short"}
        frac = sum(1 for e in energies if e >= s.VIOLENCE_MOTION_THRESHOLD) / len(energies)
        info = {"window_span_s": span, "motion_energy": float(np.mean(energies)), "motion_sustained_frac": frac}
        if frac < s.VIOLENCE_SUSTAIN_FRAC:
            info["reason"] = "limb motion not sustained"
            return False, info
        return True, info

    def gates(self, window: list) -> dict:
        out = {"persons": len(window[-1].persons), "gate_open": False, "reason": ""}
        ok, info, boxes = self._people_gate(window)
        out.update({k: v for k, v in info.items() if k != "reason"})
        if not ok:
            out["reason"] = info["reason"]
            return out
        ok, minfo = self._motion_gate(window)
        out.update({k: v for k, v in minfo.items() if k != "reason"})
        if not ok:
            out["reason"] = minfo["reason"]
            return out
        out["gate_open"], out["boxes"] = True, boxes
        return out

    def detect(self, window: list) -> ActionResult:
        g = self.gates(window)
        signals = {"persons": g["persons"], "gate_open": g["gate_open"]}
        for key in ("mode", "pair_distance", "blob_height_frac", "motion_energy", "motion_sustained_frac"):
            if key in g:
                signals[key] = g[key] if isinstance(g[key], str) else r3(g[key])
        if not g["gate_open"]:
            self._hits.append(0.0)
            signals["gate_reason"] = g["reason"]
            return ActionResult(detected=False, score=0.0, label="violence", signals=signals, evaluated=False)
        fn = self.clip_fn
        frame_pf = next((pf for pf in reversed(window) if pf.frame is not None), None)
        if fn is None or frame_pf is None:
            self._hits.append(0.0)
            signals["gate_reason"] = "CLIP unavailable"
            return ActionResult(detected=False, label="violence", signals=signals, evaluated=False)
        label, score = fn(frame_pf.frame)
        self.clip_calls += 1
        raw_hit = is_violent_label(label) and score >= settings.VIOLENCE_CLIP_THRESHOLD
        self._hits.append(score if raw_hit else 0.0)
        n_hit = sum(1 for v in self._hits if v > 0)
        smoothed = n_hit >= settings.VIOLENCE_SMOOTH_N
        signals.update({"clip_label": label, "clip_score": r3(score), "smoothing": f"{n_hit} of {len(self._hits)} (need {settings.VIOLENCE_SMOOTH_N} of {settings.VIOLENCE_SMOOTH_M})"})
        mean_hit = float(np.mean([v for v in self._hits if v > 0])) if n_hit else 0.0
        boxes = [person_box(p, "violence (experimental)", mean_hit) for p in g["boxes"]] if smoothed else []
        return ActionResult(detected=smoothed, score=mean_hit if smoothed else score if raw_hit else 0.0, label="violence", signals=signals, boxes=boxes)
