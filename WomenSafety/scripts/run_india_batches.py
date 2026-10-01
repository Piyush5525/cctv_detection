"""ARCHIVED, NOT PART OF THE PRODUCT -- see CHANGELOG.md "CCTV Incident
Capture Pipeline" phase. Runs fetch_india_incidents.py, itself archived.

Runs fetch_india_incidents.py across many diverse queries back-to-back so
the dataset grows toward a real target count without needing a human to
invoke each query by hand. Prints a running total after every query so
progress is visible in one place.
"""
import subprocess
import sys
import requests

QUERIES = [
    # Crash / road accident, spread across many big Indian cities so results
    # aren't dominated by one metro's news cycle.
    "Mumbai road accident CCTV",
    "Delhi road accident CCTV",
    "Bengaluru road accident CCTV",
    "Chennai road accident CCTV",
    "Kolkata road accident CCTV",
    "Hyderabad road accident CCTV",
    "Pune road accident CCTV",
    "Ahmedabad road accident CCTV",
    "Lucknow road accident CCTV",
    "Surat road accident CCTV",
    "Indore road accident CCTV",
    "Bhopal road accident CCTV",
    "Chandigarh road accident CCTV",
    "Kochi road accident CCTV",
    "Patna road accident CCTV",
    "Guwahati road accident CCTV",
    "Nagpur road accident CCTV",
    "Coimbatore road accident CCTV",
    "Visakhapatnam road accident CCTV",
    "Kanpur road accident CCTV",
    # Fire
    "Mumbai fire news",
    "Delhi fire news",
    "Bengaluru fire news",
    "Chennai fire news",
    "Kolkata fire news",
    "Hyderabad fire news",
    "Surat fire factory",
    "Ahmedabad fire news",
    "Pune fire news",
    "Gurugram fire news",
    # Snatching / robbery / theft
    "Delhi chain snatching CCTV",
    "Mumbai chain snatching robbery",
    "Bengaluru chain snatching",
    "Hyderabad robbery CCTV",
    "Chennai chain snatching",
    "Pune robbery CCTV",
    "Noida robbery snatching",
    "Lucknow snatching robbery",
    # Violence / assault
    "Delhi assault CCTV video",
    "Mumbai assault attack CCTV",
    "Bengaluru assault news",
    "Gurugram assault attack",
    "Noida assault attack news",
    "Hyderabad murder attack CCTV",
    "Kolkata assault attack news",
    # Women's safety
    "Delhi women safety harassment news",
    "Mumbai women harassment news",
    "Bengaluru women safety incident",
    "Hyderabad women safety news",
    "Noida women harassment CCTV",
    "Gurugram women safety incident",
    "Lucknow women safety news",
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
            encoding="utf-8", errors="replace",
        )
        print(result.stdout[-2000:])
        if result.returncode != 0:
            print("STDERR:", result.stderr[-1000:])
        total = get_total()
        print(f"--- running total after this query: {total} ---", flush=True)
        if total >= 300:
            print("Reached target of 300, stopping early.")
            break


if __name__ == "__main__":
    main()
