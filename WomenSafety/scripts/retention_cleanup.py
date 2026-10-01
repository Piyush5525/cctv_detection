"""Evidence retention dry-run command (CHANGELOG.md "CCTV Incident
Capture Pipeline" phase). Lists evidence directories older than
RETENTION_DAYS (config, default 30). Does NOT auto-delete anything in
this phase: --dry-run is the default and only supported mode.

Usage:
    python scripts/retention_cleanup.py
    python scripts/retention_cleanup.py --retention-days 60
"""
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.core.config import settings


def scan_evidence(evidence_root: Path, retention_days: int, dry_run: bool = True):
    """Scans evidence/{camera_id}/{YYYY-MM-DD}/ directories and reports
    which ones are older than retention_days. In dry-run mode (the only
    mode in this phase) it prints what WOULD be deleted but deletes
    nothing."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_date = cutoff.date()

    if not evidence_root.exists():
        print(f"Evidence root does not exist: {evidence_root}")
        return

    total_dirs = 0
    expired_dirs = 0
    expired_size_bytes = 0

    for camera_dir in sorted(evidence_root.iterdir()):
        if not camera_dir.is_dir():
            continue
        for date_dir in sorted(camera_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            total_dirs += 1
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").date()
            except ValueError:
                print(f"  SKIP (not a date dir): {date_dir}")
                continue

            if dir_date < cutoff_date:
                # Count files and size
                dir_size = sum(f.stat().st_size for f in date_dir.rglob("*") if f.is_file())
                file_count = sum(1 for f in date_dir.rglob("*") if f.is_file())
                expired_dirs += 1
                expired_size_bytes += dir_size

                action = "WOULD DELETE" if dry_run else "DELETING"
                print(f"  {action}: {date_dir.relative_to(evidence_root)} "
                      f"({file_count} files, {dir_size / 1024:.1f} KB)")

                if not dry_run:
                    # NOT IMPLEMENTED in this phase -- fail loudly
                    raise NotImplementedError(
                        "Actual deletion is disabled in this phase. "
                        "Use --dry-run (the default) to preview what would be deleted."
                    )

    print(f"\nSummary:")
    print(f"  Evidence root: {evidence_root}")
    print(f"  Retention days: {retention_days}")
    print(f"  Cutoff date: {cutoff_date}")
    print(f"  Total date-directories scanned: {total_dirs}")
    print(f"  Expired directories: {expired_dirs}")
    print(f"  Total size of expired evidence: {expired_size_bytes / 1024:.1f} KB")
    if dry_run:
        print(f"  Mode: DRY RUN (nothing was deleted)")
    else:
        print(f"  Mode: EXECUTE (not implemented in this phase)")


def main():
    parser = argparse.ArgumentParser(
        description="Evidence retention cleanup (dry-run only in this phase)"
    )
    parser.add_argument(
        "--retention-days", type=int, default=settings.RETENTION_DAYS,
        help=f"Days to retain evidence (default: {settings.RETENTION_DAYS} from config)"
    )
    parser.add_argument(
        "--evidence-root", type=str, default=str(settings.EVIDENCE_ROOT_V2),
        help=f"Evidence root directory (default: {settings.EVIDENCE_ROOT_V2})"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview what would be deleted (default, the only mode in this phase)"
    )
    args = parser.parse_args()

    print(f"Evidence retention cleanup")
    print(f"=" * 40)
    scan_evidence(Path(args.evidence_root), args.retention_days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
