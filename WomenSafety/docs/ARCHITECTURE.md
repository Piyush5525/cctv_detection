# Architecture

## System Flow

```mermaid
flowchart TB
    subgraph Input["📹 Camera Sources"]
        CCTV["CCTV Stream<br/>RTSP / video file"]
        Phone["Demo Phone Camera<br/>HTTP MJPEG"]
    end

    subgraph Workers["⚙️ API-Owned Camera Workers"]
        W1["Latest-frame worker<br/>reconnect backoff"]
        W1 -->|"original res"| Evidence["Evidence frame buffer"]
        W1 -->|"downscaled ≤640px"| Sampler["Time-based frame sampler<br/>≥ 0.25s interval"]
    end

    subgraph Detection["🔍 Detection Pipeline"]
        Sampler --> FireDet["YOLOv8 Fire Detector"]
        Sampler --> CrashDet["YOLOv8 Crash Detector"]
        FireDet --> Capture["Event Capture Pipeline<br/>N-of-M confirmation<br/>pre/post buffer"]
        CrashDet --> Capture
    end

    subgraph Storage["💾 Persistence"]
        Capture -->|"best_frame + clip.mp4"| EvidenceFS["Evidence filesystem<br/>evidence/{cam}/{date}/{id}/"]
        Capture -->|"validated incident"| SQLite["SQLite incidents.db<br/>WAL mode + write lock"]
    end

    subgraph Dispatch["📨 Dispatch Backend"]
        SQLite --> NQ["Notification queue<br/>bounded, async"]
        NQ --> Telegram["Telegram alert<br/>photo + location pin<br/>Confirm / False alarm"]
        NQ --> Escalation["Escalation timer<br/>demo: 20s → voice call"]
        NQ --> SerpApi["SerpApi lookup<br/>nearest hospital/police/fire"]
        SerpApi --> Mapbox["Mapbox Directions<br/>route polyline + ETA"]
        Telegram -.->|"callback poll"| SQLite
    end

    subgraph SafetyLayer["🛡️ Safety Guard"]
        SG["Hard blocks:<br/>• No emergency numbers ever dialled<br/>• DEMO_MODE → allowlisted recipients only<br/>• Discovered service phones = display only"]
    end

    subgraph Frontend["🖥️ React Dashboard"]
        API["FastAPI<br/>/api/v1/*"]
        API -->|"REST + WebSocket"| MapView["Mapbox GL Map<br/>numbered camera dots<br/>hover → slideshow<br/>click → detail panel"]
        API -->|"MJPEG"| LivePanel["Live camera tiles<br/>phone status + FPS"]
        MapView --> Detail["Detail view<br/>clip player · detection metadata<br/>notification timeline<br/>dispatch plan + route line"]
    end

    CCTV --> W1
    Phone --> W1
    SQLite --> API
    EvidenceFS --> API
    Dispatch --> SQLite
    NQ -.-> SG
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single SQLite file, WAL mode | Single-process API; no distributed DB needed; WAL avoids reader/writer lock contention |
| Evidence as files, not blobs | Clip seek via HTTP Range; no 50 MB blobs in SQLite; filesystem is the natural choice |
| Detection downscale separate from evidence | Evidence stays original resolution for judge review; detection runs at 640px for speed |
| Write lock + WAL together | WAL handles reader/writer; process lock serialises competing writer threads (multiple cameras) |
| Notification queue after insert | Encoder thread never blocks on network I/O; durable record exists before any dispatch |
| Straight-line fallback routes | Mapbox Directions may be unavailable; geometric fallback is clearly labelled |
| DEMO_MODE as default | Safety-first: real emergency numbers are never contacted without explicit operator configuration |

## Directory Layout

```
WomenSafety/
├── api/
│   ├── core/config.py          # All settings, env-loaded
│   ├── models/
│   │   ├── camera.py           # Camera registry (config/cameras.json)
│   │   └── incident_v2.py      # CCTV incident schema
│   ├── routes/
│   │   ├── cameras.py          # Status, live MJPEG, demo trigger
│   │   ├── map.py              # /map/groups (camera-grouped incidents)
│   │   ├── incidents_v2.py     # CRUD + WebSocket push
│   │   ├── evidence.py         # File serving with HTTP Range
│   │   └── nearby_services.py  # SerpApi lookup endpoint
│   └── services/
│       ├── camera_workers.py   # Multi-camera frame loop
│       ├── detection_service.py# Fire/crash YOLO inference
│       ├── event_capture.py    # N-of-M confirmation + encoding
│       ├── notification_service.py # Telegram + call + escalation
│       ├── dispatch_routing.py # Route planning + Mapbox cache
│       └── safety_guard.py     # Hard phone-number blocks
├── config/cameras.json         # Camera registry
├── frontend/
│   ├── src/pages/MapView.jsx   # Main hackathon dashboard
│   └── src/index.css           # Projector-optimised styles
├── evidence/                   # Generated evidence files
├── incidents.db                # SQLite database
└── docs/
    ├── ARCHITECTURE.md         # This file
    ├── DEMO_SCRIPT.md          # 3-minute demo walkthrough
    └── LIMITATIONS.md          # Honest scope disclosure
```
