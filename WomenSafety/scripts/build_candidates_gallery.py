"""Render existing test-replay incidents as a reviewable local HTML gallery."""
import html
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from api.services import incident_service_v2 as incidents

ROOT = Path(__file__).parent.parent
def rel(path):
    try: return Path(path).resolve().relative_to(ROOT).as_posix()
    except Exception: return ""
def main():
    rows = incidents.list_incidents(source="test_replay")
    rows.sort(key=lambda item: item["detection"]["peak_confidence"], reverse=True)
    cards = []
    for item in rows:
        det, evidence = item["detection"], item["evidence"]; confidence = det["peak_confidence"]
        weak = confidence < .6
        cards.append(f'''<article class="{'weak' if weak else ''}"><img src="../{rel(evidence['thumbnail_path'])}" alt="{html.escape(item['incident_id'])}"><h2>{html.escape(item['category'])}</h2><p><b>Candidate id:</b> <code>{item['incident_id']}</code></p><p>Peak confidence: {confidence:.2f}<br>Frames confirmed: {html.escape(det['frames_confirmed'])}</p><p>{'<b>REVIEW: low confidence</b>' if weak else 'Candidate: review for true positive'}</p><a href="../{rel(evidence['clip_path'])}">Open clip</a></article>''')
    output = ROOT / "demo" / "candidates.html"; output.parent.mkdir(exist_ok=True)
    output.write_text(f'''<!doctype html><title>Showcase candidates</title><style>body{{font-family:system-ui;background:#10141c;color:#eee;margin:2rem}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}}article{{background:#1e2733;padding:1rem;border-radius:8px}}article.weak{{border:2px solid #c88b22}}img{{width:100%;height:180px;object-fit:cover}}code{{font-size:.75rem}}a{{color:#84c6ff}}</style><h1>Showcase candidates</h1><p>Sorted by peak confidence. Select only genuine true positives.</p><main>{''.join(cards) or '<p>No test-replay candidates.</p>'}</main>''', encoding="utf-8")
    print(f"gallery={output} candidates={len(rows)} strong={sum(x['detection']['peak_confidence'] >= .6 for x in rows)}")
if __name__ == "__main__": main()
