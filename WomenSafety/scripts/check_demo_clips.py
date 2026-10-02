"""Checks the three demo clips: data/demo/{fall,violence,snatch}.mp4 exist, are readable, are 10-60 s long, and
have a filled-in row in data/demo/SOURCES.md. Prints every problem; exit code 1 if any.

    python scripts/check_demo_clips.py
"""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
CLIPS = ["fall", "violence", "snatch"]
MIN_S, MAX_S = 10.0, 60.0


def sources_rows() -> dict:
    """file name -> list of cell values, for the rows of SOURCES.md's table."""
    path = DEMO / "SOURCES.md"
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0].endswith(".mp4"):
            rows[cells[0]] = cells
    return rows


def check() -> list:
    problems = []
    rows = sources_rows()
    if not (DEMO / "SOURCES.md").exists():
        problems.append("data/demo/SOURCES.md is missing")
    for name in CLIPS:
        fname = f"{name}.mp4"
        path = DEMO / fname
        if not path.exists():
            problems.append(f"{fname}: MISSING")
        else:
            cap = cv2.VideoCapture(str(path))
            ok = cap.isOpened() and cap.read()[0]
            fps, frames = cap.get(cv2.CAP_PROP_FPS) or 0.0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            cap.release()
            if not ok:
                problems.append(f"{fname}: not readable")
            elif fps <= 0 or frames <= 0:
                problems.append(f"{fname}: cannot read fps / frame count")
            else:
                dur = frames / fps
                if not MIN_S <= dur <= MAX_S:
                    problems.append(f"{fname}: length {dur:.1f} s is outside {MIN_S:.0f}-{MAX_S:.0f} s")
        row = rows.get(fname)
        if row is None:
            problems.append(f"{fname}: no row in data/demo/SOURCES.md")
        elif not all(row[1:5]):
            problems.append(f"{fname}: SOURCES.md row is incomplete (class, source, permission note and date obtained must be filled)")
    return problems


if __name__ == "__main__":
    found = check()
    if found:
        print("Demo clip check: PROBLEMS")
        for p in found:
            print("  -", p)
        sys.exit(1)
    print("Demo clip check: OK (all three clips present, readable, 10-60 s, with a SOURCES.md row)")
