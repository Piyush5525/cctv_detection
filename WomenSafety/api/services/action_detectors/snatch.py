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
from api.services.action_detectors.fall import features as posture_features


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
            return {"blocked": "pair not tracked together for 4+ samples"}
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
            return {"blocked": f"no sudden approach (separation never fell from >= {s.SNATCH_FAR} to <= {s.SNATCH_NEAR} body heights within {s.SNATCH_APPROACH_S} s)"}
        t_n, t_f = contact
        # B's approach speed over [t_f, t_n]
        app = [u for u in times if t_f <= u <= t_n]
        approach_speed = float(np.linalg.norm(cb[app[-1]] - cb[app[0]])) / max(app[-1] - app[0], 1e-3)
        closing = (d[t_f] - d[t_n]) / max(t_n - t_f, 1e-3)
        # flee phase
        after = [u for u in times if t_n <= u <= t_n + s.SNATCH_FLEE_S]
        if len(after) < 2:
            return {"blocked": "pair lost right after contact (fewer than 2 samples in the flee window)"}
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
        failed = []
        if closing < far_gap:
            failed.append(f"approach closing speed {closing:.2f} < {far_gap:.2f}")
        if flee_speed < s.SNATCH_FLEE_SPEED:
            failed.append(f"flee speed {flee_speed:.2f} < {s.SNATCH_FLEE_SPEED} body heights/s")
        if ratio < s.SNATCH_ACCEL_RATIO:
            failed.append(f"acceleration ratio {ratio:.2f} < {s.SNATCH_ACCEL_RATIO}")
        if sep < s.SNATCH_SEPARATE:
            failed.append(f"separation {sep:.2f} < {s.SNATCH_SEPARATE}")
        if not away:
            failed.append("runner not moving away from the target")
        if not na < 0.5 * max(nb, 1e-6):
            failed.append("target moved along with the runner")
        return {"rules": rules, "score": score, "t": t_n, "failed": failed,
                "signals": {"target_track": int(ida), "runner_track": int(idb), "approach_closing_speed": r3(closing),
                            "approach_speed": r3(approach_speed), "flee_speed": r3(flee_speed), "acceleration_ratio": r3(ratio),
                            "separation": r3(sep), "diverging_angle_deg": r3(angle), "target_speed": r3(na)}}

    # --- second path: sustained contact, a burst of speed, then a takedown or a separation --------------------------------------
    def _contact_path(self, window: list) -> list:
        s = settings
        by_track: dict = {}
        for pf in window:
            for p in pf.persons:
                by_track.setdefault(p.track_id, []).append((pf.t, p, pf.frame_h))
        ids = sorted(by_track)
        out = []
        for i, ida in enumerate(ids):
            for idb in ids[i + 1:]:
                ta = {t: p for t, p, _h in by_track[ida]}
                tb = {t: p for t, p, _h in by_track[idb]}
                common = sorted(set(ta) & set(tb))
                if len(common) < 3:
                    continue
                dist = {t: float(np.linalg.norm(ta[t].center - tb[t].center)) / max(ta[t].h, tb[t].h, 1.0) for t in common}
                # longest contact run (distance <= SNATCH_CONTACT_DIST), bridging pose drop-outs of up to SNATCH_CONTACT_GAP_S
                runs, cur = [], None
                for t in common:
                    if dist[t] <= s.SNATCH_CONTACT_DIST:
                        if cur is not None and t - cur[1] <= s.SNATCH_CONTACT_GAP_S:
                            cur[1] = t
                        else:
                            cur = [t, t]
                            runs.append(cur)
                if not runs:
                    continue
                t0, t1 = max(runs, key=lambda r: r[1] - r[0])
                contact_s = t1 - t0
                if contact_s <= 0:
                    continue
                burst, burst_id = 0.0, None
                for tid, ser in ((ida, by_track[ida]), (idb, by_track[idb])):
                    for (ta_, pa, _), (tb_, pb, _) in zip(ser, ser[1:]):
                        dt = tb_ - ta_
                        if 0 < dt <= 0.6 and t0 - 0.5 <= tb_ <= t1 + 1.0:
                            sp = float(np.linalg.norm(pb.center - pa.center)) / max(pa.h, pb.h, 1.0) / dt
                            if sp > burst:
                                burst, burst_id = sp, tid
                ground, ground_id, ground_val = False, None, 0.0
                for tid, ser in ((ida, by_track[ida]), (idb, by_track[idb])):
                    for t, p, _h in ser:
                        if t0 <= t <= t1 + s.SNATCH_OUTCOME_WITHIN_S:
                            f = posture_features(p)
                            if f["aspect"] >= s.SNATCH_GROUND_ASPECT or (f["angle"] is not None and f["angle"] >= s.SNATCH_GROUND_ANGLE):
                                if f["aspect"] > ground_val:
                                    ground, ground_id, ground_val = True, tid, f["aspect"]
                sep = max((dist[t] for t in common if t1 < t <= t1 + s.SNATCH_OUTCOME_WITHIN_S), default=0.0)
                outcome = "ground" if ground else ("separation" if sep >= s.SNATCH_OUTCOME_SEP else None)
                cap = lambda v, thr: min(1.0, v / (1.5 * thr))
                outcome_cap = 1.0 if ground else cap(sep, s.SNATCH_OUTCOME_SEP)
                score = float(np.mean([cap(contact_s, s.SNATCH_CONTACT_S), cap(burst, s.SNATCH_BURST_SPEED), outcome_cap]))
                failed = []
                if contact_s < s.SNATCH_CONTACT_S:
                    failed.append(f"contact {contact_s:.1f} s < {s.SNATCH_CONTACT_S} s")
                if burst < s.SNATCH_BURST_SPEED:
                    failed.append(f"speed burst {burst:.2f} < {s.SNATCH_BURST_SPEED} body heights/s")
                if outcome is None:
                    failed.append(f"no takedown and separation {sep:.2f} < {s.SNATCH_OUTCOME_SEP}")
                detected = not failed and score >= self.threshold
                target = ground_id if ground else (ida if burst_id == idb else idb)
                signals = {"path": "contact_burst_outcome", "target_track": int(target), "other_track": int(idb if target == ida else ida),
                           "contact_s": r3(contact_s), "burst_speed": r3(burst), "outcome": outcome or "none", "separation": r3(sep)}
                if ground:
                    signals["ground_aspect"] = r3(ground_val)
                if not detected:
                    signals["blocked_by"] = failed or [f"score {score:.2f} < threshold {self.threshold}"]
                boxes = []
                if detected:
                    for tid in (ida, idb):
                        boxes.append(person_box(by_track[tid][-1][1], "snatch (experimental)", score))
                out.append(ActionResult(detected=detected, score=score, label="snatch", signals=signals, boxes=boxes))
        return out

    def detect(self, window: list) -> ActionResult:
        res = self._detect_approach(window)
        best = res
        for cand in self._contact_path(window):
            if (cand.detected, cand.score) > (best.detected, best.score):
                best = cand
        return best

    def _detect_approach(self, window: list) -> ActionResult:
        ids = sorted({p.track_id for pf in window for p in pf.persons})
        best, blocked = None, []
        for ida in ids:
            for idb in ids:
                if ida == idb:
                    continue
                res = self._pair(window, ida, idb)
                if res and "blocked" in res:
                    blocked.append(res["blocked"])
                elif res and (best is None or (res["rules"], res["score"]) > (best["rules"], best["score"])):
                    best = res
        if best is None:
            return ActionResult(detected=False, label="snatch", signals={"blocked_by": sorted(set(blocked))} if blocked else {"blocked_by": ["fewer than 2 tracked persons"]})
        detected = bool(best["rules"] and best["score"] >= self.threshold)
        if not detected:
            best["signals"]["blocked_by"] = best["failed"] or [f"score {best['score']:.2f} < threshold {self.threshold}"]
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
