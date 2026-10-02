"""EXPERIMENTAL snatch detector: a tracking-only prototype (no learned model, no keypoints needed).

For every ordered pair (target A, runner B) of tracked persons, in the last SNATCH_WINDOW_S seconds, all
distances in body heights (max of the two box heights):

  1. SUDDEN APPROACH   the separation falls from >= SNATCH_FAR to <= SNATCH_NEAR within SNATCH_APPROACH_S;
  2. RAPID ACCELERATION after contact, within SNATCH_FLEE_S, B reaches a speed >= SNATCH_FLEE_SPEED and at least
                       SNATCH_ACCEL_RATIO times B's own approach speed (two people simply walking past each other
                       keep their speed, so the ratio stays near 1);
  3. DIVERGENCE        B ends >= SNATCH_SEPARATE away from A, moving away from A, while A does not follow
                       (A's speed stays under half of B's).

Score = mean of four terms (approach quickness, acceleration ratio, flee speed, separation), each
min(1, value / (1.5 x its threshold)); a detection needs all three rules AND score >= SNATCH_SCORE_THRESHOLD.
Thresholds are deliberately high: this is a prototype, labelled EXPERIMENTAL everywhere. Known blind spots: a
snatcher who approaches already at running speed, a snatch from a moving vehicle, and ID switches at the
pose cadence (the tracker predicts motion, but a 1-body-height jump per sample can still break a track).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from api.core.config import settings
from api.services.action_detectors.base import ActionDetector, ActionResult, PersonPose, person_box, r3


def _series(window: list, tid: int) -> list:
    return [(pf.t, p) for pf in window for p in pf.persons if p.track_id == tid]


class SnatchDetector(ActionDetector):
    name = "snatch"
    category = "snatching"
    label = "Snatch"
    detector_source = "track-snatch-rules"
    model_name = "yolov8n-pose.pt tracks + rules"

    def __init__(self):
        s = settings
        self.window_s, self.interval_s = s.SNATCH_WINDOW_S, s.SNATCH_INTERVAL_S
        self.threshold = s.SNATCH_SCORE_THRESHOLD
        self.confirm_n, self.confirm_m = s.SNATCH_CONFIRM_N, s.SNATCH_CONFIRM_M
        self.end_gap_s, self.merge_s = s.SNATCH_END_GAP_S, s.SNATCH_MERGE_S

    def _pair(self, window: list, ida: int, idb: int) -> Optional[dict]:
        s = settings
        sa, sb = dict(((t, p) for t, p in _series(window, ida))), dict(((t, p) for t, p in _series(window, idb)))
        times = sorted(set(sa) & set(sb))
        if len(times) < 4:
            return None
        H = max(float(np.median([sa[t].h for t in times])), float(np.median([sb[t].h for t in times])), 1.0)
        ca = {t: sa[t].center / H for t in times}
        cb = {t: sb[t].center / H for t in times}
        d = {t: float(np.linalg.norm(ca[t] - cb[t])) for t in times}
        # contact = the closest sample that is <= NEAR and was preceded by a >= FAR sample within APPROACH_S
        contact = None
        for t in times:
            if d[t] > s.SNATCH_NEAR:
                continue
            far = [u for u in times if u < t and t - u <= s.SNATCH_APPROACH_S and d[u] >= s.SNATCH_FAR]
            if far:
                contact = (t, far[-1])
                break
        if contact is None:
            return None
        t_n, t_f = contact
        # B's approach speed over [t_f, t_n]
        app = [u for u in times if t_f <= u <= t_n]
        approach_speed = float(np.linalg.norm(cb[app[-1]] - cb[app[0]])) / max(app[-1] - app[0], 1e-3)
        closing = (d[t_f] - d[t_n]) / max(t_n - t_f, 1e-3)
        # flee phase
        after = [u for u in times if t_n <= u <= t_n + s.SNATCH_FLEE_S]
        if len(after) < 2:
            return None
        flee_speed = 0.0
        for k in range(1, len(after)):
            dt = max(after[k] - after[k - 1], 1e-3)
            flee_speed = max(flee_speed, float(np.linalg.norm(cb[after[k]] - cb[after[k - 1]])) / dt)
        span = max(after[-1] - after[0], 1e-3)
        va = (ca[after[-1]] - ca[after[0]]) / span
        vb = (cb[after[-1]] - cb[after[0]]) / span
        sep = max(d[u] for u in after)
        away = float(np.dot(cb[after[-1]] - cb[after[0]], cb[t_n] - ca[t_n])) > 0
        na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(va, vb)) / (na * nb + 1e-9))))) if na > 0.3 else 180.0
        ratio = flee_speed / max(approach_speed, 0.5)   # floor: a near-stationary approacher is not an "infinite" ratio
        far_gap = (s.SNATCH_FAR - s.SNATCH_NEAR) / s.SNATCH_APPROACH_S
        rules = (closing >= far_gap and flee_speed >= s.SNATCH_FLEE_SPEED and ratio >= s.SNATCH_ACCEL_RATIO
                 and sep >= s.SNATCH_SEPARATE and away and na < 0.5 * max(nb, 1e-6))
        cap = lambda v, thr: min(1.0, v / (1.5 * thr))
        score = float(np.mean([cap(closing, far_gap), cap(ratio, s.SNATCH_ACCEL_RATIO), cap(flee_speed, s.SNATCH_FLEE_SPEED), cap(sep, s.SNATCH_SEPARATE)]))
        return {"rules": rules, "score": score, "t": t_n,
                "signals": {"target_track": int(ida), "runner_track": int(idb), "approach_closing_speed": r3(closing),
                            "approach_speed": r3(approach_speed), "flee_speed": r3(flee_speed), "acceleration_ratio": r3(ratio),
                            "separation": r3(sep), "diverging_angle_deg": r3(angle), "target_speed": r3(na)}}

    def detect(self, window: list) -> ActionResult:
        ids = sorted({p.track_id for pf in window for p in pf.persons})
        best = None
        for ida in ids:
            for idb in ids:
                if ida == idb:
                    continue
                res = self._pair(window, ida, idb)
                if res and (best is None or (res["rules"], res["score"]) > (best["rules"], best["score"])):
                    best = res
        if best is None:
            return ActionResult(detected=False, label="snatch")
        detected = bool(best["rules"] and best["score"] >= self.threshold)
        boxes = []
        if detected:
            last = {}
            for pf in window:
                for p in pf.persons:
                    last[p.track_id] = p
            for tid, role in ((best["signals"]["target_track"], "target"), (best["signals"]["runner_track"], "runner")):
                if tid in last:
                    boxes.append(person_box(last[tid], f"snatch {role} (experimental)", best["score"]))
        return ActionResult(detected=detected, score=best["score"], label="snatch", signals=best["signals"], boxes=boxes)
