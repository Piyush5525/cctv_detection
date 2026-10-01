"""ARCHIVED — already ran, not part of the live product. One-time migration: applies Phase 1 Step 1.2 fixes to the EXISTING
279-record dataset (already live in the in-memory API), producing
scraped_incidents.json as the new source of truth. This is not a
scraper -- it re-processes records already created by the old scraper
version, since those all carry a fixed confidence=0.5 and were never
run through the new relevance/recency/category/dedup pipeline.

Backs up the current live dataset before making any change.
"""
import json
import re
import sys
import io
import hashlib
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from scrape_pipeline import (  # noqa: E402
    ScrapedIncident, check_relevance, classify_category, is_stale,
    normalize_url, backup_data_file, log_dropped, save_store,
    SCRAPED_INCIDENTS_FILE, MAX_AGE_DAYS, INDIA_BOUNDS,
)

API_BASE = "http://localhost:8000/api/v1"


def headline_of(inc):
    notes = inc.get("detection_data", {}).get("notes", "")
    return notes.split(" (source:")[0]


def source_url_of(inc):
    notes = inc.get("detection_data", {}).get("notes", "")
    m = re.search(r"https?://\S+$", notes)
    return m.group(0).rstrip(")") if m else None


def source_name_of(inc):
    notes = inc.get("detection_data", {}).get("notes", "")
    m = re.search(r"source: ([^,]+),", notes)
    return m.group(1) if m else "unknown"


def city_of(addr):
    return (addr or "").split(",")[0].strip().lower()


def date_of_str(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except Exception:
        return None


STOPWORDS = {"the", "a", "an", "in", "on", "at", "of", "to", "and", "for", "with",
             "after", "as", "is", "was", "were", "by", "from", "no", "video", "watch",
             "caught", "camera", "cctv", "news", "over", "breaks", "out", "up", "off"}


def token_set(t):
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return {w for w in t.split() if w not in STOPWORDS and len(w) > 1}


def token_set_ratio(a, b):
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def fetch_all_live():
    all_incs = []
    page = 1
    while True:
        r = requests.get(f"{API_BASE}/incidents", params={"page": page, "page_size": 100}, timeout=15).json()
        all_incs.extend(r["incidents"])
        if page >= r.get("total_pages", 1):
            break
        page += 1
    return all_incs


def main():
    print("Fetching live dataset...")
    live = fetch_all_live()
    print(f"Loaded {len(live)} live incidents")

    backup_data_file(Path("incidents_backup.json"))  # keep existing backup convention too
    with open("incidents_backup.json", "w", encoding="utf-8") as f:
        json.dump(live, f, ensure_ascii=False, indent=2)

    stats = {
        "total_before": len(live),
        "dropped_stale": 0, "dropped_not_incident": 0, "dropped_trend_roundup": 0,
        "dropped_legal_dispute": 0, "dropped_statistics": 0, "dropped_opinion": 0,
        "dropped_awareness_campaign": 0, "dropped_no_concrete_event": 0,
        "dropped_multi_topic_digest": 0, "dropped_alleges_unconfirmed": 0,
        "dropped_duplicate": 0, "dropped_invalid_schema": 0,
        "merged_clusters": 0,
    }

    # ---- Step A: build ScrapedIncident candidates from live records ----
    candidates = []
    for inc in live:
        title = headline_of(inc)
        url = source_url_of(inc)
        if not url:
            log_dropped(inc["incident_id"], title, "invalid_schema", detail="no source url")
            stats["dropped_invalid_schema"] += 1
            continue

        rec_id = hashlib.sha1(normalize_url(url).encode()).hexdigest()

        # Relevance
        reason = check_relevance(title)
        if reason:
            log_dropped(rec_id, title, reason)
            stats[f"dropped_{reason}"] = stats.get(f"dropped_{reason}", 0) + 1
            continue

        # Category (controlled vocabulary + deceptive-framing override)
        category = classify_category(title)
        if category == "other":
            # Keep "other" as a valid controlled-vocabulary value per spec
            # (road_accident|fire|assault|snatching|other) -- not dropped,
            # just uncertain. Matches the already-existing 'other'/'leopard'
            # /'school girl's death' records reviewed manually in the
            # earlier session.
            pass

        # Recency
        ts = inc.get("timestamp")
        stale, age_days = (True, -1) if not ts else is_stale(ts)
        if stale:
            log_dropped(rec_id, title, "stale", age_days=age_days)
            stats["dropped_stale"] += 1
            continue

        loc = inc.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        addr = loc.get("address", "")
        is_unspecified = "unspecified" in addr.lower()

        if is_unspecified:
            lat, lng, precision = None, None, "unknown"
        elif lat is not None and lng is not None:
            in_bounds = INDIA_BOUNDS[0] <= lat <= INDIA_BOUNDS[1] and INDIA_BOUNDS[2] <= lng <= INDIA_BOUNDS[3]
            if not in_bounds:
                log_dropped(rec_id, title, "invalid_schema", detail=f"coords outside India: {lat},{lng}")
                stats["dropped_invalid_schema"] += 1
                continue
            # Existing records only ever resolved to city/area level (see
            # Phase 1 audit) -- being honest about that rather than
            # claiming "exact" precision no geocode call here actually
            # achieved.
            precision = "city"
        else:
            lat, lng, precision = None, None, "unknown"

        try:
            rec = ScrapedIncident(
                id=rec_id,
                title=title,
                category=category,
                description="",
                source_name=source_name_of(inc),
                source_url=url,
                published_at=ts,
                location_text=addr or "unknown",
                latitude=lat,
                longitude=lng,
                location_precision=precision,
                image_url=inc.get("thumbnail_path"),
                fetched_at=inc.get("created_at") or datetime.now(timezone.utc).isoformat(),
                verified=False,
                confidence=None,  # the fixed 0.5 from the old scraper is erased here
            )
        except Exception as e:
            log_dropped(rec_id, title, "invalid_schema", detail=str(e))
            stats["dropped_invalid_schema"] += 1
            continue

        candidates.append((rec, inc["incident_id"], date_of_str(ts)))

    print(f"\nAfter relevance + recency + schema filtering: {len(candidates)} candidates")

    # ---- Step B: strict dedup (same city+category, +/-3 days, token-set-ratio >= 0.6) ----
    buckets = {}
    for rec, old_id, d in candidates:
        key = (city_of(rec.location_text), rec.category)
        buckets.setdefault(key, []).append((rec, old_id, d))

    kept = []
    used_ids = set()
    for key, group in buckets.items():
        for i, (a_rec, a_old, a_date) in enumerate(group):
            if a_rec.id in used_ids:
                continue
            cluster = [(a_rec, a_old, a_date)]
            for (b_rec, b_old, b_date) in group[i + 1:]:
                if b_rec.id in used_ids:
                    continue
                if a_date and b_date and abs((a_date - b_date).days) > 3:
                    continue
                if token_set_ratio(a_rec.title, b_rec.title) >= 0.6:
                    cluster.append((b_rec, b_old, b_date))
                    used_ids.add(b_rec.id)
            if len(cluster) > 1:
                used_ids.add(a_rec.id)
                # Keep the most complete record: prefers a real image_url and
                # a longer title (proxy for "more detail").
                cluster.sort(key=lambda t: (bool(t[0].image_url), len(t[0].title)), reverse=True)
                keeper_rec, keeper_old, _ = cluster[0]
                merged_urls = [c[0].source_url for c in cluster[1:]]
                keeper_rec.description = f"merged_source_urls: {merged_urls}"
                kept.append((keeper_rec, keeper_old))
                stats["merged_clusters"] += 1
                for dropped_rec, dropped_old, _ in cluster[1:]:
                    log_dropped(dropped_rec.id, dropped_rec.title, "duplicate", merged_into=keeper_rec.id)
                    stats["dropped_duplicate"] += 1
            else:
                kept.append((a_rec, a_old))

    print(f"After dedup: {len(kept)} final records ({stats['merged_clusters']} clusters merged)")

    # ---- Step C: write scraped_incidents.json (source of truth) ----
    store = {rec.id: json.loads(rec.model_dump_json()) for rec, _ in kept}
    save_store(store)
    print(f"Wrote {len(store)} records to {SCRAPED_INCIDENTS_FILE}")

    # ---- Step D: reconcile the LIVE in-memory API to match ----
    # Delete every live incident not in the kept set, keep the rest as-is
    # except their confidence, which must become null.
    kept_old_ids = {old_id for _, old_id in kept}
    deleted = 0
    for inc in live:
        if inc["incident_id"] not in kept_old_ids:
            resp = requests.delete(f"{API_BASE}/incidents/{inc['incident_id']}", timeout=15)
            if resp.status_code in (200, 204):
                deleted += 1

    print(f"Deleted {deleted} live incidents (dropped by relevance/recency/dedup/schema filters)")

    # confidence can't be patched (IncidentUpdate has no such field) --
    # recreate each kept incident with confidence=None, delete the old one.
    recreated = 0
    failed = 0
    for inc in live:
        if inc["incident_id"] not in kept_old_ids:
            continue
        if inc.get("confidence") is None:
            continue  # already null, nothing to do
        payload = {
            "incident_type": inc["incident_type"],
            "severity": inc["severity"],
            "confidence": None,
            "timestamp": inc["timestamp"],
            "location": inc["location"],
            "detection_data": inc.get("detection_data", {}),
            "thumbnail_path": inc.get("thumbnail_path"),
        }
        r_create = requests.post(f"{API_BASE}/incidents", json=payload, timeout=15)
        if r_create.status_code in (200, 201):
            r_del = requests.delete(f"{API_BASE}/incidents/{inc['incident_id']}", timeout=15)
            if r_del.status_code in (200, 204):
                recreated += 1
            else:
                failed += 1
        else:
            failed += 1
            print(f"FAILED to recreate {inc['incident_id']}: {r_create.status_code} {r_create.text[:150]}")

    print(f"Recreated {recreated} incidents with confidence=null ({failed} failed)")

    print("\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
