"""ARCHIVED, NOT PART OF THE PRODUCT -- see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase. The product is now CCTV-only; the news-scrape
scripts that import this module are themselves archived. Left in the
repo, unmodified, in case a future phase reintroduces a clearly-labeled
news feed.

Shared pipeline for the news-scraping scripts: schema, relevance
filter, duplicate detection, category classification, and geocoding
hygiene (rate-limited, cached, bounding-box-checked). Both
fetch_india_incidents.py and fetch_jaipur_incidents.py import from here
so the rules are defined once, not duplicated per-script.

Source of truth for scraped records is scraped_incidents.json (in the
WomenSafety root), keyed by a stable id = sha1(normalized_source_url).
Re-running a scraper must not create duplicate entries and must never
overwrite a record whose `verified` field is already true.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

import requests
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).parent.parent
SCRAPED_INCIDENTS_FILE = ROOT / "scraped_incidents.json"
DROPPED_LOG_FILE = ROOT / "dropped_log.jsonl"
BACKUPS_DIR = ROOT / "backups"
GEOCODE_CACHE_FILE = ROOT / "evidence_clips" / ".geocode_cache.json"

MAX_AGE_DAYS = 365  # config value per spec; records older than this are dropped as "stale"

# India's approximate bounding box (lat_min, lat_max, lng_min, lng_max).
# Any geocode result outside this is rejected outright, never stored.
INDIA_BOUNDS = (6.0, 36.0, 68.0, 98.0)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ScrapedIncident(BaseModel):
    id: str  # sha1(normalized_source_url)
    title: str
    category: Literal["road_accident", "fire", "assault", "snatching", "women_safety", "fall", "other"]
    description: str = ""
    source_name: str
    source_url: str
    published_at: str  # ISO-8601 UTC
    location_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_precision: Literal["exact", "area", "city", "unknown"] = "unknown"
    image_url: Optional[str] = None
    fetched_at: str  # ISO-8601 UTC, set at scrape time
    origin: Literal["news_scrape"] = "news_scrape"
    verified: bool = False
    confidence: Optional[float] = None  # null until a real CV model scores it

    @field_validator("latitude")
    @classmethod
    def _lat_in_bounds(cls, v):
        if v is not None and not (INDIA_BOUNDS[0] <= v <= INDIA_BOUNDS[1]):
            raise ValueError(f"latitude {v} outside India bounding box")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng_in_bounds(cls, v):
        if v is not None and not (INDIA_BOUNDS[2] <= v <= INDIA_BOUNDS[3]):
            raise ValueError(f"longitude {v} outside India bounding box")
        return v

    @field_validator("published_at", "fetched_at")
    @classmethod
    def _valid_iso8601(cls, v):
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ---------------------------------------------------------------------------
# URL normalization (strip tracking params, lowercase host, no trailing slash)
# ---------------------------------------------------------------------------
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                    "fbclid", "gclid", "ref", "ito", "cmpid", "sourceid", "amp"}


def normalize_url(url: str) -> str:
    p = urlparse(url)
    q = parse_qs(p.query)
    q = {k: v for k, v in q.items() if k.lower() not in TRACKING_PARAMS}
    new_query = urlencode(q, doseq=True)
    path = p.path.rstrip("/")
    return urlunparse((p.scheme, p.netloc.lower(), path, "", new_query, ""))


def resolve_redirects(url: str, timeout: int = 10) -> str:
    """Follows redirects with a HEAD request to get the final canonical URL.
    Falls back to the original URL on any failure (network error, timeout,
    server refusing HEAD) rather than raising -- a scrape run should not
    die because one outlet's server is slow."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; WomenSafety-research-bot/1.0)"})
        return resp.url
    except Exception:
        return url


def make_id(source_url: str, resolve: bool = True) -> str:
    final_url = resolve_redirects(source_url) if resolve else source_url
    return hashlib.sha1(normalize_url(final_url).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Relevance filter -- tuned against the live 279-record dataset (see
# CHANGELOG.md Phase 1 entry for the false-positive iterations this went
# through). A headline whose OWN lead clause reports a direct event verb
# is never flagged as legal_dispute, even if a court/police follow-up is
# mentioned later in the same headline.
# ---------------------------------------------------------------------------
DIRECT_EVENT_VERB_LEAD = re.compile(
    r"^.{0,60}\b(assaulted|attacked|stabbed|shot|killed|crashed|collided|caught fire|"
    r"gutted|robbed|snatched|molested|raped)\b",
    re.IGNORECASE,
)

RELEVANCE_FLAG_PATTERNS = [
    ("opinion", re.compile(
        r"^opinion:|^editorial:|\bopinion\b|\beditorial\b|\bcolumn:|\bwhy \w+ (should|must|needs)\b|"
        r"\bviewpoint\b|\bperspective:|\bcommentary\b",
        re.IGNORECASE)),
    ("statistics", re.compile(
        r"\bNCRB\b|\bcrime (rate|chart|index|data)\b|\bsafety index\b|\btop(s)? (the |in )?(list|chart|metro|city|cities)\b|"
        r"\branks? (\d|second|third|first|top|low|high)\b|\bstatewide\b|\breports? (highest|lowest|rise|surge|increase)\b|"
        r"\b\d+% (rise|increase|drop|decline|surge)\b|\bstudy (finds|shows|reveals)\b|\bsurvey\b",
        re.IGNORECASE)),
    ("legal_dispute", re.compile(
        r"\bcourt (rejects|seeks a report|orders a probe)\b|\bSC (seeks|to examine) (a |the )?(petition|plea)\b|"
        r"\bSupreme Court (seeks|to examine)\b|\bhigh court seeks (a )?report\b|"
        r"\bplea alleging\b|\bpetition alleging\b|\bbail (granted|rejected)\b|"
        r"\bacquits?\b|\bconvict(ed|ion)?\b|\bverdict\b|\bsentenced to\b.{0,20}\bprison\b|"
        r"\bchallenges? .{0,15}(denial|police denial)\b|\brejects (surrender|closure) (plea|report)\b",
        re.IGNORECASE)),
    ("trend_roundup", re.compile(
        r"\bput(s)? .* back into focus\b|\bcases? (back )?in(to)? focus\b|\bcrime files\b|"
        r"\bgrows? (brazen|violent)\b|\bpattern of\b|\bseries of\b|\bwave of\b|"
        r"\ba look (at|back)\b|\bblind spots?\b.*\balarm bells\b|\bring alarm bells\b|"
        r"\band more$|\bround-?up\b|\bdigest\b",
        re.IGNORECASE)),
    ("awareness_campaign", re.compile(
        r"\bawareness\b|\bcampaign\b|\bself-defen[cs]e\b|\bworkshop\b|\bsensitization\b|\binitiative\b|"
        r"\bsafety (app|tips|measures)\b|\blaunche(s|d)\b",
        re.IGNORECASE)),
    ("alleges_unconfirmed", re.compile(
        r"\bpolice probe if\b|\bquestioning everyone involved\b|\bSHO on\b.*\bdeath\b",
        re.IGNORECASE)),
]

NO_CONCRETE_EVENT_MARKERS = re.compile(
    r"^(why|how|what|where|when) \b|\?$|\bexplained\b|\bexplainer\b|\bguide\b|\bfaq\b",
    re.IGNORECASE,
)

MULTI_TOPIC_DIGEST = re.compile(r",.*,.*\band more\b|\band More$")


def check_relevance(title: str) -> Optional[str]:
    """Returns a reason code string if the headline should be dropped as a
    non-incident, or None if it passes (looks like a real, specific,
    located, dated event)."""
    lead_has_event_verb = DIRECT_EVENT_VERB_LEAD.search(title) is not None
    for flag_name, pattern in RELEVANCE_FLAG_PATTERNS:
        if flag_name == "legal_dispute" and lead_has_event_verb:
            continue
        if pattern.search(title):
            return flag_name
    if NO_CONCRETE_EVENT_MARKERS.search(title):
        return "no_concrete_event"
    if MULTI_TOPIC_DIGEST.search(title):
        return "multi_topic_digest"
    return None


# ---------------------------------------------------------------------------
# Category classifier -- controlled vocabulary only, per spec.
# Uncertain or conflicting cases become "other", never guessed.
# Handles the "murder staged as an accident" framing explicitly: if the
# headline's own words assert the real event is a murder/deliberate act
# (even when a crash/accident is also mentioned as the cover story), the
# category is assault, not road_accident.
# ---------------------------------------------------------------------------
DECEPTIVE_FRAMING_OVERRIDE = re.compile(
    r"\bmurder(ed)? staged as\b|\bstaged as (a |an )?(road )?accident\b|\bfaked? (an |a )?accident\b|"
    r"\bdisguised as (a |an )?accident\b",
    re.IGNORECASE,
)

# women_safety is checked BEFORE the generic assault/violence pattern --
# harassment/molestation/rape/stalking/eve-teasing/acid-attack headlines
# are specifically about a person's safety/sexual autonomy, which is a
# real, distinct category the dashboard has always tracked separately
# from generic violence (restored after being accidentally folded into
# "assault" in the first Phase 1 pass -- see CHANGELOG.md Phase 1b).
CATEGORY_KEYWORDS = [
    (r"\bfire\b|\bblaze\b|\bburn(t|ing)?\b|\bgutted\b", "fire"),
    (r"\bcrash(es|ed)?\b|\baccident\b|\bcollide(s|d)?\b|\bcolliding\b|\bcollision\b|\bruns? over\b|\brun over\b|"
     r"\bhit[- ]and[- ]run\b|\bhits?\b.*\b(bike|car|truck|scooter|pedestrian)\b|"
     r"\b(hit|struck|mowed down)\b.*\b(speeding|suv|truck|car|bike|vehicle)\b|\boverturn(s|ed)?\b|\brams?\b",
     "road_accident"),
    (r"\bsnatch(ed|ing|er)?\b|\bchain snatch|\brobb(ed|ery|er)\b|\bloot(ed|ing)?\b|\btheft\b|\bstolen\b|\bstole\b|\bburglar",
     "snatching"),
    (r"\bfell\b|\bfall(s|en)?\b|\bcollapsed?\b",
     "fall"),
    (r"\bharass|\bmolest|\beve[- ]?teas|\brape(d)?\b|\bgang[- ]?rape|\bacid attack|\bsexual assault|\bstalk(ed|ing|er)?\b",
     "women_safety"),
    (r"\bassault(ed)?\b|\bviolence\b|\bfight\b|\bbrawl\b|\bmurder(ed)?\b|\bstabb|\bbeaten\b|\bthrash(ed|ing)?\b|"
     r"\bshot\b|\bshooting\b|\bshootout\b",
     "assault"),
]


def classify_category(title: str) -> str:
    if DECEPTIVE_FRAMING_OVERRIDE.search(title):
        return "assault"
    for pattern, category in CATEGORY_KEYWORDS:
        if re.search(pattern, title, re.IGNORECASE):
            return category
    return "other"


# ---------------------------------------------------------------------------
# Recency check
# ---------------------------------------------------------------------------
def is_stale(published_at_iso: str, max_age_days: int = MAX_AGE_DAYS) -> tuple[bool, int]:
    try:
        published = datetime.fromisoformat(published_at_iso.replace("Z", "+00:00"))
    except Exception:
        return True, -1  # unparseable dates are treated as stale/invalid, never silently kept
    age_days = (datetime.now(timezone.utc) - published).days
    return age_days > max_age_days, age_days


# ---------------------------------------------------------------------------
# Geocoding: rate-limited (max 1 req/s), persistent cache, India bounding
# box enforced, honest location_precision, NO default/dummy coordinates
# on failure.
# ---------------------------------------------------------------------------
_last_geocode_time = [0.0]


def _load_geocode_cache() -> dict:
    if GEOCODE_CACHE_FILE.exists():
        try:
            return json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_geocode_cache(cache: dict):
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


_geocode_cache = _load_geocode_cache()


def geocode(query: str) -> Optional[dict]:
    """Returns {"latitude", "longitude", "display_name", "precision"} or
    None if geocoding fails or the result falls outside India. Never
    returns a default/fallback coordinate. Cached persistently so the
    same place is never re-queried across runs; rate-limited to Nominatim's
    documented max of 1 request/second for uncached lookups."""
    cache_key = query.strip().lower()
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    elapsed = time.time() - _last_geocode_time[0]
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1, "countrycodes": "in"},
            headers={"User-Agent": "WomenSafety-incident-research/1.0 (contact: project maintainer)"},
            timeout=15,
        )
        _last_geocode_time[0] = time.time()
        resp.raise_for_status()
        results = resp.json()
        if not results:
            _geocode_cache[cache_key] = None
            _save_geocode_cache(_geocode_cache)
            return None
        r = results[0]
        lat, lng = float(r["lat"]), float(r["lon"])
        if not (INDIA_BOUNDS[0] <= lat <= INDIA_BOUNDS[1] and INDIA_BOUNDS[2] <= lng <= INDIA_BOUNDS[3]):
            _geocode_cache[cache_key] = None
            _save_geocode_cache(_geocode_cache)
            return None
        addr = r.get("address", {})
        if addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter"):
            precision = "area"
        elif addr.get("city_district") or addr.get("town") or addr.get("village") or addr.get("city") or addr.get("municipality"):
            precision = "city"
        else:
            precision = "unknown"
        result = {
            "latitude": lat, "longitude": lng,
            "display_name": r.get("display_name", query),
            "precision": precision,
        }
        _geocode_cache[cache_key] = result
        _save_geocode_cache(_geocode_cache)
        return result
    except Exception as e:
        print(f"    geocode failed for {query!r}: {e}")
        _last_geocode_time[0] = time.time()
        return None


# ---------------------------------------------------------------------------
# Source-of-truth store: scraped_incidents.json, keyed by id.
# ---------------------------------------------------------------------------
def backup_data_file(path: Path):
    if not path.exists():
        return
    BACKUPS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"{path.stem}_{ts}{path.suffix}"
    shutil.copy(path, dest)


def load_store() -> dict:
    if SCRAPED_INCIDENTS_FILE.exists():
        try:
            return json.loads(SCRAPED_INCIDENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_store(store: dict):
    backup_data_file(SCRAPED_INCIDENTS_FILE)
    SCRAPED_INCIDENTS_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def log_dropped(record_id: str, title: str, reason: str, **extra):
    entry = {"id": record_id, "title": title, "reason": reason, "dropped_at": datetime.now(timezone.utc).isoformat(), **extra}
    with open(DROPPED_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
