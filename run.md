# Run commands (copy and paste)

All commands are PowerShell, run from the app folder unless noted.

```powershell
cd D:\Projects\Detection-Models\WomenSafety
```

## 1. Start the dashboard (API + built frontend)

```powershell
cd D:\Projects\Detection-Models\WomenSafety
python run_dashboard.py --mode api --no-build
```

Open http://localhost:8000/map . Stop with Ctrl+C. Run only ONE instance.

If the page looks outdated, rebuild the frontend first (needed after any frontend change):

```powershell
cd D:\Projects\Detection-Models\WomenSafety
python run_dashboard.py --mode build
```

## 2. Connect CAM 001 (phone camera)

Check the phone is reachable (phone and laptop on the same Wi-Fi, IP Webcam app started):

```powershell
Test-NetConnection 10.172.5.41 -Port 8080
```

`TcpTestSucceeded : True` means it is reachable. Then test the stream (no address is printed):

```powershell
cd D:\Projects\Detection-Models\WomenSafety
python scripts/check_camera.py CAM-001
```

CAM-001 settings live in `.env` (restart the API after changing them):

```
PHONE_CAM001_URL=http://<phone-ip>:8080/video
PHONE_CAM001_LAT=<number, e.g. 26.9124>
PHONE_CAM001_LNG=<number, e.g. 75.7873>
# only if the app has a login:
# PHONE_CAM001_USER=
# PHONE_CAM001_PASSWORD=
```

Check status once the API is running (`status` should be `online`, `error` null):

```powershell
curl http://localhost:8000/api/v1/cameras/status
```

If the phone IP changed, look it up in the IP Webcam app (it shows the address), update `PHONE_CAM001_URL` in `.env`, restart the API.

### CAM 002 (second phone)

```powershell
Test-NetConnection 10.172.4.180 -Port 8080
python scripts/check_camera.py CAM-002
```

Settings in `.env` (same pattern as CAM 001; restart the API after changing them):

```
PHONE_CAM002_URL=http://10.172.4.180:8080/video
PHONE_CAM002_LAT=<number>
PHONE_CAM002_LNG=<number>
```

Both cameras appear as tiles in the dashboard's **Live Cameras** panel (offline with a clear reason until configured). To add another phone, copy the CAM-002 entry in `config/cameras.json` (new id, name and `PHONE_CAMxxx_*` variables) and add the variables to `.env`.

## 3. Demo controls (in the browser)

Click the amber **Demo** button in the top bar (or Ctrl+Shift+D): Load showcase, Reset demo, Trigger test incident (pick camera and Fire/Crash).

Command line equivalents:

```powershell
cd D:\Projects\Detection-Models\WomenSafety
python scripts/reset_demo.py                 # backup, then 0 incidents
python scripts/reset_demo.py --showcase      # load demo/showcase.db
python scripts/build_showcase.py ID1 ID2 ID3 ID4 ID5   # build showcase from 5 ids in demo/candidates.html
```

## 4. Alerts (Telegram and call)

In `.env`: `ALERTS_ENABLED=true` turns real alerts on (default is false). Calls only go to `DEMO_PHONE_NUMBER`, Telegram only to `TELEGRAM_CHAT_ID`. Restart the API after changing `.env`.

Live smoke tests (each sends real traffic to your own recipients; add `--yes`). Stop the API before `--telegram`:

```powershell
cd D:\Projects\Detection-Models\WomenSafety
python scripts/smoke_test.py --help
python scripts/smoke_test.py --serpapi --yes
python scripts/smoke_test.py --mapbox --yes
python scripts/smoke_test.py --telegram --yes
python scripts/smoke_test.py --call --yes
python scripts/smoke_test.py --serpapi --yes --camera CAM-001   # refresh nearby services for CAM-001 after setting its lat/lng
```

## 5. Housekeeping

```powershell
# is the API running? (should list exactly one)
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*run_dashboard*' } | Select ProcessId

# stop it
Stop-Process -Id <ProcessId> -Force

# tests (use a temp database, never touch incidents.db)
cd D:\Projects\Detection-Models\WomenSafety
python -m unittest discover -s tests

# frontend dev server instead of the built one (optional)
cd D:\Projects\Detection-Models\WomenSafety\frontend
npm run dev
```

## 6. Pre-demo checklist

1. `python run_dashboard.py --mode api --no-build` (one instance, http://localhost:8000/map loads)
2. `Test-NetConnection 10.172.5.41 -Port 8080` is True, then `python scripts/check_camera.py CAM-001`
3. `curl http://localhost:8000/api/v1/cameras/status` shows CAM-001 (and CAM-002) `online`
4. Demo button, Reset demo (or Load showcase) for a clean map
5. `ALERTS_ENABLED=true` in `.env` only when you want real Telegram and call alerts
6. Phone nearby with the ringer on; Telegram open on the demo chat
