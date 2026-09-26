# Incident Command Dashboard

A real-time incident detection and management dashboard for the WomenSafety project.

## Features

- **Real-time Incident Monitoring**: Live feed of detected incidents (violence, falls, snatching, fire, crashes)
- **Interactive Map**: Jaipur-based map with incident markers and heatmap
- **Evidence Gallery**: Video clips and thumbnails for each incident
- **Analytics**: Trends, severity distribution, camera performance, response times
- **System Health**: CPU, memory, GPU, and detection pipeline monitoring
- **WebSocket Integration**: Real-time updates without polling

## Architecture

```
WomenSafety/
├── api/                    # FastAPI backend
│   ├── main.py            # FastAPI app entry point
│   ├── core/config.py     # Configuration
│   ├── models/            # Pydantic models
│   ├── routes/            # API routes
│   └── services/          # Business logic
├── frontend/              # React + Vite frontend
│   ├── src/
│   │   ├── components/    # Reusable UI components
│   │   ├── pages/         # Page components
│   │   ├── context/       # React context providers
│   │   └── utils/         # Utilities
│   └── package.json
├── main.py                # Detection pipeline (existing)
├── api_client.py          # API integration for detection
├── run_dashboard.py       # Unified runner script
└── evidence_clips/        # Evidence clip recording
```

## Quick Start

### 1. Install Dependencies

```bash
# Backend dependencies
pip install -r requirements-api.txt

# Frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Build Frontend

```bash
cd frontend
npm run build
cd ..
```

### 3. Run Complete System

```bash
# Run everything (API + Detection + Frontend)
python run_dashboard.py --mode all

# Or run components separately:
python run_dashboard.py --mode api      # FastAPI only
python run_dashboard.py --mode detection # Detection only
python run_dashboard.py --mode build     # Build frontend only
```

### 4. Access Dashboard

- **Dashboard**: http://localhost:8000
- **API Docs**: http://localhost:8000/api/docs
- **WebSocket**: ws://localhost:8000/api/v1/incidents/ws

## Environment Variables

Create a `.env` file in the WomenSafety directory:

```env
# Camera settings
CAMERA_SOURCE=0                    # Camera index or video file path
CAMERA_ROTATE=90                   # 0, 90, -90, 180, 270
CAMERA_ID=CAM-001                  # Camera identifier
CAMERA_LOCATION=MI Road, Jaipur    # Location name
CAMERA_LAT=26.9124                 # Latitude
CAMERA_LNG=75.7873                 # Longitude

# Detection toggles
VIOLENCE_DETECTION=1
FALL_DETECTION=1
SNATCH_DETECTION=1
FIRE_DETECTION=1
CRASH_DETECTION=1

# API settings
API_ENABLED=1
DETECT_WIDTH=640

# Alert settings (existing)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
OMNIDIM_API_KEY=your_key
OMNIDIM_AGENT_ID=your_agent_id
ALERT_PHONE_NUMBER=+91xxxxxxxxxx
```

## API Endpoints

### Incidents
- `GET /api/v1/incidents` - List incidents with filtering, pagination, sorting
- `GET /api/v1/incidents/recent` - Get recent incidents
- `GET /api/v1/incidents/{id}` - Get incident details
- `POST /api/v1/incidents` - Create incident
- `PATCH /api/v1/incidents/{id}` - Update incident
- `DELETE /api/v1/incidents/{id}` - Delete incident
- `WS /api/v1/incidents/ws` - Real-time incident updates

### Analytics
- `GET /api/v1/incidents/analytics/summary` - KPI summary
- `GET /api/v1/incidents/analytics/trends` - Hourly trends
- `GET /api/v1/incidents/analytics/heatmap` - Map heatmap data

### Evidence
- `GET /api/v1/evidence` - List evidence clips
- `GET /api/v1/evidence/{filename}` - Download video clip
- `GET /api/v1/evidence/thumbnail/{filename}` - Get thumbnail

### System
- `GET /api/v1/system/health` - System health check
- `GET /api/v1/system/status` - System status

## Detection Integration

The detection pipeline (`main.py`) now integrates with the API client:

1. When an incident is detected (violence, fall, snatch, fire, crash)
2. An evidence clip is recorded (5s before + 5s after)
3. Incident is submitted to the API via `api_client.submit_incident()`
4. Real-time WebSocket pushes update to dashboard

Cooldown: 30 seconds per incident type per track ID to prevent spam.

## Frontend Development

```bash
cd frontend
npm run dev    # Development server on http://localhost:3000
npm run build  # Production build
npm run preview # Preview production build
```

## Project Structure Details

### Backend Services

- **IncidentService**: Manages incident CRUD, filtering, analytics, WebSocket broadcasting
- **EvidenceService**: Frame buffering, clip recording, thumbnail generation

### Frontend Pages

- **Dashboard**: KPIs, live feed, trends chart, severity distribution, system health
- **Live Incidents**: Filterable, sortable incident table with inline actions
- **Map**: Leaflet map with incident markers, heatmap toggle, camera stats
- **Evidence**: Grid/list view of video clips with preview modal
- **Analytics**: Pie charts, bar charts, line charts, camera performance table
- **Settings**: Organized sections for general, notifications, detection, storage, network, security

### Key Components

- **IncidentCard**: Expandable incident card with evidence preview
- **KPICard**: Metric display with trend indicator
- **MiniMap**: Compact map for dashboard
- **Layout**: Sidebar navigation, top bar with notifications/user menu

## Extending the System

### Adding New Incident Types

1. Add to `IncidentType` enum in `api/models/incident.py`
2. Add mapping in `api_client.py` `map_detection_to_incident()`
3. Add color/icon in `frontend/src/utils/types.js`
4. Update detection pipeline to call `send_incident_to_api()`

### Custom Analytics

1. Add method to `IncidentService` in `api/services/incident_service.py`
2. Add route in `api/routes/incidents.py`
3. Create chart component in frontend

## Performance Notes

- Detection runs on separate thread from display
- API client uses async queue for non-blocking incident submission
- Frontend uses WebSocket for real-time updates
- Evidence clips buffered in memory (10s rolling buffer)
- Dashboard polls analytics every 30s, incidents via WebSocket

## Troubleshooting

### Frontend not loading
- Ensure `npm run build` completed successfully
- Check `frontend/build` directory exists

### WebSocket not connecting
- Check firewall allows port 8000
- Verify `API_ENABLED=1` in environment

### Detection not sending incidents
- Check `API_ENABLED=1`
- Verify FastAPI is running on port 8000
- Check logs for `[APIClient]` messages

### Evidence clips not recording
- Check `evidence_clips/` directory permissions
- Verify OpenCV can write MP4 (may need `ffmpeg`)

## License

Part of the WomenSafety project.