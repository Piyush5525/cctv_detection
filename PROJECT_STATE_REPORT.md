# PROJECT STATE REPORT

Audit date 2026-10-01 (IST). Repo root `D:\Projects\Detection-Models`, app in `WomenSafety/`. Read-only audit: no existing tracked or untracked file was edited, formatted or deleted by me.
Everything below was observed in code or by running it. "not verified" means I could not confirm it.

**Audit footprint (be aware):**
- I wrote 8 screenshots to `WomenSafety/docs/screenshots/audit_*.png` and this file. All scratch scripts and run data went to the session scratchpad.
- I ran the API on port 8765 with `INCIDENTS_DB_PATH`, `EVIDENCE_ROOT_V2` and cache paths redirected to scratch, `ALERTS_ENABLED=false`, no Telegram, Omnidim or SerpApi credentials in the process, and a socket guard blocking non-local connections in the safety tests. The server is now stopped.
- Nothing was installed. The frontend was built into scratch (`vite build --outDir`); `node_modules/.vite` cache may have been touched.
- **A process I did not start is running:** PID 51188, `run_dashboard.py --mode api --no-build`, started 14:36 IST. It runs live camera workers against the real `incidents.db` and `evidence/` and was still writing incidents during the audit (`incidents.db` went 289 → 316 rows). Its writes are not mine.
- The project's own `python -m unittest discover -s tests` run also started the camera workers under default paths (console showed `EventCapture:CAM-SAMPLE-003`). It may have written a few rows to the real DB too. I cannot separate that from PID 51188's writes.

---
## 1. REPO FACTS

**Git**
- Branch `phase1c-wip`; the tree is NOT clean: 17 modified plus 15 untracked entries (32 lines in `git status`).
- Only 8 commits exist in total (asked for 20):

| Hash | Author | Message |
|---|---|---|
| 7cbb763 | Piyush5525 | Add CCTV-only incident capture pipeline with sampling, hardening, and FPS investigation |
| a5c4275 | Piyush5525 | Merge branch 'main' of github.com/vjn6805/Detection-Models |
| c47575a | vjn8025 | Added model weight files |
| bc41220 | Piyush5525 | Fix API/env bugs: rtmlib version, longitude default, WS proxy |
| 6f69001 | vjn8025 | Merge branch 'main' … |
| 18cfd43 | vjn8025 | Made changes of ASG error and SHA256 certificate |
| 067cba0 | Veer Jain | Update README file |
| 4a71b31 | vjn8025 | first commit |

- **Uncommitted, grouped:**
  - Modified, `api/`: `core/config.py`, `db.py`, `main.py`, `models/camera.py`, `models/incident_v2.py`, `routes/map.py`, `services/incident_service_v2.py`.
  - Modified, other: `main.py`, `Call_Alert.py`, `Telebot_Alert.py`, `.env.example`, `CHANGELOG.md`, `config/cameras.json`, `frontend/src/{components/Layout.jsx, index.css, tailwind.css, pages/MapView.jsx}`.
  - Untracked: `api/routes/{cameras,nearby_services}.py`, `api/services/{camera_workers,demo_trigger,dispatch_routing,nearby_services,notification_service,safety_guard}.py`, `scripts/{add_phone_camera,build_candidates_gallery,check_camera}.py`, `tests/`, `docs/`, `demo/`, `data/camera_check_CAM-SAMPLE-001.jpg`.
  - **The whole dispatch/notification/camera-worker layer and the docs are uncommitted.**
- `.gitignore` is in `WomenSafety/`; the repo root has none. `.env`, `frontend/.env`, `incidents.db`, `backups/`, `evidence/`, `evidence_clips/` and `frontend/build/` are ignored, so a fresh clone must build the frontend.

**Folders** (WomenSafety, excluding `frontend/node_modules`; its size was not captured, it has 378 top-level entries)

| Folder | Files | Size |
|---|---|---|
| evidence_clips (scraped news images, gitignored) | 584 | 501 MB |
| evidence (v2 incident evidence, gitignored) | 1248 and growing | 335 MB |
| scraped_data | 63 | 48 MB |
| models | 2 | 27 MB |
| data | 15 | 12 MB |
| frontend | 41 | 11 MB |
| docs | 12 incl. my 8 shots | 3.6 MB |
| backups | 13 | 3.1 MB |
| api | 72 | 0.7 MB |
| scripts | 48 | 0.4 MB |
| other (snatch/fall/fire/crash modules, tests, archive, config) | — | <1 MB each |

- Sibling folder `snatch_detection_system/` at the repo root: `make_ppt.py`, `models_arch`, `core`, `data`, `evaluate.py`, docs. It is not wired to the API.
- 10 largest files: 9 are `evidence_clips/article_*.jpg` (11–25 MB each, untracked); the other is `models/crash_best.pt` (22.5 MB, tracked).

**Versions and dependencies**
- Python 3.12.10, Node v24.19.0.
- fastapi 0.141.1, uvicorn 0.54.0, pydantic 2.13.5, pydantic-settings 2.15.0, ultralytics 8.4.163, torch 2.14.0, opencv-python 5.0.0.93, pyTelegramBotAPI 4.37.0, numpy 2.5.3. All requirements are unpinned (`>=` or bare).
- Imports vs requirements:
  - `yt_dlp` (scripts only) is not listed.
  - `clip` (git URL) and `models_arch` are local or git.
  - `requirements.txt` has no fastapi/uvicorn; `requirements-api.txt` duplicates all of requirements.txt.
  - Listed but never imported: ftfy, jupyter, lap, regex, rtmlib, scikit-learn, scipy, tqdm.
  - package.json: playwright and concurrently are only used by tooling scripts.

**Multi-agent overlap, dead code, leftovers**
- Two incident stacks: v1 (`api/routes/incidents.py`, `services/incident_service.py`, `models/incident.py`) is unmounted dead code. v2 is live.
- `api_client.py` (used by `main.py`) POSTs to `/incidents`, which no longer exists (v2 returns 405).
- `/system/health` hardcodes every detector as `loaded: true`, `uptime_seconds=0`, and a wrong `disk_percent` (3e-8).
- Frontend pages `Dashboard`, `LiveIncidents`, `Analytics` and `EvidenceGallery` call v1 endpoints that don't exist in v2 (`/incidents/recent` → 404, `DELETE /incidents/{id}` → 405). The catch-all SPA route returns **HTTP 200 `{"detail":"Not found"}`** for unknown `/api/...` paths, which hides this.
- Leftovers: `__pycache__/strict_dedup_scan.cpython-312.pyc` with no source; `dropped_log.jsonl`, `live_frame.jpg`, `tutorial.ipynb`, `app.py` (streamlit), `run.py`, `archive/`, 13 `backups/` files, `docs/take_screenshots.js`.
- TODO/FIXME: none found in `api`, `frontend/src`, `scripts` or `tests`. Intent is in comments instead (e.g. "Phase 3 to-do list").
- Stale comment: `config.py` says `LEGACY_DETECTORS_ENABLED` "Defaults to True"; the value is False.

---
## 2. FEATURE STATUS TABLE
(See the end of the chat reply; same table.)

| Item | Status | Files / endpoints | How verified |
|---|---|---|---|
| Camera registry | partial | `config/cameras.json`, `api/models/camera.py` | Loaded 4 cams; India-bbox and credential validators read in code. Sample cams and the CAM-001 placeholder are all `real_installation` although they replay video files. CAM-001 `stream_source:"0"` fails (see below) |
| Phone camera support | partial / unverified | `add_phone_camera.py`, `check_camera.py`, `camera_type`, `display_name` | Scripts read, not run (they write `cameras.json` / `data/`). Label "Demo phone camera - X" verified by instantiation. MJPEG ingest NOT verified: OpenCV timed out after 30 s on my local simulated MJPEG server (simulator vs cv2 5.0 unclear). New cameras need an API restart. Invalid entries are silently skipped |
| Live workers / reconnect / status / live | partial | `camera_workers.py`, `/cameras/status`, `/cameras/{id}/live` | 3 sample cams `online`, about 1.2 fps each with all three running; offline→backoff loop shows `stream unreachable`. CAM-001 offline because `cv2.VideoCapture("0")` fails (int 0 opens). `/live` returns 503 when workers are off; 200 MJPEG not verified. Reconnect-after-drop not verified. `env:` source with an unset var raises an uncaught `ValueError` and kills the thread |
| Frame sampler, EventCapturePipeline | done (core) | `frame_sampler.py`, `event_capture.py` | Live workers produced incidents with best frame, annotated frame, thumbnail, 8–12 s mp4 (ffmpeg present), SHA-256s. Quarantine table has 0 rows, so the encode-failure paths were not exercised by me (CHANGELOG says simulated) |
| Fire / crash detectors | partial | `detector_interface.py`, `models/*.pt` | Both run. **Floor in use = 0.0** (`FIRE_CRASH_CONFIDENCE_FLOOR` default); per-detector threshold 0.5 is not what gates incidents. Of 289 stored incidents, 109 have peak conf <0.5 (0.3–0.4). Cross-class FPs (below) |
| Incident schema / SQLite / evidence / endpoints | done | `db.py`, `incident_service_v2.py`, `evidence.py`, `/incidents`, `/map/groups`, `PATCH …/status` | Restart persistence 7→7. Range request gives 206 with `Content-Range`. Traversal attempts (`..%2F`, `%2e%2e`, raw) leaked no file (404 or SPA JSON); resolve-within-root guard read. PATCH 200, bad status 422, unknown 404. Incident JSON exposes absolute server file paths |
| Nearby services (SerpApi) + cache | partial / unproven | `nearby_services.py`, `/cameras/{id}/nearby-services` | Cache path and fixture verified (unit tests + my fixture). **Real SerpApi never exercised.** Under `uvicorn api.main:app` / `--mode api`, `.env` is never loaded into `os.environ`; in the real DB all 141 plans are `lookup_error: SERPAPI_KEY is not set` although the key is set in `.env` |
| Dispatch plan / routing | partial | `dispatch_routing.py` | Plan with fire/hospital/police cards plus route geometry verified using a fixture cache. Only `straight_line_fallback` was seen; **Mapbox Directions never exercised** (token not in env) |
| Notification service | mostly done (mocked) | `notification_service.py`, `safety_guard.py` | 25/25 mocked checks passed (section 3). Telegram photo branch not exercised (only the text branch). Real Telegram/Omnidim and the callback poller are unverified |
| Legacy alert path | done (gated), not run live | `main.py`, `Telebot_Alert.py`, `Call_Alert.py` | Both legacy senders check `ALERTS_ENABLED` and `safety_guard`. Fire/crash legacy sends were removed from `main.py` (grep confirms; only violence/fall/snatch still call them). With `LEGACY_DETECTORS_ENABLED=false` the three detectors are not constructed (code, `main.py:196-215`). `main.py` not run end to end |
| Demo features | partial | `/demo/trigger`, `demo_trigger.py`, `demo/candidates.html` | Trigger works (200, about 3 s). `showcase.db`: **not found**. Reset script: **not found**. Gallery exists: 6 test_replay candidates (5 road_accident + 1 fire) |
| Dashboard | mostly done | `frontend/src/pages/MapView.jsx` | See section 3 screenshots. Numbered dots, hover slideshow, detail panel, timeline, dispatch plan and route line, toast and pulse (via polling), offline dots all work. **WebSocket never delivers.** Live Cameras panel only shows phone cams (empty here). Other pages are broken |
| Docs | partial | `docs/*.md` | Several claims don't match the code (section 5) |

---
## 3. WHAT I ACTUALLY RAN

| Check | Result | Evidence |
|---|---|---|
| Existing unit tests | PASS | `python -m unittest discover -s tests`: 8 tests OK (pytest not installed). They start camera workers under default paths (side effect) |
| Backend starts | PASS | `Application startup complete`, port 8765; 3 of 4 cameras online |
| Route list | PASS | Below |
| Frontend builds | PASS | `vite build` in 28 s. Hashes `index-THEypFW4.js` and `index-BFsdlt1D.css` are identical to the existing `frontend/build`, so it is current. Chunk warning: mapbox-gl 1.9 MB, index 0.79 MB |
| Screenshots 1920x1080 | PASS (6 of 7 asked for) | `docs/screenshots/audit_01…08`: map, hover slideshow, detail, timeline+dispatch, live panel (empty state; no phone), pulse+toast, dispatch route, offline fallback. A live phone tile was not captured |
| Browser console | PASS | 0 errors, 0 page errors. Only 2 GL perf warnings. Failed requests are only aborted Mapbox tiles and aborted `clip.mp4` range loads (benign navigation aborts) |
| Full pipeline, mocked notifications | PASS | Details below |
| Safety tests with mocks | PASS 25/25 | Below |
| Determinism | PARTIAL | Two demo triggers: identical `sha256_frame` 8c98a02a… and `sha256_clip` 1b923532…. Live detection determinism not verified (wall-clock gate; same clip gave peaks 0.47 and 0.79 in different loops) |
| Restart persistence | PASS | 7 incidents before and after a kill/restart |
| WebSocket | **FAIL (push)** / PASS (connect) | Connects OK, but no message within 12 s after a new incident (and 0 frames across the Playwright run). Cause: `_notify()` in `incident_service_v2.py` has no caller. Polling (2 s) drives the UI and was observed to produce toast and pulse |
| Effective config dump | PASS | Below |
| FPS and memory, 1 simulated camera | PASS | Below |

**Routes** (method path): GET `/`; GET `/api/v1/cameras/status`; GET `/cameras/{id}/live`; GET `/cameras/{id}/nearby-services`; POST `/demo/trigger`; POST `/detect`; GET `/emergency/nearest`; GET `/emergency/incidents/{id}/nearest`; GET `/evidence`; GET `/evidence/camera/{cam}/{date}/{file}`; GET `/evidence/thumbnail/{file}`; GET `/evidence/v2/{cam}/{date}/{incident}/{file}`; GET and DELETE `/evidence/{filename}`; GET `/incidents`; GET `/incidents/_internal/quarantine`; GET `/incidents/{id}`; PATCH `/incidents/{id}/status`; GET `/map/groups`; GET `/system/frame`, `/system/health`, `/system/status`; GET `/{full_path}` (SPA catch-all); WS `/api/v1/incidents/ws` (not in OpenAPI). There is no auth on any of them. There is no dedicated notification-timeline endpoint: the timeline is the `notifications[]` array inside the incident JSON.

**Example incident** (demo trigger, `CAM-SAMPLE-002`, fire; paths redacted): `source: test_replay`, `status: new`, lat/lng 26.915/75.792, `detector_source: demo-trigger`, `model_name: stored-sample`, `peak_confidence: 0.99`, `threshold_applied: 0.0`, `frames_confirmed: "3 of 3"`, bbox = full frame `[0,0,640,352]`, clip 2.0 s at 1.5 fps.
- Timeline: `dispatch queued (internal)` → `telegram skipped: ALERTS_ENABLED is false` → `call skipped: ALERTS_ENABLED is false`.
- Dispatch plan: required `[fire, hospital, police]`, each `available` with a fixture facility, 0.99–1.22 km, ETA 2.0–2.4 min, `route_source: straight_line_fallback`, `contact_policy: display_only_never_auto_dial_discovered_numbers`.
- The services were my own labelled "AUDIT FIXTURE" cache entries, because SerpApi is not reachable from the process.

**Safety tests (mocked `requests.post` and a fake bot, non-local sockets blocked), 25/25 pass:**
- 100/101/102/108/112 plus `+91 112`, `0112`, `91-108`, `+91100`, `0100` are blocked, even when set as the allowlisted `DEMO_PHONE_NUMBER`.
- Non-allowlisted, empty and facility-style numbers are blocked.
- `ALERTS_ENABLED=false` sends nothing and records skipped.
- Low-confidence call fires only after the delay (0 / 0 / 1 posts at t=0 / 0.5 / 1.7 s with a 1 s test delay); a call at confidence ≥0.6 is immediate.
- Telegram sends message, location pin and inline buttons.
- "False alarm" cancels the pending call and sets `false_positive`.
- "Escalate now" calls immediately.
- An unknown callback action is rejected.
- Cooldown is per camera and category.
- `MAX_CALLS_PER_HOUR` cap holds (2 of 4 with cap 2).
- A non-allowlisted chat is blocked when the allowlist is set.
- Telegram failure is retried 3 times and recorded; call failure is recorded without a crash.
- `DEMO_PHONE_NUMBER=112` is refused by the service.
- `DEMO_MODE=false` still dials only the allowlisted number.
- Missing Omnidim credentials are recorded as failed.
- A real telebot with a fake token and the network blocked fails safely.
- **Observations, not failures:** (a) with `TELEGRAM_CHAT_ID_ALLOWLIST` unset, any chat id is allowed (`expected = allowlist or chat_id`, so the allowlist is vacuous); (b) the "Confirm" button also cancels the pending call; (c) `DEMO_MODE` only switches the delay (20 s vs 60 s), the allowlist applies always.

**Effective config** (all `[default]`; `.env` sets none of these; `ALERTS_ENABLED` and `DEMO_MODE` were not overridden in the dump run):

| Setting | Value |
|---|---|
| ALERTS_ENABLED | False |
| DEMO_MODE | True |
| LEGACY_DETECTORS_ENABLED | False |
| FIRE_CRASH_CONFIDENCE_FLOOR | 0.0 |
| SAMPLE_INTERVAL_S | 0.25 |
| DETECT_MAX_WIDTH | 640 |
| LIVE_VIEW_MAX_FPS | 8.0 |
| LIVE_CAMERA_WORKERS_ENABLED | True |
| ESCALATION_DELAY_S / DEMO_ESCALATION_DELAY_S | 60 / 20 |
| CALL_MIN_CONFIDENCE | 0.6 |
| NOTIFICATION_COOLDOWN_S | 120 |
| MAX_CALLS_PER_HOUR | 5 |
| NOTIFICATION_MAX_RETRIES | 3 |
| NOTIFICATION_RETRY_BACKOFF_S | 2.0 |
| EVENT_CONFIRM_N / M | 3 / 5 |
| PRE / POST_EVENT_SECONDS | 8 / 8 |
| EVENT_END_GAP_SECONDS | 5 |
| EVENT_MERGE_SECONDS | 15 |
| MAX_ENCODE_QUEUE_SIZE | 8 |
| JPEG_QUALITY | 90 |
| RETENTION_DAYS | 30 |

- `.env` (key names only): the five detector toggles are set (CRASH=1, the rest 0), `CAMERA_*` and `SERPAPI_KEY` are set, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OMNIDIM_*` and `ALERT_PHONE_NUMBER` are empty, and `DEMO_PHONE_NUMBER`, `DEMO_MODE`, `ALERTS_ENABLED` and the allowlist are absent. With the current `.env`, a call can never be placed: `DEMO_PHONE_NUMBER` is empty, so the guard blocks it.

**FPS and memory, 1 simulated camera** (`CAM-SAMPLE-001`, `crash.mp4`, 16-core CPU, no GPU, 60 s):
- Detection about 2.7–3.2 fps against a 4 fps target; reader fps about 2.5–4. The reader is tied to detection, so a real RTSP/MJPEG stream would lag.
- With all 3 workers running concurrently: about 0.6–1.2 fps each.
- RSS: 15 MB at start, 301 MB after models, 603 MB 10 s after the worker started, 664 MB at 70 s. The increase is about 360 MB for the camera, and still growing at about 60 MB per minute at the end; whether it plateaus is **not verified**.

**Not run, and why:**
- Real Telegram, call, SerpApi and Mapbox Directions: forbidden or no credentials in the process.
- Live phone stream: no phone, and the simulated MJPEG source was not accepted by OpenCV.
- `add_phone_camera.py`: would edit `cameras.json`.
- `check_camera.py`: would overwrite `data/camera_check_*.jpg`.
- `retention_cleanup.py` and the migrate/restore scripts: destructive.
- Legacy `main.py` loop: needs the legacy models and a window or source.
- Dashboard/Analytics/Incidents/Evidence pages: not exercised visually.

---
## 4. DATA AND HONESTY CHECKS

**Mock or hardcoded grep**
- Frontend: no sample-incident arrays, no `DEFAULT_LOCATIONS`; `Math.random` appears only in an id helper (`utils/format.js`). Fixed values: map initial view 75.79/26.91, header placeholder "Officer 1", a Settings page of static rows.
- Backend: `demo_trigger.py` uses fixed 0.99 confidence and a full-frame box on a stored frame; `system.py` health is hardcoded; `config/cameras.json` holds fixed coordinates.
- Legacy incident `notification_status` field is `None` or `"not_implemented"` on old rows.

**Dashboard default data** (a snapshot of the real `incidents.db`, 289 rows; it is 316 now and growing from PID 51188)

| Camera | Category | Source | Count |
|---|---|---|---|
| CAM-SAMPLE-003 (`snatch.mp4`, no crash in it) | road_accident | live | 97 |
| CAM-SAMPLE-002 (`fire.mp4`) | fire | live | 114 |
| CAM-SAMPLE-002 (`fire.mp4`) | road_accident | live | 35 |
| CAM-SAMPLE-001 (`crash.mp4`) | road_accident | live | 37 |
| CAM-SAMPLE-001 | road_accident | test_replay | 5 |
| CAM-SAMPLE-002 | fire | test_replay | 1 |

- 283 of 289 are labelled `source: live`, but come from looping sample video files, so the "🔴 Live detection" badge is misleading.
- At least 132 are false positives by construction (the crash model fires on the fire clip and on the snatch clip).
- 109 have peak confidence <0.5.
- All have `status: new`. 141 carry dispatch plans, all error plans.
- Every camera is `location_basis: real_installation`, `camera_type: cctv`.
- No news-scrape data is served by v2, but 501 MB of `evidence_clips` and `scraped_data` sit on disk and the legacy `/evidence` routes still exist.
- A fresh audit DB (my run) started with 0 rows. Workers add real "live" rows within about 1 minute, and after about 10 min there were 5.

**Secrets hygiene**
- `.env` and `frontend/.env` are gitignored and untracked (`git check-ignore` confirms; `git ls-files` lists only `.env.example`).
- `git grep` over all 8 commits for token, key and phone assignment patterns found only placeholders: `README.md:283` `TELEGRAM_BOT_TOKEN=your_…`, `README.md:287` `OMNIDIM_API_KEY=your_…`, and a `+91xxxxxxxxxx` or `…3210`-style example in comments. No Mapbox `pk.`/`sk.` keys, bot-token shapes or real phone numbers were found in tracked files or history (pattern-based, not exhaustive).
- Local `frontend/.env` holds a public Mapbox `pk.` token (baked into the build, expected). Local `.env` has `SERPAPI_KEY` set (value not printed).
- Absolute local paths (`C:\Users\…`) are stored in incident JSON and returned by the API.
- No auth anywhere, `CORS *` with credentials, and `run_dashboard.py` binds `0.0.0.0`.

---
## 5. KNOWN PROBLEMS
(See the end of the chat reply; same table.)

| # | Sev | Problem | Evidence | Fix | Effort |
|---|---|---|---|---|---|
| 1 | High | `.env` not loaded in API-only runs, so SerpApi, Mapbox, Telegram and Omnidim vars are invisible. They are read via `os.environ`, and only `main.py` calls `load_dotenv` | `os.environ` has no SERPAPI_KEY while `settings` has it; 141 DB plans say "SERPAPI_KEY is not set"; the live instance runs `--mode api` | `load_dotenv()` in `api/core/config.py` | S |
| 2 | High | Real DB is full of synthetic "live" incidents (310+): looping sample clips, 132+ false positives (crash model firing on the fire clip and on the snatch clip), floor 0.0, 109 below 0.5 conf, badge says "Live detection" | `incidents.db` counts above; PID 51188 still adding | Mark sample cameras `source` as replay/simulated, set floor ≥0.5, wipe or archive, use a clean demo DB | M |
| 3 | High | WebSocket push never fires (`_notify` has no caller); docs and CHANGELOG claim "WebSocket + polling" | 0 WS frames after a new incident | Call `_notify` from a thread-safe loop hook, or drop the claim | S–M |
| 4 | High | Demo "fire" trigger uses `data/fire.mp4` frame 0, which is pure black (mean brightness 0.0): black best frame, thumbnail and clip. The same trigger is a fixed 0.99 full-frame box, not a real detection | brightness check; offline screenshot shows black media | Seek to a flame frame; label as synthetic | S |
| 5 | High (demo) | No `demo/showcase.db`, no reset script; "Load showcase" is disabled. The 5 "recorded incidents" don't exist: candidates are 5 repeats of one crash clip plus 1 low-confidence fire | `scripts/` and `demo/` listings; CHANGELOG admits it | Pick 5 distinct verified clips; build DB and reset script | M |
| 6 | Medium | Cooldown (per camera+category, 120 s) skips dispatch plan and notifications entirely for the second incident, and consumes the slot even when `ALERTS_ENABLED=false` | timeline "dispatch skipped: cooldown", plan "pending or unavailable" in screenshot | Always build the plan; cooldown only outbound | S |
| 7 | Medium | Telegram allowlist is vacuous when `TELEGRAM_CHAT_ID_ALLOWLIST` is unset; LIMITATIONS says messages go only to the allowlist | safety test observation | Require an explicit allowlist or document | S |
| 8 | Medium | "Confirm" silently cancels the pending call | safety test | Decide intent; at least log or label | S |
| 9 | Medium | No auth, `CORS *`, binds `0.0.0.0`. Anyone on the LAN can POST `/demo/trigger` (which can notify when alerts are on), PATCH status, or DELETE legacy evidence | route list; `run_dashboard.py` | Bind localhost or gate demo and mutating routes | S |
| 10 | Medium | `stream_source:"0"` (string) never opens (`VideoCapture("0")` False, `0` True). `env:` unset var raises an uncaught `ValueError` that kills the worker thread | cv2 test; `/cameras/status` CAM-001 offline; code | Convert digits to int; catch and retry | S |
| 11 | Medium | Phone MJPEG ingest unverified. cv2 open blocks up to 30 s on a bad stream. Detection runs inside the read loop (read rate ≈ detect rate ≈ 3 fps), so real streams lag. No frame drop/grab | sim test and FPS table | Reader thread plus latest-frame, test with a real phone | M |
| 12 | Medium | Frontend pages Dashboard, LiveIncidents, Analytics and Evidence call v1 endpoints that are missing; SPA catch-all returns 200 for unknown API paths | curl: `/incidents/recent` 404, DELETE 405, analytics 200 | Return 404 for `/api/*`; hide or fix pages | M |
| 13 | Medium | Honesty labelling: sample and placeholder cameras are `real_installation`; LIMITATIONS claims otherwise. Offline-fallback label not visible in screenshot | cameras.json; `audit_08` | Set `simulated_placement`; add a label | S |
| 14 | Medium | Entire dispatch/notification/worker/docs layer is uncommitted | `git status` 32 entries | Commit | S |
| 15 | Medium | Memory: ~300 MB models plus ~360 MB (growing) per camera. 3 sample plus 3 phone cams plus the API is untested | FPS run | Soak test with target camera count | M |
| 16 | Medium | Running the unit tests spins up camera workers with real default paths (may write to real DB and evidence) | unittest console output; DB growth | Isolate tests with a temp DB and workers off | S |
| 17 | Low | `update_status` read-modify-write is not atomic against `append_notification`, so a notification record can be lost | code `incident_service_v2.py` | Use `mutate_incident_data` | S |
| 18 | Low | `/system/health` fabricated (loaded:true, uptime 0, wrong disk %) | code and response | Compute or remove | S |
| 19 | Low | Dead v1 code and `api_client` posting to a nonexistent route | grep; 405 | Delete | S |
| 20 | Low | Incident JSON leaks absolute server paths | API output | Store relative | S |
| 21 | Low | Docs mismatches: ARCHITECTURE "WebSocket push"; LIMITATIONS "DEMO_MODE=true is set in .env" (it isn't), "no autonomous action" (calls escalate automatically), "Recorded footage replay" badge claim for samples | read | Edit docs | S |
| 22 | Low | Unpinned requirements, 2 overlapping files, `yt_dlp` missing | import scan | Pin and merge | S |
| 23 | Low | Unverified claims in earlier summaries: encode-failure quarantine, SQLite 10-minute concurrency test, "5 strong candidates" (distinct), eval-vs-live FPS figures | not re-run | Re-run if needed | M |

---
## 6. DEMO READINESS
(See the end of the chat reply; same list.)

| Item | State |
|---|---|
| Backend and frontend start and render | ready |
| Map, dots, hover slideshow, detail panel, timeline, dispatch card | ready |
| 5 recorded incidents (distinct, verified) | **needs work** (don't exist) |
| Showcase DB and reset | **needs work** (not found) |
| Clean DB for the demo | **needs work** (real DB holds 310+ synthetic rows) |
| Demo trigger: crash | ready (fire needs fix, black frame) |
| 2–3 phone cameras over hotspot | **unknown** (never tested with a real phone; the MJPEG path is unverified) |
| `.env` loaded for SerpApi, Telegram, Omnidim | **needs work** (broken in API-only mode) |
| Telegram message, location, buttons | unknown (code and mocks pass; never sent) |
| Callback buttons (poller) | unknown |
| Call to demo number | unknown (never placed; `DEMO_PHONE_NUMBER` unset) |
| Safety rails (blocks, allowlist, cooldown, cap) | ready (25/25 mocked) |
| Mapbox road routes | unknown (never run; the straight-line fallback works) |
| SerpApi lookup | unknown |
| Offline fallback | ready, but unlabelled |
| WebSocket live push | needs work (the 2 s polling fallback works) |
| ffmpeg on the demo machine | ready here (present on PATH) |

**Most likely failure points:**
1. Env vars not loaded, so there is no dispatch plan, Telegram or call.
2. Phone stream won't open, or lags (single-thread detect+read).
3. The second incident on the same camera/category within 2 minutes gets no plan or alert.
4. The black fire frame.
5. Wrong or synthetic incidents on screen.
6. Machine CPU and memory with many cameras (about 1 fps each already with 3).

**Never tested end to end:** real Telegram send plus button callback; real Omnidim call; SerpApi; Mapbox Directions; a phone camera producing an incident; operator "False alarm" from a real Telegram button cancelling a real pending call; offline venue Wi-Fi.

---
## 7. OPEN QUESTIONS
1. Is PID 51188 yours, and should the real `incidents.db` be treated as disposable (archive or wipe) before the demo?
2. Which 5 incidents are the approved showcase set, and are fresh recordings planned?
3. Are the sample-video cameras meant to stay enabled in the demo, or only the phones?
4. Do you want `FIRE_CRASH_CONFIDENCE_FLOOR` raised (the eval harness used 0.5)?
5. Should "Confirm" cancel the call escalation?
6. Is the Telegram allowlist meant to be mandatory?
7. What is the phone streaming app/URL format (IP Webcam MJPEG or RTSP)?
8. Should Dashboard, Incidents and Analytics pages be fixed or hidden for the demo?
9. May I commit the uncommitted work to a branch?
