"""Secrets hygiene scan: looks for the ACTUAL secret values from the local .env files (and generic token / phone / LAN-IP
shapes) in the working tree (tracked + untracked, not git-ignored) and in the whole git history.

Prints ONLY "<kind>  <file>:<line>" (and commit short-ids for history hits): never a value, never a matching line.

    python scripts/secret_scan.py [--no-history]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent  # the git repo root is the parent of WomenSafety/

SENSITIVE = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OMNIDIM_API_KEY", "SERPAPI_KEY", "DEMO_TOKEN", "DEMO_PHONE_NUMBER", "ALERT_PHONE_NUMBER",
             "MAPBOX_TOKEN", "VITE_MAPBOX_TOKEN", "VITE_DEMO_TOKEN", "OMNIDIM_AGENT_ID", "OMNIDIM_FROM_NUMBER_ID"]
SHAPES = {
    "telegram-bot-token-shape": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "mapbox-token-shape": re.compile(r"\b[ps]k\.[A-Za-z0-9_-]{40,}\b"),
    "indian-mobile-number-shape": re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)"),
    "private-lan-ip-shape": re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".mp4", ".pt", ".db", ".pth", ".npy", ".pkl", ".ico", ".woff", ".woff2", ".ttf", ".gif", ".webp", ".pdf", ".map"}
SKIP_DIRS = ("node_modules/", "frontend/build/", "evidence/", "evidence_clips/", "archive/", "backups/")


def secret_values() -> dict:
    vals = {}
    for f in (ROOT / ".env", ROOT / "frontend" / ".env"):
        if not f.exists():
            continue
        env = dotenv_values(f)
        for k in SENSITIVE:
            v = (env.get(k) or "").strip()
            if len(v) >= 8:
                vals[f"value of {k}"] = v
        for k, v in env.items():
            if k and re.match(r"PHONE_CAM\d+_URL$", k) and v:
                host = urlsplit(v.strip()).hostname
                if host:
                    vals[f"host/IP of {k}"] = host
            if k and re.match(r"PHONE_CAM\d+_(PASSWORD|USER)$", k) and v and len(v.strip()) >= 4:
                vals[f"value of {k}"] = v.strip()
    return vals


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def tree_files() -> list:
    names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    out = []
    for n in names:
        if not n or any(d in n for d in SKIP_DIRS) or Path(n).suffix.lower() in SKIP_SUFFIX:
            continue
        out.append(n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-history", action="store_true")
    args = ap.parse_args()
    vals = secret_values()
    print(f"scanning for {len(vals)} local secret values + {len(SHAPES)} generic shapes (values are never printed)")
    tracked_env = [f for f in git("ls-files").splitlines() if re.search(r"(^|/)\.env($|\.)", f) and not f.endswith(".example")]
    print("tracked .env files:", tracked_env or "none")
    hits = 0
    for name in tree_files():
        p = REPO / name
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for kind, v in vals.items():
                if v in line:
                    print(f"WORKTREE  {kind:34s} {name}:{i}")
                    hits += 1
            for kind, rx in SHAPES.items():
                if rx.search(line):
                    print(f"WORKTREE  {kind:34s} {name}:{i}")
                    hits += 1
    print(f"worktree hits: {hits}")
    if not args.no_history:
        hh = 0
        revs = git("rev-list", "--all", "--abbrev-commit").split()
        print(f"history: {len(revs)} commits")
        for kind, v in vals.items():
            commits = git("log", "--all", "--format=%h", "-S" + v).split()
            for c in commits:
                for ln in git("grep", "-I", "-n", "-F", "-e", v, c).splitlines():
                    parts = ln.split(":", 3)
                    if len(parts) >= 3:
                        print(f"HISTORY   {kind:34s} {c} {parts[1]}:{parts[2]}")
                        hh += 1
        for kind, rx in SHAPES.items():
            pattern = rx.pattern
            for ln in git("grep", "-I", "-n", "-P", "-e", pattern, *revs[:200]).splitlines()[:60]:
                parts = ln.split(":", 3)
                if len(parts) >= 3 and Path(parts[1]).suffix.lower() not in SKIP_SUFFIX and not any(d in parts[1] for d in SKIP_DIRS):
                    print(f"HISTORY   {kind:34s} {parts[0][:7]} {parts[1]}:{parts[2]}")
                    hh += 1
        print(f"history hits (values + shapes in the 200 most recent commits): {hh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
