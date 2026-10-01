"""ARCHIVED, NOT PART OF THE PRODUCT -- see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase. Runs fetch_india_incidents.py, itself archived.

Fills the women_safety and violence category gap left when the main
nationwide batch run hit its 300-incident cap before reaching those queries.
Same mechanics as run_india_batches.py, just a focused query list.
"""
import subprocess
import sys
import requests

QUERIES = [
    "Mumbai women harassment news",
    "Bengaluru women safety incident",
    "Hyderabad women safety news",
    "Noida women harassment CCTV",
    "Gurugram women safety incident",
    "Lucknow women safety news",
    "Chennai women harassment news",
    "Kolkata women safety incident",
    "Pune women harassment news",
    "India molestation CCTV video",
    "India stalking case news",
    "India acid attack news",
    "Delhi assault CCTV video",
    "Mumbai assault attack CCTV",
    "Bengaluru assault news",
    "Gurugram assault attack",
    "Noida assault attack news",
    "Hyderabad murder attack CCTV",
    "Kolkata assault attack news",
    "Chennai murder attack CCTV",
    "Pune assault attack news",
]


def get_total():
    try:
        r = requests.get("http://localhost:8000/api/v1/incidents", params={"page": 1, "page_size": 1}, timeout=10).json()
        return r.get("total", 0)
    except Exception:
        return -1


def main():
    print(f"Starting total: {get_total()}")
    for i, q in enumerate(QUERIES):
        print(f"\n===== [{i+1}/{len(QUERIES)}] query: {q!r} =====", flush=True)
        result = subprocess.run(
            [sys.executable, "scripts/fetch_india_incidents.py", q, "--count", "20", "--create-incidents"],
            cwd="D:/Projects/Detection-Models/WomenSafety",
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",  # child prints non-ASCII headlines; cp1252 default crashes here on Windows
        )
        print(result.stdout[-2000:])
        if result.returncode != 0:
            print("STDERR:", result.stderr[-1000:])
        total = get_total()
        print(f"--- running total after this query: {total} ---", flush=True)


if __name__ == "__main__":
    main()
