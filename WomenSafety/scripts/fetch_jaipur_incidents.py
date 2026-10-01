"""ARCHIVED, NOT PART OF THE PRODUCT -- see fetch_india_incidents.py's
docstring and CHANGELOG.md "CCTV Incident Capture Pipeline" phase. The
product is now CCTV-only; news scraping (what this wraps) is out of
scope and its previous output was moved to
archive/news_scrape_incidents.json.

Jaipur-specific wrapper around fetch_india_incidents.py.

This script originally had its own full copy of the scraping pipeline
(hand-maintained Jaipur locality list, its own duplicate/relevance/
classification logic). That logic has since been consolidated into
scripts/scrape_pipeline.py and scripts/fetch_india_incidents.py, which
do everything this script did plus nationwide coverage, a real schema,
honest location_precision, null confidence, recency filtering, and
idempotent re-runs. Maintaining two divergent copies of the same rules
was a real risk (the Phase 1 audit exists precisely because rules
drifted apart before), so this file is now a thin wrapper: it just
biases the query toward Jaipur and delegates everything else.

Usage:
    python scripts/fetch_jaipur_incidents.py "road accident" --count 15 --create-incidents
    (equivalent to: python scripts/fetch_india_incidents.py "Jaipur road accident" --count 15 --create-incidents)
"""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Jaipur-biased wrapper around fetch_india_incidents.py")
    parser.add_argument("query", help="Search query, e.g. 'road accident' (Jaipur is prefixed automatically)")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--create-incidents", action="store_true")
    parser.add_argument("--max-age-days", type=int, default=365)
    args = parser.parse_args()

    query = args.query if "jaipur" in args.query.lower() else f"Jaipur {args.query}"

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "fetch_india_incidents.py"),
        query,
        "--count", str(args.count),
        "--max-age-days", str(args.max_age_days),
    ]
    if args.create_incidents:
        cmd.append("--create-incidents")

    result = subprocess.run(cmd, cwd=str(Path(__file__).parent.parent))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
