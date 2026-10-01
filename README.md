All run commands (dashboard, CAM 001 phone camera, demo controls, smoke tests): see WomenSafety/run.md

# 🚨 Incident Command Dashboard

Real-time CCTV incident detection system with fire, crash, violence, fall, and snatch detection. Features a live map dashboard, Telegram alerts, voice-call escalation, and a dispatch plan with nearest emergency services.

---

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Environment Setup](#-environment-setup)
- [Camera Configuration](#-camera-configuration)
- [Running the Dashboard](#-running-the-dashboard)
- [Demo Mode](#-demo-mode)
- [API Endpoints](#-api-endpoints)
- [Phone Camera Setup](#-phone-camera-setup)
- [Project Structure](#-project-structure)
- [Troubleshooting](#-troubleshooting)

---

## 🚀 Quick Start

```bash
cd WomenSafety
pip install -r requirements.txt
cp .env.example .env          # Edit .env with your keys
cd frontend && npm install && cd ..
python run_dashboard.py --mode all
```

Open **http://localhost:8000** (full stack) or **http://localhost:3000/map** (dev mode).

---

## 📦 Prerequisites

| Tool       | Version  | Purpose                        |
|------------|----------|--------------------------------|
| Python     | 3.10+    | Backend, detection models      |
| Node.js    | 18+      | Frontend build                 |
| npm        | 9+       | Frontend dependencies          |
| ffmpeg     | any      | Evidence clip encoding         |
| Git        | any      | Clone + CLIP install           |

Check everything is installed:

```bash
python --version
node --version
npm --version
ffmpeg -version
```

---

## 🔧 Installation

### 1. Clone and enter the project

```bash
git clone <your-repo-url>
cd Detection-Models/WomenSafety
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## ⚙️ Environment Setup

Copy the example and fill in your values:

```bash
cp .env.example .env
```

### `.env` — Key variables

```env
# ============================================================
# DETECTION MODELS — 1 = ON, 0 = OFF
# ============================================================
VIOLENCE_DETECTION=0
FALL_DETECTION=0
SNATCH_DETECTION=0
FIRE_DETECTION=1          # YOLOv8 fire detector
CRASH_DETECTION=1          # YOLOv8 crash detector

API_ENABLED=1

# ── Telegram alerts ──────────────────────────────────────────
# Get bot token from @BotFather on Telegram
# Get chat ID from @userinfobot on Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# ── Voice call alerts (Omnidim) ──────────────────────────────
OMNIDIM_API_KEY=
OMNIDIM_AGENT_ID=
OMNIDIM_FROM_NUMBER_ID=
ALERT_PHONE_NUMBER=+91XXXXXXXXXX

# ── Dispatch & nearby services ───────────────────────────────
SERPAPI_KEY=your_serpapi_key     # For hospital/police/fire lookup
MAPBOX_TOKEN=your_mapbox_token  # Backend routing (server-side)

# ── Demo safety ──────────────────────────────────────────────
DEMO_MODE=true                  # MUST be true for demos
DEMO_PHONE_NUMBER=+91XXXXXXXXXX # Only this number gets calls
ALERTS_ENABLED=false            # Set true to enable Telegram/call
LEGACY_DETECTORS_ENABLED=false  # Keep false for demos
```

### `frontend/.env` — Frontend-only variables

```env
VITE_MAPBOX_TOKEN=pk.your_mapbox_public_token_here
VITE_DEMO_TOKEN=your_demo_token_here
```

> **Get a Mapbox token:** Sign up at [mapbox.com](https://account.mapbox.com/) → create a token → paste it in both `frontend/.env` and `.env`.

---

## 📷 Camera Configuration

Cameras are registered in `config/cameras.json`. The system supports several source types:

### Webcam (built-in)

```env
CAMERA_SOURCE=0
```

Use `1`, `2`, etc. if you have multiple cameras.

### IP Camera (RTSP — most common for CCTV)

```env
CAMERA_SOURCE=rtsp://username:password@192.168.1.100:554/stream1
```

### IP Camera (HTTP/MJPEG stream)

```env
CAMERA_SOURCE=http://192.168.1.100:8080/video
```

### Video File (offline replay)

```env
CAMERA_SOURCE=data/crash.mp4
```

### Adding a new camera to the registry

Edit `config/cameras.json`:

```json
{
  "camera_id": "CAM-NEW-001",
  "name": "My Camera Name",
  "place_text": "Location description",
  "latitude": 26.9124,
  "longitude": 75.7873,
  "stream_source": "rtsp://192.168.1.100:554/stream1",
  "camera_type": "cctv",
  "location_basis": "real_installation",
  "enabled": true,
  "sample": false
}
```

> **Camera types:** `cctv` (fixed installation) or `phone` (demo phone camera).
> **Location basis:** `real_installation` (actual GPS) or `simulated_placement` (demo position).

---

## ▶️ Running the Dashboard

### Option 1: Full stack (recommended for demo)

Starts the API + detection pipeline + serves the built frontend:

```bash
cd WomenSafety
python run_dashboard.py --mode all
```

- Dashboard: **http://localhost:8000**
- API docs: **http://localhost:8000/api/docs**

### Option 2: API only (no detection)

Just the API server, no camera processing:

```bash
python run_dashboard.py --mode api
```

### Option 3: Dev mode (hot-reload frontend)

Run backend and frontend separately for development:

```bash
# Terminal 1 — Backend
python run_dashboard.py --mode api --no-build

# Terminal 2 — Frontend (hot reload)
cd frontend
npm run dev
```

- Frontend dev server: **http://localhost:3000** (proxies API to :8000)
- Map dashboard: **http://localhost:3000/map**

### Option 4: Build frontend only

```bash
python run_dashboard.py --mode build
# or
cd frontend && npm run build
```

### Option 5: Detection pipeline only

```bash
python run_dashboard.py --mode detection
```

---

## 🎮 Demo Mode

### Pre-demo checklist

| # | Check | Command / Action |
|---|-------|-----------------|
| 1 | Mapbox token set | Check `frontend/.env` has `VITE_MAPBOX_TOKEN=pk.…` |
| 2 | `DEMO_MODE=true` | Check `.env` |
| 3 | Backend running | `python run_dashboard.py --mode all` |
| 4 | Frontend loads | Open http://localhost:8000 or http://localhost:3000/map |
| 5 | Hotspot joined | Laptop + phone on same Wi-Fi (for phone camera) |
| 6 | Phone camera online | `python scripts/check_camera.py CAM-001` |
| 7 | Cache warmed | Visit `/api/v1/cameras/CAM-SAMPLE-001/nearby-services` |

### Demo controls (hidden menu)

Press **`Ctrl + Shift + D`** on the map page to open the demo controls:

- **Load showcase** — Restores demo/showcase.db (the pre-recorded incidents)
- **Reset view** — Refreshes the map data
- **Trigger test incident** — Creates a fire or crash incident from a stored sample clip

### Trigger a test incident via API

```bash
# Fire incident on CAM-SAMPLE-002
curl -X POST http://localhost:8000/api/v1/demo/trigger \
  -H "Content-Type: application/json" \
  -d "{\"camera_id\": \"CAM-SAMPLE-002\", \"category\": \"fire\"}"

# Crash incident on CAM-SAMPLE-001
curl -X POST http://localhost:8000/api/v1/demo/trigger \
  -H "Content-Type: application/json" \
  -d "{\"camera_id\": \"CAM-SAMPLE-001\", \"category\": \"road_accident\"}"
```

### PowerShell (Windows)

```powershell
# Fire incident
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/demo/trigger" `
  -Method POST -ContentType "application/json" `
  -Body '{"camera_id":"CAM-SAMPLE-002","category":"fire"}'

# Crash incident
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/demo/trigger" `
  -Method POST -ContentType "application/json" `
  -Body '{"camera_id":"CAM-SAMPLE-001","category":"road_accident"}'
```

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/incidents` | List all incidents (paginated) |
| GET | `/api/v1/incidents/{id}` | Get incident detail |
| PATCH | `/api/v1/incidents/{id}/status` | Update status (confirm/false_positive) |
| WS | `/api/v1/incidents/ws` | Real-time incident push (WebSocket) |
| GET | `/api/v1/map/groups` | Camera-grouped incidents for map |
| GET | `/api/v1/cameras/status` | All camera statuses + FPS |
| GET | `/api/v1/cameras/{id}/live` | Live MJPEG stream |
| GET | `/api/v1/cameras/{id}/nearby-services` | Nearest hospital/police/fire |
| GET | `/api/v1/evidence/v2/{cam}/{date}/{id}/{file}` | Evidence files (thumbnail, best_frame, clip) |
| POST | `/api/v1/demo/trigger` | Trigger a test incident |
| GET | `/api/docs` | Interactive Swagger docs |

---

## 📱 Phone Camera Setup

Use your phone as a live demo camera:

### 1. Install a camera app on your phone

- **Android:** [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam) (free)
- **iOS:** [IP Camera Lite](https://apps.apple.com/app/ip-camera-lite/id1013455241)

### 2. Start the stream on your phone

Open the app and start the server. Note the URL shown (e.g., `http://192.168.1.42:8080/video`).

### 3. Configure in `.env`

```env
PHONE_CAM001_URL=http://192.168.1.42:8080/video
PHONE_CAM001_LAT=26.9124
PHONE_CAM001_LNG=75.7873
```

### 4. Verify the phone camera

```bash
python scripts/check_camera.py CAM-001
```

Expected output: `CAM-001: online`

### 5. Add a new phone camera to the registry

```bash
python scripts/add_phone_camera.py \
  --camera-id CAM-PHONE-002 \
  --name "Entrance Camera" \
  --place "Building entrance" \
  --url "http://192.168.1.43:8080/video" \
  --lat 26.9150 --lng 75.7920
```

> **Important:** Both laptop and phone must be on the **same Wi-Fi network** or hotspot.

---

## 📁 Project Structure

```
WomenSafety/
├── api/                        # FastAPI backend
│   ├── core/config.py          # All settings (env-loaded)
│   ├── models/
│   │   ├── camera.py           # Camera registry
│   │   └── incident_v2.py      # Incident schema
│   ├── routes/
│   │   ├── cameras.py          # Camera status + live + demo trigger
│   │   ├── map.py              # /map/groups endpoint
│   │   ├── incidents_v2.py     # Incidents CRUD + WebSocket
│   │   ├── evidence.py         # Evidence file serving
│   │   └── nearby_services.py  # SerpApi lookup
│   └── services/
│       ├── camera_workers.py   # Multi-camera frame loop
│       ├── detection_service.py# YOLOv8 fire/crash inference
│       ├── event_capture.py    # N-of-M confirmation + clip encoding
│       ├── notification_service.py # Telegram + call + escalation
│       ├── dispatch_routing.py # Route planning + Mapbox cache
│       └── safety_guard.py     # Hard phone-number blocks
├── config/cameras.json         # Camera registry
├── frontend/                   # React + Vite + Mapbox GL
│   ├── src/pages/MapView.jsx   # Main hackathon dashboard
│   └── src/index.css           # Dashboard styles
├── data/                       # Sample video files
│   ├── crash.mp4
│   └── fire.mp4
├── evidence/                   # Generated evidence files
├── incidents.db                # SQLite database
├── models/                     # YOLOv8 model weights
├── scripts/                    # Utility scripts
│   ├── check_camera.py         # Verify phone camera is reachable
│   ├── add_phone_camera.py     # Register a phone camera
│   └── camera_replay.py        # Replay a video file for testing
├── docs/
│   ├── ARCHITECTURE.md         # System flow diagram
│   ├── DEMO_SCRIPT.md          # 3-minute demo walkthrough
│   └── LIMITATIONS.md          # Honest scope disclosure
├── run_dashboard.py            # Main launcher
├── .env                        # Environment config (not committed)
├── .env.example                # Template for .env
├── settings.yaml               # CLIP model settings
└── requirements.txt            # Python dependencies
```

---

## 🔧 Troubleshooting

### Port already in use

```bash
# Windows — find and kill the process
netstat -ano | findstr :8000
taskkill /PID <pid> /F

# Then restart
python run_dashboard.py --mode all
```

### Map shows blank / no tiles

- Check `frontend/.env` has a valid `VITE_MAPBOX_TOKEN`
- The dashboard has a built-in fallback (dots on dark background) if Mapbox is unreachable

### Phone camera not detected

- Ensure both devices are on the **same Wi-Fi / hotspot**
- Try opening the phone stream URL directly in a browser: `http://<phone-ip>:8080/video`
- Run: `python scripts/check_camera.py CAM-001`

### ffmpeg not found

Evidence clip encoding requires ffmpeg. Install it:
- **Windows:** `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html)
- **Linux:** `sudo apt install ffmpeg`
- **Mac:** `brew install ffmpeg`

### No incidents appear on the map

1. Check the backend is running: `curl http://localhost:8000/api/v1/map/groups`
2. Trigger a test incident: `Ctrl+Shift+D` → "Trigger test incident"
3. Or via API: `POST /api/v1/demo/trigger` with `{"camera_id":"CAM-SAMPLE-001","category":"fire"}`

### Detection models

To enable/disable detection models, edit `.env`:

```env
VIOLENCE_DETECTION=0    # 0 = OFF, 1 = ON
FALL_DETECTION=0
SNATCH_DETECTION=0
FIRE_DETECTION=1        # ✅ ON
CRASH_DETECTION=1       # ✅ ON
```

> **For demos:** Keep only `FIRE_DETECTION=1` and `CRASH_DETECTION=1` enabled. Set `LEGACY_DETECTORS_ENABLED=false`.

---

## 🛡️ Safety

- **DEMO_MODE=true** (default) restricts all outgoing calls/messages to explicitly configured demo recipients.
- Discovered service phone numbers (hospitals, police, fire stations) are **display only** — never auto-dialled.
- Known emergency numbers (100, 101, 102, 108, 112) are **hard-blocked** at the code level.
- See `docs/LIMITATIONS.md` for full disclosure.

---

## 📄 License

This project is developed for the hackathon demo. See `docs/LIMITATIONS.md` for scope and limitations.
