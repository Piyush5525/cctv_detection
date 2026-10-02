"""Synthetic pose sequences for the action-detector tests (no model, no video: just geometry).

A person is a 17-keypoint COCO skeleton of height H pixels built from: hip position, torso angle from vertical
(0 = upright, 90 = horizontal), a leg style and optional arm swing. Sequences are sampled at 4 Hz like the
default shared pose pass.
"""
import math

import numpy as np

from api.services.action_detectors.base import PersonPose, PoseFrame

DT = 0.25
GROUND = 400.0
H = 200.0


def skeleton(hx, hy, theta, h=H, legs="stand", d=1.0, arm=0.0):
    """17x3 keypoints. theta = torso angle (deg). legs: stand | sit | crouch | lie. arm = limb swing phase in [-1, 1]."""
    th = math.radians(theta)
    u = np.array([math.sin(th) * d, -math.cos(th)])
    hip = np.array([hx, hy])
    sho = hip + 0.30 * h * u
    head = sho + 0.15 * h * u
    if legs == "stand":
        knee, ank = hip + np.array([0, 0.25 * h]), hip + np.array([0, 0.5 * h])
    elif legs == "sit":
        knee, ank = hip + np.array([0.25 * h * d, 0]), hip + np.array([0.25 * h * d, 0.25 * h])
    elif legs == "crouch":
        knee, ank = hip + np.array([0.2 * h * d, 0.1 * h]), hip + np.array([0.0, 0.25 * h])
    else:  # lie: legs continue the body line
        knee, ank = hip - 0.25 * h * u, hip - 0.5 * h * u
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    for i in (0, 1, 2, 3, 4):
        kp[i, :2] = head
    for i in (5, 6):
        kp[i, :2] = sho + np.array([(-1 if i == 5 else 1) * 0.04 * h, 0])
    for i in (11, 12):
        kp[i, :2] = hip + np.array([(-1 if i == 11 else 1) * 0.03 * h, 0])
    for i in (13, 14):
        kp[i, :2] = knee
    for i in (15, 16):
        kp[i, :2] = ank
    swing = arm * 0.3 * h
    kp[7, :2] = sho + np.array([-0.05 * h + swing, 0.12 * h])
    kp[8, :2] = sho + np.array([0.05 * h - swing, 0.12 * h])
    kp[9, :2] = sho + np.array([-0.05 * h + 2 * swing, 0.25 * h - abs(swing)])
    kp[10, :2] = sho + np.array([0.05 * h - 2 * swing, 0.25 * h - abs(swing)])
    return kp


def person(tid, kp):
    xs, ys = kp[:, 0], kp[:, 1]
    pad = 0.04 * H
    return PersonPose(track_id=tid, box=(float(xs.min() - pad), float(ys.min() - pad), float(xs.max() + pad), float(ys.max() + pad)), kp=kp)


def frames(persons_per_step, t0=0.0, dt=DT):
    return [PoseFrame(t=t0 + i * dt, persons=ps, frame_h=480, frame_w=640, frame=np.zeros((480, 640, 3), np.uint8)) for i, ps in enumerate(persons_per_step)]


def run(detector, pfs, window_s=None):
    """Feed the frames one by one like the engine does; returns the list of ActionResults."""
    win_s = window_s or detector.window_s
    out = []
    for i, pf in enumerate(pfs):
        win = [x for x in pfs[:i + 1] if pf.t - x.t <= win_s + 1e-6]
        out.append(detector.detect(win) if pf.persons else detector.idle())
    return out


def stand_frames(n, x=300.0):
    return [[person(1, skeleton(x, GROUND - 0.5 * H, 0))] for _ in range(n)]


# --- fall scenarios --------------------------------------------------------------
def true_fall(stay_s=4.0):
    seq = stand_frames(8)
    seq.append([person(1, skeleton(300, GROUND - 0.42 * H, 50, legs="stand"))])               # tipping over
    seq.append([person(1, skeleton(300, GROUND - 0.08 * H, 88, legs="lie"))])                  # on the ground
    seq += [[person(1, skeleton(300, GROUND - 0.08 * H, 88, legs="lie"))] for _ in range(int(stay_s / DT))]
    return seq


def fall_then_get_up():
    seq = true_fall(stay_s=1.0)                                                                # down only 1 s
    seq.append([person(1, skeleton(300, GROUND - 0.3 * H, 40, legs="crouch"))])
    seq += stand_frames(6)
    return seq


def sitting_down():
    seq = stand_frames(8)
    for k in range(1, 7):                                                                      # hips lower 0.25H over 1.5 s, torso upright
        seq.append([person(1, skeleton(300 + 6 * k, GROUND - 0.5 * H + 0.042 * H * k, 0, legs="sit"))])
    seq += [[person(1, skeleton(336, GROUND - 0.25 * H, 0, legs="sit"))] for _ in range(16)]
    return seq


def bending():
    seq = stand_frames(8)
    for th in (30, 60, 80):                                                                    # bends forward over 0.75 s, hips fixed
        seq.append([person(1, skeleton(300, GROUND - 0.5 * H, th, legs="stand"))])
    seq += [[person(1, skeleton(300, GROUND - 0.5 * H, 80, legs="stand"))] for _ in range(4)]  # holds 1 s
    for th in (60, 30, 0):
        seq.append([person(1, skeleton(300, GROUND - 0.5 * H, th, legs="stand"))])
    seq += stand_frames(6)
    return seq


def bending_deep_hold():
    """Bends to ~88 degrees (hips drop only 0.1H, e.g. knees slightly bent) and HOLDS for 3 s (picking something up):
    head drop, speed, flip-to-horizontal torso and stay-down all pass -- only the hip-drop rule rejects it."""
    seq = stand_frames(8)
    for th, drop in ((30, 0.03), (60, 0.07), (88, 0.1)):
        seq.append([person(1, skeleton(300, GROUND - (0.5 - drop) * H, th, legs="stand"))])
    seq += [[person(1, skeleton(300, GROUND - 0.4 * H, 88, legs="stand"))] for _ in range(12)]
    return seq


def lying_down_on_purpose():
    seq = stand_frames(8)
    for k in range(1, 17):                                                                     # 4 s: torso 0 -> 90, hips 0.5H -> 0.08H
        f = k / 16.0
        seq.append([person(1, skeleton(300, GROUND - (0.5 - 0.42 * f) * H, 90 * f, legs="stand" if f < 0.5 else "lie"))])
    seq += [[person(1, skeleton(300, GROUND - 0.08 * H, 90, legs="lie"))] for _ in range(16)]
    return seq


def crouching():
    seq = stand_frames(8)
    for k in range(1, 4):                                                                      # deep squat over 0.75 s, torso ~upright
        seq.append([person(1, skeleton(300, GROUND - (0.5 - 0.08 * k) * H, 10, legs="crouch"))])
    seq += [[person(1, skeleton(300, GROUND - 0.26 * H, 10, legs="crouch"))] for _ in range(16)]
    return seq


def tiny_far_person_fall():
    h = 40.0   # 40 px tall in a 480 px frame: below ACTION_MIN_PERSON_H_FRAC; the engine drops it before detectors see it
    return h


# --- violence scenarios ----------------------------------------------------------
def pair_sequence(n, gap, swing, still=False):
    """Two persons `gap` px apart (centres), arm/leg swing phase alternating unless still."""
    seq = []
    for i in range(n):
        a = 0.0 if still else (1.0 if i % 2 == 0 else -1.0) * swing
        seq.append([person(1, skeleton(300, GROUND - 0.5 * H, 0, arm=a)), person(2, skeleton(300 + gap, GROUND - 0.5 * H, 0, d=-1, arm=-a))])
    return seq


# --- snatch scenarios ------------------------------------------------------------
def box_person(tid, cx, cy, h=H):
    kp = np.zeros((17, 3))
    return PersonPose(track_id=tid, box=(cx - 0.17 * h, cy - 0.5 * h, cx + 0.17 * h, cy + 0.5 * h), kp=kp)


def approach_and_flee(flee_speed_h=4.0, approach_speed_h=1.0):
    """Target A stands still at x=600. Runner B walks in at ~1 body height/s, touches, then sprints away."""
    seq, t = [], 0.0
    xb = 100.0
    step = approach_speed_h * H * DT
    for _ in range(5):                       # far away, walking in: ~2.2H -> contact
        seq.append([box_person(1, 600, 300), box_person(2, xb, 300)])
        xb += step * 1.6                     # closing: the runner covers ground quickly
    while xb < 600 - 0.6 * H:                # reach contact distance
        seq.append([box_person(1, 600, 300), box_person(2, xb, 300)]); xb += step * 1.6
    seq.append([box_person(1, 600, 300), box_person(2, 600 - 0.6 * H, 300)])
    x = 600 - 0.6 * H
    for _ in range(8):                       # sprint away (and slightly sideways)
        x -= flee_speed_h * H * DT
        seq.append([box_person(1, 600, 300), box_person(2, x, 300 + 20)])
    return seq


def walk_past(speed_h=1.2):
    """Two people walking towards each other and past: same speed before and after."""
    seq, step = [], speed_h * H * DT
    for k in range(26):
        seq.append([box_person(1, 60 + k * step, 300), box_person(2, 760 - k * step, 310)])
    return seq
