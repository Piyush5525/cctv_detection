"""Render showcase candidates as a reviewable local HTML gallery (demo/candidates.html).

    python scripts/build_candidates_gallery.py [--db backups/incidents_candidates_<ts>.db]

Without --db it reads the current incidents DB (source=test_replay), as before. Each card shows: the best frame with the
detector overlay (box / skeleton), the clip name and time range, category, peak score, frames confirmed, the signals that
fired (action detectors), the candidate id, an EXPERIMENTAL badge where it applies, and "weak" marks (peak under 0.6, or an
event shorter than 1 s). Sorted by peak score. Only categories whose detector actually fired can appear: nothing is padded.
The page loads only local files; images and clips are read from evidence/ (git-ignored).
"""
import argparse
import html
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

LABELS = {"road_accident": "Crash", "fire": "Fire", "fall": "Fall", "assault": "Violence", "snatching": "Snatching"}
WEAK_CONFIDENCE, WEAK_SECONDS = 0.6, 1.0


def rel(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except Exception:
        return ""


def load_rows(db_path):
    if db_path:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return [json.loads(r[0]) for r in con.execute("SELECT data FROM incidents WHERE source='test_replay'")]
        finally:
            con.close()
    from api.services import incident_service_v2 as incidents
    return incidents.list_incidents(source="test_replay")


def card(item):
    det, ev = item["detection"], item["evidence"]
    conf = det["peak_confidence"]
    note = ev.get("note") or ""
    m = re.search(r"replay of (\S+) \(([^)]*)\)", note)
    clip, span = (m.group(1), m.group(2)) if m else ("unknown clip", "")
    weak_reasons = []
    if conf < WEAK_CONFIDENCE:
        weak_reasons.append("low peak score")
    if item.get("duration_s", 0) < WEAK_SECONDS:
        weak_reasons.append("very short event")
    experimental = bool(det.get("experimental"))
    signals = det.get("signals") or {}
    sig_html = "".join(f"<li>{html.escape(str(k).replace('_', ' '))}: {html.escape(str(v))}</li>" for k, v in signals.items())
    img = rel(ev.get("annotated_frame_path") or ev["best_frame_path"])
    clip_path = rel(ev.get("clip_path") or "")
    return conf, f'''<article class="{'weak' if weak_reasons else ''}"><img src="../{img}" alt="{html.escape(item['incident_id'])}">
<h2>{html.escape(LABELS.get(item['category'], item['category']))}{' <span class="exp">EXPERIMENTAL</span>' if experimental else ''}</h2>
<p><b>Clip:</b> {html.escape(clip)}<br><b>Time range:</b> {html.escape(span)}</p>
<p><b>Peak score:</b> {conf:.2f} (threshold {det['threshold_applied']})<br><b>Frames confirmed:</b> {html.escape(det['frames_confirmed'])}<br><b>Detector:</b> {html.escape(det['detector_source'])}</p>
{('<ul class="sig">' + sig_html + '</ul>') if sig_html else ''}
<p><b>Candidate id:</b> <code>{item['incident_id']}</code></p>
<p>{('<b class="warn">WEAK: ' + ', '.join(weak_reasons) + '. Review carefully.</b>') if weak_reasons else 'Review for true positive'}</p>
{f'<a href="../{clip_path}">Open clip</a>' if clip_path else ''}</article>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--out", default=str(ROOT / "demo" / "candidates.html"))
    args = ap.parse_args()
    if args.db:
        os.environ["INCIDENTS_DB_PATH"] = str(Path(args.db).resolve())
    rows = load_rows(Path(args.db).resolve() if args.db else None)
    cards = sorted((card(r) for r in rows), key=lambda x: -x[0])
    by_cat = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    summary = ", ".join(f"{LABELS.get(c, c)}: {n}" for c, n in sorted(by_cat.items())) or "none"
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text(f'''<!doctype html><meta charset="utf-8"><title>Showcase candidates</title><style>
:root{{--bg:#10141c;--fg:#eee;--card:#1e2733;--acc:#84c6ff;--warn:#c88b22}}@media (prefers-color-scheme: light){{:root{{--bg:#f4f6f9;--fg:#18222e;--card:#fff;--acc:#0b63b8;--warn:#a86a00}}}}
body{{font-family:system-ui;background:var(--bg);color:var(--fg);margin:2rem}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}}
article{{background:var(--card);padding:1rem;border-radius:8px}}article.weak{{border:2px solid var(--warn)}}img{{width:100%;aspect-ratio:16/9;object-fit:cover;background:#000}}
code{{font-size:.75rem}}a{{color:var(--acc)}}.exp{{font-size:.65rem;border:1px dashed var(--warn);color:var(--warn);padding:1px 5px;border-radius:5px;vertical-align:middle}}
.warn{{color:var(--warn)}}.sig{{font-size:.75rem;padding-left:1.1rem}}</style>
<h1>Showcase candidates</h1>
<p>Real detections from replaying only the provided clips; sorted by peak score; {len(rows)} candidates ({html.escape(summary)}). Nothing is padded: a category appears only if its detector actually fired.
A detection can come from another detector than the clip's own class (the clip name is shown): please judge each from the image and the clip. Select only genuine true positives.</p>
<main>{''.join(c for _, c in cards) or '<p>No candidates: no detector fired.</p>'}</main>''', encoding="utf-8")
    print(f"gallery={out} candidates={len(rows)} ({summary}) weak={sum('weak' in c for _, c in cards)}")


if __name__ == "__main__":
    main()
