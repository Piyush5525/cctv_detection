"""Reset the demo database (backs up first).

  python scripts/reset_demo.py              # empty DB (0 incidents)
  python scripts/reset_demo.py --showcase   # replace contents with demo/showcase.db
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from api.services import demo_reset  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--showcase", action="store_true", help="load demo/showcase.db after clearing")
    args = parser.parse_args()
    try:
        print(demo_reset.reset(load_showcase=args.showcase))
    except demo_reset.ShowcaseMissing as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
