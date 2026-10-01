# GPS bring-up checklist (run once both phones are online)

Status today: **`LOCATION_MODE=fixed` (default) - nothing GPS-related runs.** Incidents, labels and the map use the
`.env` coordinates (`PHONE_CAM001_LAT/LNG`, `PHONE_CAM002_LAT/LNG`). The GPS code is built and tested against
simulated phones only (the adapters in `api/services/gps_adapters.py` are marked "verified against simulation only").

## 1. Get the phones ready
- Both phones on the same Wi-Fi as the laptop, IP Webcam server started, stream URLs current in `.env`.
- IP Webcam: allow **Location** permission and turn GPS on (its `/gps.json` and `/sensors.json` only carry GPS then).
- Alternative: install SensorServer, enable its GPS sensor, and add `PHONE_CAM001_GPS_URL=ws://<phone-ip>:<port>/gps`
  (same for `PHONE_CAM002_GPS_URL`) to `.env`.
- Go near a window or outside: indoors a phone often reports poor accuracy (more than the 50 m limit) or no fix.

## 2. Probe each phone (prints no coordinates, hosts or URLs)
```powershell
cd D:\Projects\Detection-Models\WomenSafety
python scripts/check_phone_gps.py CAM-001
python scripts/check_phone_gps.py CAM-002
```
| Output | Meaning | What to do |
|---|---|---|
| `[OK] ipwebcam /gps.json  accuracy=8 m  fix_age=2 s  inside_india=yes` | A source works and the fix is usable | Go to step 3 |
| `[OK] ...  accuracy=?` | A fix arrives but the phone gives no accuracy; the system will treat it as unusable (it needs accuracy <= `MAX_ACCURACY_M`) | Tell me the source; the adapter in `gps_adapters.py` may need a field name |
| `[OK] ...  inside_india=NO` | Coordinates look wrong (outside the India box); fixes are rejected | Check the phone's location settings / mock locations |
| `[--] ... unavailable (ConnectionError / ConnectTimeout)` | Phone not reachable or server off | Step 1 |
| `[--] ... reachable but no GPS fix in the response` | Reachable but the reply has no GPS, or the format differs from the assumed one | Send me the app and endpoint; the fix is local to one adapter |
| `RESULT: NO GPS SOURCE WORKS on this phone` | No usable source | **Stay on `fixed`.** Nothing else to do; the system keeps using the `.env` coordinates |

## 3. Switch it on (only after a source is confirmed)
In `.env`: `LOCATION_MODE=auto` (optional tuning: `MAX_FIX_AGE_S=60`, `MAX_ACCURACY_M=50`, `SMOOTH_FIXES=5`).
Restart the API: `python run_dashboard.py --mode api --no-build`.

## 4. Check it
```powershell
curl http://localhost:8000/api/v1/cameras/status
```
Each phone should show `location_source: device_gps`, `location_accuracy_m` and a small `location_fix_age_s`
(`camera_registry` = no good fix, using the `.env` coordinates). In the dashboard: the camera tile and incident
detail show "Device GPS ± N m" (or "Fixed placement"), and the selected camera shows a soft accuracy circle.
Trigger a test incident on a phone (Demo button): it uses the same location logic, stays labelled "Recorded footage replay",
and its dispatch plan uses the snapshot location. Sample cameras, the showcase and "Reset demo" never use GPS.

## 5. Go back
Set `LOCATION_MODE=fixed` (or remove the line) and restart: GPS polling, prefetch, labels and the 5 s services deadline all stop.
