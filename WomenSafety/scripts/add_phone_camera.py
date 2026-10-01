"""Register a fixed-location demo phone camera without storing credentials."""
import argparse, json, re
from pathlib import Path

ROOT = Path(__file__).parent.parent; CONFIG = ROOT / "config" / "cameras.json"

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--name", required=True); parser.add_argument("--lat", required=True, type=float); parser.add_argument("--lng", required=True, type=float); parser.add_argument("--url", required=True); parser.add_argument("--place", default="Demo phone installation")
    args = parser.parse_args()
    if not args.url.startswith(("http://", "https://", "rtsp://")): parser.error("--url must be HTTP/MJPEG or RTSP")
    data = json.loads(CONFIG.read_text(encoding="utf-8")); ids = {c["camera_id"] for c in data["cameras"]}
    stem = re.sub(r"[^A-Z0-9]+", "-", args.name.upper()).strip("-") or "PHONE"; camera_id = f"PHONE-{stem}"
    suffix = 2
    while camera_id in ids: camera_id = f"PHONE-{stem}-{suffix}"; suffix += 1
    data["cameras"].append({"camera_id": camera_id, "name": args.name, "place_text": args.place, "latitude": args.lat, "longitude": args.lng, "stream_source": args.url, "camera_type": "phone", "location_basis": "real_installation", "enabled": True, "sample": False, "field_of_view_note": "Demo phone camera; fixed coordinates entered by operator."})
    CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Added {camera_id}: Demo phone camera - {args.name}")
if __name__ == "__main__": main()
