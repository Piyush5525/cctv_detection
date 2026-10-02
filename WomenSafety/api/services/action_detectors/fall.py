"""EXPERIMENTAL fall detector (rules over YOLOv8n-pose keypoints; no training).

Per tracked person, over the last FALL_WINDOW_S seconds:

  1. an UPRIGHT sample (torso angle from vertical <= FALL_UPRIGHT_ANGLE_DEG),
  2. followed within FALL_TRANSITION_S by a DOWN sample (torso angle >= FALL_DOWN_ANGLE_DEG, or the box flipped
     to wider-than-tall: width/height >= FALL_ASPECT_FLIP),
  3. with a fast height drop between them: head AND hip drop (in standing box heights) >= FALL_HEAD_DROP_FRAC /
     FALL_HIP_DROP_FRAC and peak drop velocity >= FALL_DROP_VEL standing heights per second,
  4. and the person STAYS down (every later sample is down) for at least FALL_STAY_DOWN_S.

What each rule is there to reject:
  sitting   -> torso stays upright (never "down")
  crouching -> torso stays upright, box never flips
  bending   -> head drops but the hips do not (hip-drop rule), and it recovers within seconds (stay-down rule)
  lying down on purpose -> the upright->down transition takes longer than FALL_TRANSITION_S
  very small / distant persons -> ignored (box shorter than ACTION_MIN_PERSON_H_FRAC of the frame; applied by
  the engine before tracking)

A confirmed fall is latched per track until the person is upright again (or the track is gone for 2 s), because
the original transition scrolls out of the window while the person is still lying there.
Score = 0.30 velocity + 0.25 torso angle + 0.15 aspect flip + 0.30 stay-down, each capped at 1; a detection also
needs every rule above to hold and score >= FALL_SCORE_THRESHOLD.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from api.core.config import settings
from api.services.action_detectors.base import (
    ActionDetector, ActionResult, PersonPose, PoseFrame, L_HIP, R_HIP, L_SHO, R_SHO, NOSE, L_EYE, R_EYE, L_EAR, R_EAR,
    person_box, r3,
)

_UNLATCH_MISSING_S = 2.0
_UNLATCH_UPRIGHT_SAMPLES = 2


def features(p: PersonPose) -> dict:
    """Scalar posture features of one person (no keypoints leave this function)."""
    sho, hip = p.point(L_SHO, R_SHO), p.point(L_HIP, R_HIP)
    angle: Optional[float] = None
    if sho is not None and hip is not None:
        v = sho - hip
        angle = math.degrees(math.atan2(abs(v[0]), abs(v[1]) + 1e-6))   # 0 = vertical torso, 90 = horizontal
    head = p.point(NOSE, L_EYE, R_EYE, L_EAR, R_EAR)
    head_y = float(head[1]) if head is not None else (float(sho[1]) if sho is not None else float(p.box[1]))
    hip_y = float(hip[1]) if hip is not None else float((p.box[1] + p.box[3]) / 2.0)
    return {"angle": angle, "aspect": p.w / max(p.h, 1.0), "head_y": head_y, "hip_y": hip_y, "h": p.h, "w": p.w}


class FallDetector(ActionDetector):
    name = "fall"
    category = "fall"
    label = "Fall"
    detector_source = "pose-fall-rules"
    model_name = "yolov8n-pose.pt + rules"

    def __init__(self):
        s = settings
        self.window_s, self.interval_s = s.FALL_WINDOW_S, s.FALL_INTERVAL_S
        self.threshold = s.FALL_SCORE_THRESHOLD
        self.confirm_n, self.confirm_m = s.FALL_CONFIRM_N, s.FALL_CONFIRM_M
        self.end_gap_s, self.merge_s = s.FALL_END_GAP_S, s.FALL_MERGE_S
        self._latched: dict = {}    # track_id -> {"t_down","vel","head_drop","hip_drop","last_seen","upright_run"}
        self._seen: dict = {}       # track_id -> memory used by the lost-track-then-low path
        self._links: dict = {}      # new track_id -> link to the upright predecessor (or None once it stood up / was rejected)

    # --- sample classification -------------------------------------------------
    @staticmethod
    def _is_down(f: dict) -> bool:
        return (f["angle"] is not None and f["angle"] >= settings.FALL_DOWN_ANGLE_DEG) or f["aspect"] >= settings.FALL_ASPECT_FLIP

    @staticmethod
    def _is_upright(f: dict) -> bool:
        if f["aspect"] >= settings.FALL_ASPECT_FLIP:
            return False
        return f["angle"] <= settings.FALL_UPRIGHT_ANGLE_DEG if f["angle"] is not None else f["aspect"] < 0.7

    # --- core ------------------------------------------------------------------
    def _transition(self, samples: list) -> Optional[dict]:
        """samples: [(t, feat)] oldest..newest of ONE track. Returns the fall evidence or None.
        self._why records, for diagnostics only, why the last call returned None."""
        self._why = None
        if len(samples) < 3:
            self._why = "track too short (fewer than 3 samples)"
            return None
        if not self._is_down(samples[-1][1]):
            self._why = "person never reached a down posture (torso not near horizontal, box not wider than tall)"
            return None
        i_d = len(samples) - 1                                   # first sample of the trailing run of 'down'
        while i_d > 0 and self._is_down(samples[i_d - 1][1]):
            i_d -= 1
        i_u = None
        for k in range(i_d - 1, -1, -1):                         # nearest earlier upright sample (mid samples allowed)
            if self._is_upright(samples[k][1]):
                i_u = k
                break
        if i_u is None:
            self._why = "no upright sample before the down posture (person was already low / entered lying)"
            return None
        t_u, fu = samples[i_u]
        t_d, fd = samples[i_d]
        transition_s = t_d - t_u
        if transition_s > settings.FALL_TRANSITION_S + 1e-6:
            self._why = f"upright-to-down transition too slow ({transition_s:.2f} s > {settings.FALL_TRANSITION_S} s)"
            return None                                          # too slow: lying down on purpose
        ref = max(fu["h"], 1.0)                                  # standing height of this person
        head_drop = (fd["head_y"] - fu["head_y"]) / ref
        hip_drop = (fd["hip_y"] - fu["hip_y"]) / ref
        vel = 0.0
        for k in range(i_u, i_d):
            (ta, fa), (tb, fb) = samples[k], samples[k + 1]
            step = ((fb["head_y"] - fa["head_y"]) + (fb["hip_y"] - fa["hip_y"])) / 2.0 / ref / max(tb - ta, 1e-3)
            vel = max(vel, step)
        return {"t_down": t_d, "transition_s": transition_s, "head_drop": head_drop, "hip_drop": hip_drop, "vel": vel}

    def _score(self, ev: dict, f_last: dict, stay: float) -> float:
        s = settings
        vel_s = min(1.0, max(ev["vel"], 0.0) / (2 * s.FALL_DROP_VEL))
        angle = f_last["angle"] if f_last["angle"] is not None else (90.0 if f_last["aspect"] >= s.FALL_ASPECT_FLIP else 0.0)
        angle_s = min(1.0, max(0.0, (angle - 30.0) / 60.0))
        flip_s = 1.0 if f_last["aspect"] >= s.FALL_ASPECT_FLIP else 0.0
        stay_s = min(1.0, stay / max(2 * s.FALL_STAY_DOWN_S, 1e-6))
        return 0.30 * vel_s + 0.25 * angle_s + 0.15 * flip_s + 0.30 * stay_s

    # --- second path: the track is lost during the fall, a new low track appears nearby ----------------------------------
    def _edge(self, p: PersonPose, pf: PoseFrame) -> bool:
        m = settings.FALL_EDGE_MARGIN
        return p.box[0] <= m * pf.frame_w or p.box[2] >= (1 - m) * pf.frame_w or p.box[1] <= m * pf.frame_h

    def _update_seen(self, latest: PoseFrame) -> None:
        for p in latest.persons:
            f = features(p)
            rec = self._seen.get(p.track_id)
            if rec is None:
                rec = self._seen[p.track_id] = {"t_first": latest.t, "first": p, "up_p": None, "upright_t": None}
            rec.update(t_last=latest.t, p=p, f=f, edge=self._edge(p, latest))
            if self._is_upright(f) and p.h >= 0.08 * latest.frame_h:
                rec["up_p"], rec["upright_t"], rec["up_edge"] = p, latest.t, rec["edge"]
        for tid in [k for k, r in self._seen.items() if latest.t - r["t_last"] > 30.0]:
            self._seen.pop(tid, None); self._links.pop(tid, None)

    def _find_link(self, tid: int, latest: PoseFrame) -> Optional[dict]:
        s = settings
        rec = self._seen[tid]
        p0 = rec["first"]
        best = None
        for old_id, old in self._seen.items():
            if old_id == tid or old["up_p"] is None or old.get("up_edge"):
                continue
            gap = rec["t_first"] - old["t_last"]
            if not 0.2 <= gap <= s.FALL_LOST_GAP_S or old["t_last"] - old["upright_t"] > 1.0:
                continue
            ref = max(old["up_p"].h, 1.0)
            u = old["up_p"]
            ratio = p0.h / ref
            head_drop = (features(p0)["head_y"] - features(u)["head_y"]) / ref
            bottom_shift = abs(p0.box[3] - u.box[3]) / ref
            dist = float(np.linalg.norm(p0.center - u.center)) / ref
            if dist <= s.FALL_LOST_LINK_DIST and ratio <= s.FALL_LOW_HEIGHT_RATIO and head_drop >= s.FALL_LOST_MIN_HEAD_DROP:
                cand = {"old": old_id, "gap": gap, "ref": ref, "ratio": ratio, "head_drop": head_drop, "bottom_shift": bottom_shift,
                        "hip_drop": (features(p0)["hip_y"] - features(u)["hip_y"]) / ref}
                if best is None or cand["gap"] < best["gap"]:
                    best = cand
        return best

    def _linked_results(self, latest: PoseFrame) -> list:
        s = settings
        out = []
        for p in latest.persons:
            tid = p.track_id
            if tid not in self._links:
                self._links[tid] = self._find_link(tid, latest)
            link = self._links[tid]
            if not link:
                continue
            f = features(p)
            ratio_now = p.h / link["ref"]
            if ratio_now > s.FALL_LOW_HEIGHT_RATIO + 0.15 or (self._is_upright(f) and ratio_now > 0.85):
                self._links[tid] = None            # the person stood up: not a fall
                continue
            stay = latest.t - self._seen[tid]["t_first"]
            clip01 = lambda v: max(0.0, min(1.0, v))
            score = (0.35 * clip01((1 - link["ratio"]) / 0.5) + 0.25 * clip01(link["head_drop"] / 0.6)
                     + 0.25 * clip01(stay / max(2 * s.FALL_STAY_DOWN_S, 1e-6)) + 0.15 * clip01(1 - link["gap"] / s.FALL_LOST_GAP_S))
            detected = stay >= s.FALL_STAY_DOWN_S and score >= self.threshold
            signals = {"path": "lost_track_then_low", "track_id": int(tid), "track_gap_s": r3(link["gap"]), "height_ratio": r3(link["ratio"]),
                       "head_drop_frac": r3(link["head_drop"]), "hip_drop_frac": r3(link["hip_drop"]), "bottom_shift": r3(link["bottom_shift"]),
                       "torso_angle_deg": None if f["angle"] is None else r3(f["angle"]), "aspect_ratio": r3(f["aspect"]),
                       "stay_down_s": r3(stay), "stay_down_required_s": s.FALL_STAY_DOWN_S}
            if not detected:
                signals["blocked_by"] = [f"stay-down {stay:.1f} s < {s.FALL_STAY_DOWN_S} s"] if stay < s.FALL_STAY_DOWN_S else [f"score {score:.2f} < threshold {self.threshold}"]
            out.append(ActionResult(detected=detected, score=score, label="fall", signals=signals,
                                    boxes=[person_box(p, "fall (experimental)", score)] if detected else []))
        return out

    def detect(self, window: list) -> ActionResult:
        s = settings
        latest: PoseFrame = window[-1]
        self._update_seen(latest)
        by_track: dict = {}
        persons: dict = {}
        for pf in window:
            for p in pf.persons:
                by_track.setdefault(p.track_id, []).append((pf.t, features(p)))
        for p in latest.persons:
            persons[p.track_id] = p

        best: Optional[ActionResult] = None
        reasons: list = []
        for tid, samples in by_track.items():
            p = persons.get(tid)
            if p is None:                                        # not in the newest frame
                lat = self._latched.get(tid)
                if lat is not None and latest.t - lat["last_seen"] > _UNLATCH_MISSING_S:
                    del self._latched[tid]
                continue
            f_last = samples[-1][1]
            lat = self._latched.get(tid)
            ev = self._transition(samples)
            if lat is not None:                                  # already confirmed: hold while still down
                lat["last_seen"] = latest.t
                if self._is_upright(f_last):
                    lat["upright_run"] += 1
                    if lat["upright_run"] >= _UNLATCH_UPRIGHT_SAMPLES:
                        del self._latched[tid]
                        continue
                else:
                    lat["upright_run"] = 0
                stay = latest.t - lat["t_down"]
                ev_use = {"vel": lat["vel"], "head_drop": lat["head_drop"], "hip_drop": lat["hip_drop"], "transition_s": lat["transition_s"]}
            elif ev is not None:
                stay = latest.t - ev["t_down"]
                ev_use = ev
            else:
                if getattr(self, "_why", None):
                    reasons.append(self._why)
                continue
            ok = (ev_use["head_drop"] >= s.FALL_HEAD_DROP_FRAC and ev_use["hip_drop"] >= s.FALL_HIP_DROP_FRAC
                  and ev_use["vel"] >= s.FALL_DROP_VEL and stay >= s.FALL_STAY_DOWN_S)
            score = self._score(ev_use, f_last, stay)
            detected = ok and score >= self.threshold
            if detected and lat is None and ev is not None:
                self._latched[tid] = {"t_down": ev["t_down"], "vel": ev["vel"], "head_drop": ev["head_drop"], "hip_drop": ev["hip_drop"],
                                      "transition_s": ev["transition_s"], "last_seen": latest.t, "upright_run": 0}
            signals = {
                "track_id": int(tid), "head_drop_frac": r3(ev_use["head_drop"]), "hip_drop_frac": r3(ev_use["hip_drop"]),
                "drop_velocity": r3(ev_use["vel"]), "transition_s": r3(ev_use["transition_s"]),
                "torso_angle_deg": None if f_last["angle"] is None else r3(f_last["angle"]),
                "aspect_ratio": r3(f_last["aspect"]), "aspect_flip": bool(f_last["aspect"] >= s.FALL_ASPECT_FLIP),
                "stay_down_s": r3(stay), "stay_down_required_s": s.FALL_STAY_DOWN_S,
            }
            if not detected:
                failed = []
                if ev_use["head_drop"] < s.FALL_HEAD_DROP_FRAC:
                    failed.append(f"head drop {ev_use['head_drop']:.2f} < {s.FALL_HEAD_DROP_FRAC}")
                if ev_use["hip_drop"] < s.FALL_HIP_DROP_FRAC:
                    failed.append(f"hip drop {ev_use['hip_drop']:.2f} < {s.FALL_HIP_DROP_FRAC}")
                if ev_use["vel"] < s.FALL_DROP_VEL:
                    failed.append(f"drop velocity {ev_use['vel']:.2f} < {s.FALL_DROP_VEL}")
                if stay < s.FALL_STAY_DOWN_S:
                    failed.append(f"stay-down {stay:.1f} s < {s.FALL_STAY_DOWN_S} s")
                if not failed:
                    failed.append(f"score {score:.2f} < threshold {self.threshold}")
                signals["blocked_by"] = failed
            res = ActionResult(detected=detected, score=score, label="fall", signals=signals,
                               boxes=[person_box(p, "fall (experimental)", score)] if detected else [])
            if best is None or (res.detected, res.score) > (best.detected, best.score):
                best = res
        for res in self._linked_results(latest):
            if best is None or (res.detected, res.score) > (best.detected, best.score):
                best = res
        if best is not None:
            return best
        return ActionResult(detected=False, score=0.0, label="fall", signals={"blocked_by": sorted(set(reasons))} if reasons else {})
