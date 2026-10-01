"""Probe which GPS source a demo phone offers.  Usage: python scripts/check_phone_gps.py CAM-001

Tries, in order:
  (a) IP Webcam HTTP endpoints on the camera's own host: /gps.json, /sensors.json?sense=gps, /sensors.json
  (b) the SensorServer WebSocket at PHONE_CAMnnn_GPS_URL (e.g. ws://<phone>:<port>/gps), nnn from the camera's
      stream variable (PHONE_CAM001_URL -> PHONE_CAM001_GPS_URL)
Prints only: source name, accuracy in metres, fix age in seconds, inside-India yes/no. NEVER prints
coordinates, hosts, URLs or credentials.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from api.models.camera import get_camera  # noqa: E402  (loads .env)
from api.services import phone_location as pl  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/check_phone_gps.py <camera_id>")
    camera = get_camera(sys.argv[1])
    if camera is None or camera.camera_type != "phone":
        raise SystemExit("ERROR: unknown camera id or not a phone camera")
    sources = pl.candidate_sources(camera)
    if not sources:
        raise SystemExit("ERROR: no probe sources (stream URL env var unset or not http(s))")
    working = []
    for name, probe in sources:
        try:
            fix = probe()
        except Exception as exc:  # message names the failure class only, never a URL
            print(f"[--] {name:28} unavailable ({type(exc).__name__})")
            continue
        if fix is None:
            print(f"[--] {name:28} reachable but no GPS fix in the response")
            continue
        print(f"[OK] {name:28} accuracy={'?' if fix.accuracy_m is None else round(fix.accuracy_m)} m  "
              f"fix_age={'?' if fix.age_s is None else round(fix.age_s)} s  inside_india={'yes' if fix.in_india else 'NO'}")
        working.append(name)
    print("RESULT:", f"working source(s): {', '.join(working)}" if working else "NO GPS SOURCE WORKS on this phone")
    raise SystemExit(0 if working else 1)


if __name__ == "__main__":
    main()
