"""DISCOVERY ONLY: find candidate demo clips (fall / violence / snatch) through the SerpApi YouTube engine's JSON.

Never downloads, fetches, converts or caches any video, and never touches YouTube pages: the only network call
is https://serpapi.com/search.json (engine=youtube). The page it writes (discovery/review.html) loads only
thumbnails. SERPAPI_KEY is read from WomenSafety/.env, never printed, logged or written to any output/cache file.

    python scripts/discover_clips.py [--max-calls 6] [--min-length 10] [--max-length 180] [--no-live]

Calls are allocated round-robin across the classes, highest-priority query first, up to --max-calls LIVE calls
per run. Responses are cached on disk (discovery/cache/), so reruns, and any query already answered, cost nothing.
"""
import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "discovery"
CACHE = OUT / "cache"
ENDPOINT = "https://serpapi.com/search.json"
TIMEOUT_S = 15

# priority order within each class (first = most important)
QUERIES = {
    "fall": ["CCTV person falls", "security camera slip and fall", "elderly fall caught on camera cctv"],
    "violence": ["CCTV street fight", "security camera fight", "cctv fight caught on camera"],
    "snatch": ["CCTV chain snatching", "mobile phone snatching cctv", "चेन स्नैचिंग सीसीटीवी", "chain snatching cctv jaipur"],
}
FLAG_WORDS = ["compilation", "top", "best", "news", "reaction", "dashcam", "dash cam", "pov", "prank", "staged", "movie", "scene",
              "game", "simulation", "funny", "fails", "shorts"]
BOOST_PHRASES = ["cctv", "security camera", "surveillance", "caught on camera"]
FIELDS = ["class", "video_id", "title", "channel", "link", "length_s", "published", "views", "thumbnail", "query", "flags", "score"]


class DiscoveryError(Exception):
    """Structured, key-free error."""
    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message = kind, message


def api_key() -> str:
    key = (dotenv_values(ROOT / ".env").get("SERPAPI_KEY") or os.environ.get("SERPAPI_KEY") or "").strip()
    if not key:
        raise DiscoveryError("no_key", "SERPAPI_KEY is unset in WomenSafety/.env")
    return key


def scrub(text: str, key: str) -> str:
    return text.replace(key, "[redacted]") if key else text


def cache_path(query: str) -> Path:
    return CACHE / (hashlib.sha1(("youtube|" + query).encode("utf-8")).hexdigest()[:16] + ".json")


def fetch(query: str, key: str, allow_live: bool, live_budget: list) -> tuple:
    """-> (response_dict, source) where source is "cache" or "live". Raises DiscoveryError (never containing the key)."""
    path = cache_path(query)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["response"], "cache"
    if not allow_live or live_budget[0] <= 0:
        raise DiscoveryError("call_cap", "not fetched: live call cap reached (cached queries are free; raise --max-calls to fetch it)")
    live_budget[0] -= 1
    try:
        r = requests.get(ENDPOINT, params={"engine": "youtube", "search_query": query, "api_key": key}, timeout=TIMEOUT_S)
    except requests.Timeout:
        raise DiscoveryError("timeout", f"no answer within {TIMEOUT_S} s")
    except requests.RequestException as exc:
        raise DiscoveryError("network", type(exc).__name__)
    try:
        body = r.json()
    except ValueError:
        raise DiscoveryError("bad_response", f"HTTP {r.status_code}, body was not JSON")
    if r.status_code != 200 or body.get("error"):
        raise DiscoveryError("serpapi_error", f"HTTP {r.status_code}: {scrub(str(body.get('error', 'no error text')), key)}")
    CACHE.mkdir(parents=True, exist_ok=True)
    clean = json.loads(scrub(json.dumps(body), key))   # defence in depth: the key must never reach the cache file
    path.write_text(json.dumps({"query": query, "response": clean}, ensure_ascii=False), encoding="utf-8")
    return clean, "live"


def parse_length(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parts = str(value).strip().split(":")
    if not all(p.isdigit() for p in parts) or not 1 <= len(parts) <= 3:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def parse_views(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"([\d.,]+)\s*([KMB]?)", str(value), re.I)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()])


def thumb_of(item: dict) -> str:
    t = item.get("thumbnail")
    if isinstance(t, dict):
        return t.get("static") or t.get("rich") or ""
    return t or ""


def flags_for(title: str, link: str, length_s) -> list:
    low = (title or "").lower()
    out = [w for w in FLAG_WORDS if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low)]
    if "/shorts/" in (link or "") and "shorts" not in out:
        out.append("shorts")
    if length_s is None:
        out.append("length_unknown")
    return out


def score_for(title: str, flags: list, length_s) -> int:
    low = (title or "").lower()
    s = 2 * sum(1 for p in BOOST_PHRASES if p in low)
    s -= sum(1 for f in flags if f != "length_unknown")
    if length_s is not None and 15 <= length_s <= 90:
        s += 1
    return s


def candidates_from(response: dict, cls: str, query: str, min_len: int, max_len: int) -> list:
    rows = []
    for item in response.get("video_results") or []:
        link = item.get("link") or ""
        m = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{6,})", link)
        vid = m.group(1) if m else None
        if not vid:
            continue
        length_s = parse_length(item.get("length"))
        if length_s is not None and not (min_len <= length_s <= max_len):
            continue
        title = item.get("title", "")
        flags = flags_for(title, link, length_s)
        ch = item.get("channel")
        rows.append({"class": cls, "video_id": vid, "title": title, "channel": ch.get("name", "") if isinstance(ch, dict) else (ch or ""),
                     "link": link, "length_s": "" if length_s is None else length_s, "published": item.get("published_date", ""),
                     "views": "" if parse_views(item.get("views")) is None else parse_views(item.get("views")),
                     "thumbnail": thumb_of(item), "query": query, "flags": ";".join(flags), "score": score_for(title, flags, length_s)})
    return rows


def write_review(by_class: dict) -> None:
    data = {c: rows for c, rows in by_class.items()}
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip candidates (review)</title><style>
:root{--bg:#0f1620;--fg:#e6edf5;--mut:#8b99b3;--card:#17202c;--line:#2a3646;--acc:#7FE3D0;--warn:#FFB829}
@media (prefers-color-scheme: light){:root{--bg:#f4f6f9;--fg:#18222e;--mut:#5b6b80;--card:#fff;--line:#d5dce6;--acc:#0a7f6d;--warn:#a86a00}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;padding:16px}
h1{font-size:20px}h2{margin-top:28px;border-bottom:1px solid var(--line);padding-bottom:6px;text-transform:capitalize}
.note{color:var(--warn);font-size:13px;max-width:900px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#000}.body{padding:8px 10px;display:flex;flex-direction:column;gap:3px;flex:1}
.t{font-weight:600}.m{color:var(--mut);font-size:12px}.f{color:var(--warn);font-size:12px}a{color:var(--acc)}label{margin-top:auto;padding-top:6px}
.card.on{outline:2px solid var(--acc)}</style></head><body>
<h1>Clip candidates: review only</h1>
<p class="note">Metadata from search results only; content and rights are NOT verified. Anything linked may depict real people being hurt. Nothing here is downloaded.
Tick "interesting" to mark clips for yourself (stored in this browser only).</p><div id="app"></div>
<script>
const DATA=__DATA__;const KEY="clip-review-interesting";let sel={};try{sel=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(sel))}catch(e){}};const fmt=s=>s===""?"?":Math.floor(s/60)+":"+String(s%60).padStart(2,"0");
const app=document.getElementById("app");
for(const [cls,rows] of Object.entries(DATA)){const h=document.createElement("h2");h.textContent=cls+" ("+rows.length+")";app.appendChild(h);
const g=document.createElement("div");g.className="grid";app.appendChild(g);
for(const r of rows){const c=document.createElement("div");c.className="card"+(sel[r.video_id]?" on":"");
const img=document.createElement("img");img.loading="lazy";img.referrerPolicy="no-referrer";img.alt="";if(r.thumbnail)img.src=r.thumbnail;c.appendChild(img);
const b=document.createElement("div");b.className="body";
const t=document.createElement("div");t.className="t";t.textContent=r.title;b.appendChild(t);
const m=document.createElement("div");m.className="m";m.textContent=[r.channel,fmt(r.length_s),r.views===""?"":r.views.toLocaleString()+" views",r.published].filter(Boolean).join(" \\u00b7 ");b.appendChild(m);
if(r.flags){const f=document.createElement("div");f.className="f";f.textContent="flags: "+r.flags.split(";").join(", ");b.appendChild(f)}
const a=document.createElement("a");a.href=r.link;a.target="_blank";a.rel="noopener noreferrer";a.textContent="open";b.appendChild(a);
const l=document.createElement("label");const cb=document.createElement("input");cb.type="checkbox";cb.checked=!!sel[r.video_id];
cb.onchange=()=>{if(cb.checked)sel[r.video_id]=1;else delete sel[r.video_id];c.classList.toggle("on",cb.checked);save()};
l.appendChild(cb);l.append(" interesting");b.appendChild(l);c.appendChild(b);g.appendChild(c)}}
</script></body></html>"""
    (OUT / "review.html").write_text(page.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")   # Hindi query text on a cp1252 console
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-calls", type=int, default=6, help="hard cap on LIVE SerpApi calls this run (default 6)")
    ap.add_argument("--min-length", type=int, default=10)
    ap.add_argument("--max-length", type=int, default=180)
    ap.add_argument("--no-live", action="store_true", help="use the cache only")
    args = ap.parse_args()
    try:
        key = api_key()
    except DiscoveryError as exc:
        print(exc)
        return 2
    OUT.mkdir(exist_ok=True)

    # round-robin over classes, priority order inside each class
    plan = []
    for rank in range(max(len(q) for q in QUERIES.values())):
        for cls, qs in QUERIES.items():
            if rank < len(qs):
                plan.append((cls, qs[rank]))
    budget = [args.max_calls]
    live_used, errors, skipped = 0, [], []
    by_class: dict = {c: {} for c in QUERIES}
    for cls, query in plan:
        before = budget[0]
        try:
            resp, source = fetch(query, key, not args.no_live, budget)
        except DiscoveryError as exc:
            (skipped if exc.kind == "call_cap" else errors).append((cls, query, str(exc)))
            live_used += before - budget[0]
            continue
        live_used += before - budget[0]
        got = candidates_from(resp, cls, query, args.min_length, args.max_length)
        for row in got:
            by_class[cls].setdefault(row["video_id"], row)   # dedupe by video_id (first/highest-priority query wins)
        print(f"[{cls}] {source:5s} {query!r}: {len(resp.get('video_results') or [])} results, {len(got)} kept")

    summary = {}
    for cls, rows in by_class.items():
        ordered = sorted(rows.values(), key=lambda r: (-r["score"], r["video_id"]))
        by_class[cls] = ordered
        with open(OUT / f"{cls}_candidates.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(ordered)
        summary[cls] = (len(ordered), sum(1 for r in ordered if r["flags"].replace("length_unknown", "").strip(";")))
    write_review(by_class)
    print(f"\nlive SerpApi calls used this run: {live_used} (cap {args.max_calls})")
    for cls, (n, fl) in summary.items():
        print(f"{cls:9s} candidates={n:3d} flagged={fl:3d}")
    for cls, q, msg in errors:
        print(f"ERROR [{cls}] {q!r}: {msg}")
    for cls, q, msg in skipped:
        print(f"not run [{cls}] {q!r}: {msg}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
