# Three-Minute Demo Script

> **Goal:** Show judges a working camera-to-dispatch pipeline with
> real detection, real evidence, and honest labelling of what is
> pre-recorded vs. live.

---

## 🎬 Script (3 minutes)

### 1. Map Overview (0:00–0:40)

Open the dashboard at `http://localhost:3000/map`.

- Point out the **DEMO MODE** badge in the header — this is live software
  with safety rails: it never contacts real emergency services.
- Show the numbered camera markers: each dot is one registered camera,
  colour-coded by the most severe detected incident type
  (🟠 fire, 🔴 crash, 🟣 snatch).
- Point out the **legend** and the **demo phone ring** (teal outline)
  that distinguishes phone cameras from CCTV.
- The map auto-fits to all cameras on load — a clean starting view.

### 2. Hover & Click (0:40–1:20)

- **Hover** over a camera marker: the popup shows the camera name,
  location, total incident count, and a rotating thumbnail slideshow
  (every 3 seconds) with category, timestamp, and confidence score.
- **Click** a marker to open the **detail panel**:
  - Note the **"Recorded footage replay"** badge — honesty about the
    data source.
  - Play the evidence **clip** and show the **best frame**.
  - Point out detection metadata: peak/mean confidence, threshold,
    model name, and "3 of 5 frames confirmed."
  - Scroll to the **Notification Timeline**: Telegram sent, operator
    button pressed, call placed or cancelled — all real records.
  - Show the **Dispatch Plan**: nearest hospital, police, and fire
    station with name, phone, distance, and ETA.
  - Point out the **route line** on the map (dashed teal).

### 3. Live Camera & Demo Trigger (1:20–2:10)

- Scroll to the **Live Cameras** section: show the phone tile with
  its online/offline status and effective FPS.
- If a phone camera is live, wave at the camera and show the
  annotated stream updating.
- If detection is quiet, press `Ctrl+Shift+D` to open the demo
  controls menu, then click **Trigger test incident**.
  - The new incident's marker **pulses** on the map.
  - A **toast** notification appears.
  - The map **flies to** the new camera.
  - Click it to show the freshly generated evidence and dispatch.

### 4. Close (2:10–3:00)

- Click **"Back to overview"** to fly the map back to all cameras.
- Emphasise the safety boundary:
  - Discovered service phone numbers are **display only** — never
    auto-dialled.
  - Demo mode restricts all outgoing contact to explicitly configured
    demo recipients.
  - The models are pre-trained open-source checkpoints; thresholds
    are configurable; a human acknowledges or dismisses every incident (an unattended one escalates to a single demo call).
- End with: *"This is a working pipeline, not a mockup — camera in,
  evidence out, dispatch plan displayed, all within safety rails."*

---

## ✅ Pre-Demo Checklist

Run through this **before judges arrive**:

| # | Check | How to verify |
|---|-------|---------------|
| 1 | Mapbox token set | `frontend/.env` has `VITE_MAPBOX_TOKEN=pk.…` |
| 2 | Telegram keys set | `.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| 3 | `DEMO_MODE=true` | default in config (not in `.env`); `DEMO_PHONE_NUMBER` and `DEMO_TOKEN` set in `.env`, `VITE_DEMO_TOKEN` in `frontend/.env` |
| 4 | Backend running | `python run_dashboard.py --mode api --no-build` → binds 127.0.0.1:8000, no crash in first 5s (`--mode all` also starts the legacy detector loop; not needed) |
| 5 | Frontend running | `cd frontend && npm run dev` → `http://localhost:3000` loads |
| 6 | Hotspot joined | Laptop and phone on same Wi-Fi / hotspot |
| 7 | Phone camera online | `python scripts/check_camera.py <phone-camera-id>` → `online` |
| 8 | Phone reachable | Open `http://<phone-ip>:8080/video` in browser → live feed |
| 9 | Cache warmed | `/api/v1/cameras/<id>/nearby-services` returns data (not 503) |
| 10 | Evidence exists | At least one incident in the map (`/api/v1/map/groups` non-empty) |
| 11 | ffmpeg available | `ffmpeg -version` → prints version (required for clip encoding) |
| 12 | Demo trigger works | `Ctrl+Shift+D` → "Trigger test incident" → toast appears (needs `DEMO_TOKEN` in `.env` and `VITE_DEMO_TOKEN` in `frontend/.env` at build time) |
| 13 | Showcase built | `python scripts/build_showcase.py <5 ids from demo/candidates.html>` → `demo/showcase.db`; then Demo Controls → "Load showcase" |
| 14 | Live smoke tests passed | `python scripts/smoke_test.py --serpapi --yes`, `--mapbox --yes`, then (API stopped) `--telegram --yes` and `--call --yes` |
| 15 | Clean start | `python scripts/reset_demo.py` (backs up, then 0 incidents) or Demo Controls → "Reset demo" |

### 🆘 Backup Plan

If something goes wrong during the live demo:

1. **Phone camera offline:** Show the recorded replay incidents instead.
   Click a marker with the "Recorded footage replay" badge and walk
   through the evidence and dispatch plan.

2. **Map tiles fail to load:** The dashboard has a built-in fallback
   view with positioned dots on a dark gradient background. Routing
   shows straight-line estimates with distances.

3. **No incidents in DB:** Load the showcase (Demo Controls → "Load showcase") or use the demo trigger (`Ctrl+Shift+D` →
   "Trigger test incident") to create one on the fly — it uses a
   stored sample clip and generates real evidence and detection metadata.

4. **Backend crash:** Restart with `python run_dashboard.py --mode api --no-build`.
   SQLite data survives restarts (WAL mode, file-backed).

5. **Telegram not configured:** All other functionality works without
   Telegram. The notification timeline will show "No notification
   attempts recorded" — explain that Telegram integration is configured
   per-deployment.
