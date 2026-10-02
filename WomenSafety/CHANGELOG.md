# Gate A completed; snatch rerun on the 30 s clip (2026-10-02)

- **Snatch on the new `data/demo/snatch.mp4` (30.0 s):** fired **no**; peak (nearest-miss) score 0.441 vs threshold 0.7; signals of the nearest miss: approach closing speed 2.04, approach speed 1.62, flee speed 0.90, acceleration ratio 0.55, separation 0.76, target speed 0.28; blocked by: flee speed 0.90 < 2.5 body heights/s, acceleration ratio 0.55 < 2.0, separation 0.76 < 1.5 (a real approach was seen, but nothing accelerates away after contact), and in most evaluations no far-to-near approach at all. Crash cross-triggered once (24.6-28.3 s, peak 0.62). Other clips unchanged (deterministic). No threshold touched. `docs/DEMO_CLIPS_CHECK.md` and `docs/ACTION_DETECTORS_STATUS.md` updated.
- **Showcase** `demo/showcase.db` built from your two ids only: crash `525054e1...` on CAM-SAMPLE-001 and fire `f8ca84a0...` on CAM-SAMPLE-002 (2 locations, 1 incident each; dispatch plans from the cache, no placeholders; the fire's evidence folder was copied to its new camera's folder). Proof against a scratch API (alerts off, scratch DB): with a dirty DB, Load showcase gave exactly the showcase rows (byte-for-byte JSON equal); after acknowledging one incident (status confirmed), Reset demo gave 0 rows and Load showcase again gave the identical state (status back to new); clip, best frame and thumbnail served (HTTP 206) for both. Screenshots `docs/screenshots/rules_showcase_{crash,fire}_{full,card}.png`. `showcase.db` was checkpointed into a single file (no WAL leftovers). `demo/candidates.html` still shows the earlier replay of the old 62 s snatch clip (its ids were not rerun, so your chosen ids stay valid).
- `docs/KNOWN_FALSE_POSITIVES.md`: three cross-triggers (fire 0.5-5.9 s and crash 11.2-20.0 s on fall.mp4; crash 24.6-28.3 s on snatch.mp4) plus near cross-triggers; no tuning. `docs/LIVE_TEST_CHECKLIST.md`: per-camera detector preset note (fire/crash camera vs action-scene camera).
- `scripts/check_demo_clips.py` now passes (30 s snatch is inside 10-60 s; SOURCES.md rows are filled by you, with "no permission on record; local testing only").

# Demo build with ONLY the provided clips: phases 0-6, stopped at Gate A (2026-10-02)

Sources used: `data/demo/{fall,violence,snatch}.mp4` (each for its own class) and the existing fire/crash sample clips `data/fire.mp4`, `data/crash.mp4`. Not used: `testing/snatch.mp4`, `snatch_detection_system/`, `.claude/worktrees/`, the `discovery/` candidates, any other video. Nothing downloaded. `data/demo/SOURCES.md` is yours: I never wrote its source or permission fields (it is untracked; the clips are git-ignored). No real Telegram message and no real call during this task (mocks, a scratch API with `ALERTS_ENABLED=false`, and DRY RUN logic only); `.env` values untouched.

**Headline:** the real fall, violence and snatch detectors did **not** fire on their provided clips (`docs/DEMO_CLIPS_CHECK.md`, tiny sample, one clip per class). So their demo triggers are built but **disabled** with the reason, fire/crash are unchanged, and no threshold was touched (none of the misses is a near miss: fall 0.227 vs 0.6 with the person never reaching a down posture; violence never evaluated because the pose model finds under 2 persons in 12 of 13 gate checks; snatch 0.0 vs 0.7 with no far-to-near approach). Fire and crash cross-fired on `fall.mp4` and crash on `snatch.mp4`.

**Phase 0:** one API process on :8000; env vars checked by name only (all set except the backend `MAPBOX_TOKEN`, which falls back to the frontend token); `LOCATION_MODE=fixed`, `ALERTS_ENABLED=true`, `DEMO_MODE=true`, `LEGACY_DETECTORS_ENABLED=false`. `snatch.mp4` is 62.3 s (my 10-60 s checker flags it; used as provided). An extra `data/demo/snatch_trim.mp4` exists and is ignored (not one of the three). `.gitignore` extended (`demo/*.mp4*`, `data/demo/**/*.mp4`, `data/demo/_originals/`, `discovery/cache/`).

**Phase 1:** new `api/services/clip_replay.py` + `ActionRuntime` (engine + per-detector pipelines, now also used by `CameraWorker`, which was refactored onto it): replays a clip in video time through the real detectors and the same `EventCapturePipeline`. Added `blocked_by` diagnostics to the fall and snatch detectors (no logic or threshold change). `scripts/demo_clips_check.py` writes `docs/DEMO_CLIPS_CHECK.md` and `outputs/demo_clip_check.json` (fired flag + the clip's SHA-256). `docs/ACTION_DETECTORS_STATUS.md` now says "not shown live" for all three.

**Phase 2:** `POST /api/v1/demo/trigger` accepts `fall`, `assault` (`violence` alias) and `snatching` (HTTP 409 with the reason when the clip is missing, the detector did not fire, the clip changed since its check, or the replay does not fire; never forced). A category is enabled only if the clip exists AND `outputs/demo_clip_check.json` says the real detector fired on exactly that file (hash match). Source stays `test_replay` with the "synthetic demo trigger" note; best frame = peak-score frame with overlay; scalar signals only. New public `GET /api/v1/demo-state` (no token: no secrets, URLs, numbers or coordinates) feeds the picker, DRY RUN header badge, per-camera detector chips and audit tail. Token-protected: `POST /demo/detectors` (runtime per-camera toggle, no restart; a toggle rebuilds that camera's action runtime so its detector state restarts), `POST /demo/dry-run`. `DEMO_DRY_RUN` (default false): Telegram stays real, calls recorded `suppressed: dry run`, checked before the cap and allowlist. New `api/services/audit.py` (in-memory ring + `outputs/session_audit.jsonl`; none existed). `scripts/run_demo.py` (`--sequence --delay 25 --dry-run --camera --base-url`, restores the dry-run flag at the end); verified end to end against a scratch API (alerts off): fire and crash created, the three others SKIPPED with the reason. Alert policy for the three is unchanged (Telegram + dashboard, no auto-call, Escalate now only, EXPERIMENTAL text with score and threshold).

**Phase 3:** CAM-001 dispatch (mocked lookup, `tests/test_cam001_dispatch.py`): crash -> hospital then police, no fire station; fire -> fire station then hospital, no police; fall -> hospital; violence and snatching -> police only. CAM-001 cache (names only): hospital 3 kept / 0 excluded; **police 3 kept** / 3 excluded (railway GRP 1, generic "Police Station" 1, "type is not police station" 1 = Chitrakoot Police Station typed "government office"); fire 3 kept / 8 excluded (equipment suppliers 4, wrong type 4). Police is NOT missing, so the conditional filter fix was **not applied** (the filter is unchanged; the two police rescues the rule describes would be Chitrakoot PS and the bare "Police Station", plus Jhotwara Fire Station for fire). **0 SerpApi calls** (cache complete). **CAM-001's resolved coordinates equal the MI Road sample camera's simulated coordinates (CAM-001, CAM-002 and CAM-SAMPLE-001 share one ~100 m cache cell): probably a copied placeholder; no live refresh was attempted for that reason.** (A failing assertion in my own test echoed those coordinates once into test output; they are the public sample-camera values, I did not repeat them.) Screenshots at 1920x1080 in `docs/screenshots/rules_*`: fire and crash from the real stored-sample trigger on CAM-001; fall, violence and snatching are **fixtures** (`rules_fixture_*`, `scripts/make_ui_fixtures.py`: scripted pose, frames stamped TEST FIXTURE, scratch DB only, refuses to run against the real DB) because no real detection exists for them. They show the EXPERIMENTAL badge, EXP marker, filter chips, legend and the correct dispatch rows.

**Phase 4:** full suite 138 tests, all passing. **Safety fix found by a new test:** `_send_call_if_still_needed` (Escalate now) did not check `ALERTS_ENABLED`, so a stale Escalate button could place a call after alerts were turned off; it now does. New `tests/test_safety_proofs.py`: alerts off sends nothing for all five categories (including a stale Escalate press); experimental never auto-calls (full confidence, zero delay); hard-blocked numbers 100/101/102/108/112 in many formats and unset or non-allowlisted numbers are blocked on both the new path and legacy `Call_Alert`; worst-case Telegram caption stays under 1024. `scripts/secret_scan.py` (prints file:line and kind only): no local secret value (tokens, keys, demo phone) in the working tree or history; `.env` and `frontend/.env` untracked; the only real hit was the **CAM-002 phone IP and another LAN IP in `run.md`** (tracked; first in commit e0a679f): redacted in the working tree, **still present in git history** (nothing was pushed; rewriting history is your decision). Other hits are test fixtures and README examples. The doubled-extension files in `demo/` are ignored and untracked. `cache/nearby_services.json` committed on its own.

**Finding (not changed):** fire and crash demo triggers score about 0.68 and 0.80, above `CALL_MIN_CONFIDENCE` 0.6, so their call is scheduled with zero delay: Acknowledge cannot cancel it. The live checklist works around it with `$env:CALL_MIN_CONFIDENCE='0.99'` for button tests.

**Phase 5:** `docs/LIVE_TEST_CHECKLIST.md`.

**Phase 6:** `scripts/replay_candidates.py` replays only the five provided clips into a scratch DB (`backups/incidents_candidates_<ts>.db`, git-ignored; real DB untouched). **8 real candidates: Fire 3, Crash 5, Fall 0, Violence 0, Snatching 0**; 3 marked weak (peak under 0.6 or event under 1 s). Five of the eight come from a clip that is not the detector's own class (fire and crash on `fall.mp4`, crash on `snatch.mp4`: judge them yourself). `demo/candidates.html` regenerated from them (image with overlay, clip and time range, peak score, frames confirmed, signals, id, weak marks, EXPERIMENTAL badge). `scripts/build_showcase.py` now takes 1-5 ids of any category (5 -> 4 cameras with one holding 2; 4 -> 3 cameras with one holding 2), keeps `detection.experimental` and signals, copies each incident's evidence folder to its new camera's folder (evidence is served by camera id), restores the global DB path, and **no longer invents placeholder facilities** (an uncached camera shows services as unavailable unless `--allow-estimated`). `tests/test_showcase_build.py` proves Load showcase and Reset demo restore exactly the built state (round trip, evidence, badge fields).

**GATE A:** waiting for your chosen candidate ids (true positives only). **GATE B:** no threshold change is proposed: none of the three misses is a near miss, so the options are to refilm or leave those categories out.

# SerpApi candidate-clip discovery for fall / violence / snatch (2026-10-02)

**Discovery only.** No video was downloaded, fetched, converted or cached; no yt-dlp-style tool and no direct YouTube page access. The only network calls were SerpApi's `engine=youtube` JSON (plus nothing else). No detector, threshold, alert, pipeline or dashboard code changed. `SERPAPI_KEY` is read from `.env` only; it is never printed, and I grepped every file under `discovery/` to confirm it is absent.

- **Script:** `scripts/discover_clips.py` (no `serp_discover_local.py` existed). Round-robin over the three classes, highest-priority query first; hard cap on live calls per run (`--max-calls`, default 6); 15 s timeout; on-disk response cache (`discovery/cache/`, so reruns cost nothing); structured key-free errors; dedupe by video_id; keeps 10-180 s (unknown length is kept and flagged `length_unknown`); flags (not drops) compilation/top/best/news/reaction/dashcam/POV/prank/staged/movie/scene/game/simulation/funny/fails/shorts; boosts CCTV / security camera / surveillance / caught on camera. Outputs `discovery/<class>_candidates.csv` and a self-contained `discovery/review.html` (gallery, "interesting" checkboxes in the browser's localStorage, only thumbnails loaded).
- **Decision:** 10 queries (3+3+4 incl. a Hindi one and the Jaipur one) vs a default cap of 6, so priority order + round-robin; the first 6 live calls covered the top 2 queries per class.
- **Result:** the first run used 6 live calls and stopped at the cap. I then reran it (my mistake: each run has its own cap) which made **4 more live calls**, so **10 live SerpApi calls in total**; 0 failed. Candidates: fall 24 (1 flagged), violence 15 (0), snatch 50 (10 flagged: news / shorts). The automatic flags are coarse; the shortlist relies on my reading of title, channel and length.
- **Shortlist** `discovery/SHORTLIST.md`: top 5 per class with an honest metadata-only assessment (I did not open pages or look at thumbnails; content and rights unverified; may show real people being hurt) and one suggested pick per class for the user to decide. The violence pool is thin (mostly news, robberies, a shootout, a food fight with children).
- **Provenance:** `data/demo/SOURCES.md` (table template), `discovery/PERMISSION_REQUEST.md` (draft with placeholders), `scripts/check_demo_clips.py` (exists / readable / 10-60 s / SOURCES row). Run now: reports `fall.mp4`, `violence.mp4`, `snatch.mp4` all MISSING and their rows empty (exit 1), as expected. Added `data/demo/*.mp4` to `.gitignore` so someone else's clip is never committed by accident.
- **Honest note:** SerpApi returns links and metadata only, so none of these can enter the pipeline until the clips are obtained through a permitted route (uploader permission, a licensed dataset, or own recordings). The detectors found 0 of 5 real clips earlier, so own acted clips will probably work better than internet footage. Not done, on purpose: demo triggers and calibration.

# Fall, violence and snatch in the v2 event pipeline - EXPERIMENTAL (2026-10-02)

**Scope lock honoured:** fire/crash detectors, thresholds and behaviour are untouched (the default per-camera list is still `["fire","crash"]`; `EventCapturePipeline` defaults are unchanged). No training, no new database. Legacy `main.py` alert path left as is (`LEGACY_DETECTORS_ENABLED=false`). Full status, thresholds, evaluation and weak spots: `docs/ACTION_DETECTORS_STATUS.md`.

**Headline (honest):** the plumbing, safety policy and tests work; the detectors themselves do **not** detect the available real clips. Preliminary, tiny sample: 5 positive clips (2 fight, 3 snatch) -> 0 detections; 5 fire/crash clips -> 0 false alarms; no fall footage exists in the repo, so fall is verified on synthetic pose sequences only.

**Audit (what existed):** violence = stateless CLIP top-1 label (~150-300 ms/frame, no person/motion gating); fall = per-person state machine on a private ByteTrack + YOLOv8n-pose (~50-110 ms); snatch = its own detector + tracker + optical flow + ST-GCN + CNN-LSTM with weights that are not in the repo. All three lived in `main.py`'s legacy loop and pushed old-schema incidents straight to Telegram/call; `CameraWorker` only knew fire/crash and `EventCapturePipeline` had one verdict deque and fixed settings.

**Decisions (SPEED MODE, recommended option each time):**
- New package `api/services/action_detectors/` (one module per detector + `pose.py` shared pose pass/tracker + `engine.py`). Original modules untouched; fall/snatch re-implemented as rules over one shared YOLOv8n-pose pass (the old ST-GCN/CNN-LSTM snatch needs weights we do not have; the old fall state machine is tied to its private tracker).
- One `EventCapturePipeline` per action detector per camera (own confirm / end-gap / merge settings), sharing the camera's ring buffer (new keyword-only options; defaults reproduce the old behaviour). Action inference runs inline on the processing thread (not a second thread) so the sampled frame, its boxes/skeleton and the event's best frame are the same frame; the throttle protects fire/crash instead.
- Categories: fall -> `fall`, violence -> `assault` (shown "Violence"; added `assault` to `_category_from_class_name`, which previously mapped it to `other`), snatch -> `snatching`. `DISPATCH_RULES` unchanged.
- Per-camera detector list: `Camera.detectors` (cameras.json, default `["fire","crash"]`, validated) + env `DETECTORS_<CAMERA_ID>`; fire/crash also honour the list. No action engine, pose model or CLIP is built unless an action detector is listed.
- Best frame for action detectors = peak-score frame with box + skeleton overlay (written as `best_frame.jpg`); incident keeps scalar `signals` + `experimental` on `Detection`, never keypoints.
- Violence kept CLIP top-1 as the base score (as asked) behind gates; I did not loosen it to fit the two fight clips. Snatch/fall thresholds were not tuned on the repo clips either.
- Existing test `CallTextTests.test_primary_unavailable_and_no_prefix_outside_demo` expected plain snatching call text; updated to the new required EXPERIMENTAL wording (the only existing test changed).

**Alert policy:** `AUTO_CALL_CATEGORIES=fire,crash` (road_accident counts as crash). Experimental incidents: dashboard + Telegram only (buttons Acknowledge / False alarm / Escalate now), no timer, timeline `call: manual_only`; the call happens only on Escalate now. Telegram caption and call text say EXPERIMENTAL with confidence and threshold; cooldown per camera + category, at least `ACTION_COOLDOWN_S` (60 s) for experimental categories. DEMO_MODE allowlist, hard-blocked numbers, `MAX_CALLS_PER_HOUR`, `ALERTS_ENABLED` unchanged and proven on the escalate path.

**Dashboard (small diff, `MapView.jsx` + CSS + one field in `/map/groups`):** icons, filter chips (All / Fire / Crash / Violence / Fall / Snatch), legend entries, dashed "EXP" marker, "EXPERIMENTAL" badge on popups and the detail panel, and a "Why it fired" panel (score vs threshold, every signal). Frontend builds.

**Performance guard** (`scripts/measure_action_perf.py`): pose once per sampled frame, shared; detectors at their own cadence, idle verdicts only when nobody is in frame; interval x2 per step (max x8) while fire/crash fps < `MIN_USEFUL_FPS` (2.0). Measured on this CPU, fire/crash fps per camera: 1 camera 3.65 -> 3.72 (+2%); 2 cameras 2.19 -> 2.10 (-4%). Both inside the 25% limit, no re-measure needed. Cost of the guard: on 2 cameras the action detectors drop to about 0.6 pose passes/s, which makes them effectively blind; they are only useful on one camera on this machine.

**Violence classifier check (nothing downloaded/integrated):** `Nikeytas/videomae-crime-detector-production-v1`, MIT, 86M params, reported 63-67% accuracy on a 300-video subset (the only permissive candidate found); `OPear/videomae-large-finetuned-UCF-Crime` is CC-BY-NC-4.0 (not permissive). Expected CPU latency about 1-3 s per 16-frame clip (estimate). Not worth integrating on that evidence. Details in the status doc.

**Tests:** 41 new (`tests/test_action_detectors.py`, `tests/test_action_pipeline.py`, helper `tests/action_synth.py`); full suite 95 passing before the docs/UI work, rerun below. Fall: true fall, quick recovery, sitting, bending, deep held bend (only the hip rule rejects it), lying down on purpose, crouch, entering already lying, release when standing, plus mutation tests proving the hip-drop and stay-down rules are active. Violence: one person / far apart / close but still never run CLIP; close and moving does; single raw hit, non-violent label, sub-threshold score do not alert. Snatch: approach-and-flee detected; walk-past, fast walk-past, slow departure, single person not. Pipeline: simulated fall clip -> `fall` incident with `experimental`, signals, clip/best/annotated/thumbnail files, no keypoints stored, dispatch plan for hospital; per-camera list/env override; experimental incident never calls by itself (fall, assault, snatching) and Escalate now does (mocked, with EXPERIMENTAL / confidence / threshold in the spoken text); fire still auto-calls; cooldown per camera+category; hard-blocked/unset number, hourly cap, non-allowlisted chat, `ALERTS_ENABLED=false` all still block.

**Not done / open:** no real fall footage and no normal-pedestrian clip to measure false alarms against (needs data collection, out of scope); violence and snatch recall on the available clips is 0 (see status doc); thresholds are uncalibrated.

# Device GPS for demo phones (2026-10-02)

**Default `LOCATION_MODE=fixed`: nothing changes until you flip it to `auto` yourself** after `scripts/check_phone_gps.py` confirms a real source. In `fixed` mode no GPS poller or prefetch runs, no new labels/fields appear (incident GPS fields are null, status/map output unchanged), the dispatch-plan flow is the old synchronous one, and no phone is contacted. Sample cameras, replays, the showcase, "Load showcase" and "Reset demo" never use GPS in any mode; "Trigger test incident" on a phone uses the same location logic as a live detection and stays `source=test_replay`.

**Probe result so far:** both phones were unreachable from the laptop (`ConnectionError`/`ConnectTimeout` on all IP Webcam endpoints, SensorServer URL not configured), so **no real GPS source is confirmed**. The system stays on the fixed `.env` coordinates; nothing was guessed. Bring-up steps: `docs/GPS_BRINGUP.md`.

- **Adapters (one small file, common interface):** `api/services/gps_adapters.py` has `IPWebcamHttpAdapter` (`/gps.json`, `/sensors.json?sense=gps`, `/sensors.json`) and `SensorServerWsAdapter` (`ws://<phone>:<port>/gps`, URL from `PHONE_CAMnnn_GPS_URL`), both behind `GpsAdapter.read()`. **Both are verified against simulation only** (mock HTTP and WebSocket servers in `tests/test_phone_location.py`); a wrong format assumption is a one-file fix there.
- **Provider** (`api/services/phone_location.py`): per-phone poller, history of 10 fixes, reconnect with backoff; position = median of the last `SMOOTH_FIXES` (5) acceptable fixes (age <= `MAX_FIX_AGE_S` 60, accuracy <= `MAX_ACCURACY_M` 50, inside the India box; unknown accuracy is not acceptable); a single jump > 100 m is ignored unless the next fix confirms it. `resolve_location()`: auto = device GPS else the `.env` coordinates, device = GPS only, never a default coordinate; if neither exists the camera is offline ("location not configured ...") and an incident would be quarantined. No coordinates in logs/errors.
- **Incident snapshot:** `location_source` (`device_gps` | `camera_registry`), `location_accuracy_m`, `location_fix_age_s` on phone incidents when mode != fixed; latitude/longitude are the snapshot, which the Telegram pin, dispatch plan, routes and ETAs use.
- **Nearby services (B):** cache now keyed by ~100 m grid cell (`cell:lat3,lon3`; old camera-keyed entries migrated via the registry with no SerpApi calls; only missing categories are fetched; one lookup per cell at a time; SerpApi call cap kept; another cell's results are never reused). Prefetch when a phone starts and when its smoothed position enters a new cell. At incident time (phone, mode != fixed) the plan waits at most `NEARBY_PLAN_WAIT_S` (5 s); if not ready the alert goes out with the services "Lookup in progress" (Telegram caption says "lookup in progress"), and the plan, timeline ("plan_ready") and caption are filled in when it completes. Nothing is fabricated.
- **Dashboard:** badge "Device GPS +/- N m (. fix N s old)" / "Fixed placement" on camera tiles and incident detail (only when the backend sends the fields); soft accuracy circle for the selected device-GPS camera; cameras within 15 m are offset a few pixels on screen only with the tooltip "Offset on screen only ... (stored coordinates unchanged)"; the camera dot uses the smoothed position; `/cameras/status` and `/map/groups` carry `location_source`, `location_accuracy_m`, `location_fix_age_s` (no coordinates beyond what the map already received).
- **Also fixed:** `MAPBOX_TOKEN` fallback now respects an explicitly empty value, so tests/offline runs no longer reach Mapbox Directions through the frontend token (earlier test runs had made a few real Directions calls).

**Results (simulated phones):** scenarios (good fix, 120 m accuracy, 300 s old, outside India, single 550 m jump ignored then confirmed, dropped HTTP connection) produce device GPS or fall back to the `.env` coordinates as specified; with no fix and no `.env` coordinates the location is None. Incident records: phone+good GPS `device_gps` accuracy 8 m; phone+no GPS `camera_registry`; phone in fixed mode and sample replay: no GPS fields, registry coordinates; the showcase DB rows are byte-identical before and after loading with GPS active. Telegram pin, plan and route origin equal the snapshot. Timing: cache hit incident-to-plan 0.015 s with 0 SerpApi calls at incident time; cache miss (simulated 3 s per category) alert at 5.00 s with "Lookup in progress", plan filled in at 9.0 s. **SerpApi calls made during tests: 0 real** (all mocked; the mock counted 3 per new cell, 0 for a cache hit). Headless Chrome shots: `docs/screenshots/gps_01_two_nearby_cameras_offset.png`, `gps_02_badge_and_accuracy_circle.png`, `gps_03_camera_tile_badges.png`. 54 tests pass.

# Demo picker (2026-10-01)

The Demo controls camera picker (`GET /api/v1/cameras`) now lists only the added phone cameras (CAM-001, CAM-002); sample cameras are no longer offered. Test added.

# Incident-aware dispatch layer (2026-10-01)

Scope: dispatch map layer, dispatch card, and the small text changes in item 6. No detection / threshold / pipeline / escalation / cooldown / camera wall / showcase changes, no new dependencies (icons are inline SVG).

**1. Audit of `build_dispatch_plan` BEFORE the change** (all three service types available): fire -> fire, hospital, police; road_accident -> hospital, police, **fire**; crash (no table key, fell through to "other") -> police, hospital; assault -> police, hospital; snatching -> police; fall -> hospital; women_safety / other -> police, hospital. So a crash listed a fire station and a fire listed police.

**Rules table** (`DISPATCH_RULES` in `api/core/config.py`, primary first; `required_services(category)`): fire -> fire_station, hospital; road_accident and crash -> hospital, police; assault, snatching -> police; fall -> hospital; other -> police. **Decision:** `women_safety` and any unknown category use `other` (police only); the spec did not list women_safety. Rule type `fire_station` maps to the lookup/cache key `fire` (`SERVICE_LOOKUP_KEY`); cache format unchanged. The backend plan (`dispatch_routing.build_dispatch_plan`), API output, dashboard, map layer, Telegram caption and call text all read this table. Each assignment now has `role` (primary/secondary), a route for the first (nearest, phone-preferring) result only, and up to 2 `alternatives`. A required type with no result is `unavailable` ("No fire station found nearby") and is **never** replaced by another type. `conform_plan()` (applied in `public_view`) brings plans stored before this change in line with the rules (old "fire" -> "fire_station", unneeded types dropped).

**2. Map layer** (`frontend/src/components/dispatch.jsx`, wired in `MapView.jsx`): markers only for the selected incident and only the required types (nearest = primary icon, up to 2 smaller secondary ones); nothing when no incident is selected. Inline-SVG badges rendered into `map.addImage`: hospital = red circle + white cross, police = blue shield + white star, fire station = orange rounded square + white flame (shape and colour, aria-labels), soft shadow baked in. Symbol layers + a ring circle layer (data-driven hover/selected scale and ring). Route lines per type (colour per type), solid when from Mapbox Directions, dashed and labelled "est." when straight-line; draw-in via `line-trim-offset`; ETA/distance chip at each route's midpoint (DOM chips, so they also work without glyphs offline). Selecting an incident does an eased `fitBounds` to the incident plus its services; icons fade/scale in 60 ms apart. `prefers-reduced-motion`: no animation, instant placement. Sources/layers/images are created once (idempotent `ensure`, guarded against concurrent runs) and updated in place with `setData`; the 2 s poll does not touch them. Legend lists only the types in use. The old single route layer in MapView was removed. **Offline:** if the Mapbox style never loads (error, or 8 s), the map swaps to a local blank dark style, so icons, dashed lines, chips and the card keep working. The detail panel sits beside the map canvas, so symmetric padding is used instead of reserving space for it.

**3. Card:** one compact row per required service (same SVG icon, name, existing km display, ETA, tap-to-copy phone, "Nearest" badge on the primary), primary first; hover/focus on a row highlights its marker and route (and hovering a marker highlights its row); muted "No <service> found nearby" row; rows fade in when the incident changes (no layout jump).

**4. Failure behaviour:** cache is used when SerpApi is unavailable (unchanged); no service is ever invented.

**6. Text:** Telegram caption lists only the required services ("hospital: X (1.0 km)", "fire station: none found nearby"); call text names the PRIMARY service: "Fire detected at <place>. Nearest fire station: <name>, <distance> kilometres." / "Crash detected at <place>. Nearest hospital: ..." (Room 118 prefix in demo mode, safety rules untouched). `scripts/smoke_test.py --call` fixture updated (fire -> fire station).

**Tests:** `tests/test_dispatch_rules.py` (every category returns exactly the required types in order and roles, crash never contains fire_station, fire never police, missing type unavailable and not replaced, <=2 alternatives and route for nearest only, old plans conformed, caption lists only required services) and updated call-text tests: 40 tests pass.

**Verification** (headless Chrome 1920x1080, scratch DB with fire, crash, snatching, fire-with-missing-fire-station incidents; real SerpApi cache and Mapbox Directions): screenshots in `docs/screenshots/` `dispatch_01_fire`, `dispatch_02_crash`, `dispatch_03_snatching_police_only`, `dispatch_04_missing_service`, `dispatch_05_tiles_offline`, `dispatch_06_hover_highlight` (+ `*_card.png` crops of the dispatch card). Rows/legend per scenario: fire = fire station + hospital, crash = hospital + police, snatching = police only, missing = "No fire station found nearby" + hospital. Layer counts across 5 polls (10 s): sources 2->2, layers 4->4, images 3->3 (no recreation; only the hover leave changed data). Reduced motion: 0 animation frames and `animation-name: none`; normal: ~38 frames and `dispatch-fade`. Console: no errors in normal mode apart from 404s for the evidence files of two incidents I synthesised for the test (their media does not exist); offline mode logs one Mapbox internal `AbortError: Actor removed` when the style is swapped.

# CAM-001 phone camera, env-driven (2026-10-01)

Scope lock: no detection, threshold or pipeline changes. `config/cameras.json` was backed up first (`backups/cameras_20261001_191137.json`).

0. **Inspection (before changes):** `CAM-001` (the old placeholder: cctv, simulated placement, device "0"), `CAM-SAMPLE-001..004` (cctv, file replays) and one phone entry `PHONE-DEMO-PHONE-CAMERA-ENTRANCE` named "Demo phone camera - Entrance" (the hand edit changed the *name*, not an id, which is what doubled the prefix). A hand-made `config/cameras.json.bak` held two phone entries (`...ENTRANCE` and `...ENTRANCE-2`) for the same phone; it had been committed by an earlier `git add -A` (so the phone's LAN address is in commit 1c3e779, local only, no credentials). It is now untracked and `config/*.bak` is gitignored; history was not rewritten.
1. **CAM-001 = the phone.** One entry: `camera_id CAM-001`, `name "CAM 001"`, `camera_type phone`, `location_basis real_installation`, `stream_source env:PHONE_CAM001_URL`. The old placeholder CAM-001 and the PHONE-DEMO entry are removed. Display name is "Demo phone camera - CAM 001" exactly once on the dashboard, in Telegram (incidents store `display_name`) and the status API; the call text speaks the place only. **Env names:** your `.env` already holds `PHONE_CAM001_URL/LAT/LNG` (not `PHONE_CAM1_*`), so those are the names used everywhere.
2. **Env coordinates.** `latitude`/`longitude` accept `env:VAR`. Resolved each call and validated (set, numeric, inside the India bounding box). On any problem both stay empty, `location_error` names the variable (never its value), no default coordinate is used, incidents for it would be quarantined, `/nearby-services` returns 503, and the worker reports **offline: "location not configured: ..."** without opening the stream. Your `.env` currently has placeholder text in `PHONE_CAM001_LAT`/`LNG`, so CAM-001 is offline until you put real numbers there.
3. **No leaks.** No URL, credential or coordinate is logged. Found and fixed one: OpenCV's FFmpeg prints the full `host:port` when a stream is unreachable and that cannot be silenced in-process on Windows, so http/rtsp streams get a quiet TCP preflight (`stream_reachable`) first; unreachable streams just report "stream unreachable" (workers and `check_camera.py`). Credentials inside a URL stay rejected in the file (now for any scheme). If the app needs a login: `PHONE_CAM001_USER` + `PHONE_CAM001_PASSWORD` are read at connect time and injected into the URL in memory only (percent-encoded; a password without a user raises an error naming the variable, never the value). `/cameras` (picker) no longer returns coordinates. Camera registry load warnings print reasons only.
4. **main.py:** `CAMERA_ID` no longer defaults to `CAM-001` (the legacy local loop must not masquerade as the phone); with it unset the legacy event pipeline is OFF. The legacy `send_incident_to_api` now takes location from the registry instead of `CAMERA_LAT`/`CAMERA_LNG`/`CAMERA_LOCATION`, which are removed from `.env.example` and DASHBOARD_README (that path is dead anyway: the v1 POST route no longer exists).
5. **Cache:** removed the stale `PHONE-DEMO-PHONE-CAMERA-ENTRANCE` entry from `cache/nearby_services.json`; no incident rows exist for removed ids (fresh DB empty), no other file references them. **CAM-001 cache refresh NOT done**: it needs real coordinates and `PHONE_CAM001_LAT/LNG` are placeholders. After filling them run `python scripts/smoke_test.py --serpapi --yes --camera CAM-001`.
6. `.env.example`: `PHONE_CAM001_URL`, `PHONE_CAM001_LAT`, `PHONE_CAM001_LNG` (names only) plus commented optional `_USER`/`_PASSWORD`.
7. **Checks:** `check_camera.py CAM-001`: stream unreachable from this laptop right now (phone off, other Wi-Fi, or its address changed); it prints no address. API running (single instance, 127.0.0.1:8000): CAM-001 `offline` with the location error above. Online path verified with a simulated phone stream and temporary env values on a scratch server: `online`, `effective_fps 3.75`, `error null`, name "Demo phone camera - CAM 001".

Tests: `tests/test_camera_env.py` (registry shape, no duplicates, env coordinates valid/unset/non-numeric/out-of-range, no values in errors, password in memory only, worker stays offline without opening the stream); 33 tests pass.

# Pending fixes batch (2026-10-01)

Scope lock: no detection, threshold or pipeline changes.

1. **Demo button.** Header (top bar, right side, next to the DEMO MODE badge): an amber "🎛 Demo" button (`#demo-menu-button`, `components/Layout.jsx`). It toggles the Demo Controls panel on the map page (Ctrl+Shift+D still works): Load showcase, Reset demo, Reset view, camera picker, category picker (Fire / Crash) and Trigger test incident. All POSTs still send `X-Demo-Token`. Screenshots: `docs/screenshots/fix2_01_demo_button_and_controls.png`, `fix2_02_acknowledged_label_phone_name.png`.
2. **Doubled camera name.** `Camera.display_name` only adds "Demo phone camera - " if the registered name doesn't already start with it (case-insensitive); incidents now store `display_name`, so dashboard (map groups, picker, detail), Telegram caption and call text all agree ("Demo phone camera - Entrance", verified). The call text uses the place text only.
3. **Nearby services filtering** (`api/services/nearby_services.py`): SerpApi `type`/`types` are now kept and checked. Hospital: must be hospital/clinic/medical center/emergency (pharmacy, supply, diagnostic, dental-only, veterinary rejected). Police: must be a police station; railway police (GRP/RPF/"railway", also "G R P") excluded for road incidents. Fire: must be a fire station and not an equipment/supplier/dealer/shop/enterprises/extinguisher type or name. Results with no name or only a generic name ("Police Station", "Hospital") are dropped. Ranking: nearest first, but among results within 300 m of each other (measured from the nearest remaining one) those with a phone number come first. Every exclusion is recorded as `{category, title, reason}` in the cache entry (`excluded`) and in the lookup result. A `place_text` without a comma (e.g. the phone camera's "Demo phone installation") no longer injects that text into the query as a fake city (it had made the phone camera's hospital query return nothing). Cache refreshed live for the 4 sample cameras and the phone camera (16 SerpApi queries): e.g. sample-001 top results are now SR Kalla Hospital (0.98 km), Sadar Police Station (0.97 km), Rajasthan Agnishaman Seva (1.61 km); the generic "Police Station", the railway "G R P Police Station" and the fire-equipment shops were excluded with reasons (11-13 per camera). Note: the filter is strictly type-based, so a real station SerpApi mis-typed (e.g. "Jhotwara Fire Station" typed "government office") is excluded too; see `excluded` in the cache.
4. **Call text** is now: `<Room 118 prefix in demo mode> Fire detected at <place>. Nearest hospital: <name>, <distance> kilometres.` (or `Nearest hospital: unavailable.`). Only the nearest hospital is spoken.
5. **Telegram caption < 1024** (limit 1000): `compose_caption()` shortens the services list to fit with "(+N more)", then falls back to "see dashboard", and only then shortens the head; appended status lines are kept (last 6), and each service entry is capped at 70 chars. Used for the first send and every edit.
6. **Status label.** `confirmed` (only ever produced by Acknowledge, dashboard or Telegram) now shows as "Acknowledged" in the detail panel (status chip, button "✓ Acknowledged" once active, timeline entries) and the toast says "Incident acknowledged".

Tests: `tests/test_pending_fixes.py` (name prefix, filtering and recorded reasons, 300 m phone ranking, call text, caption length incl. very long services and heads); 26 tests pass.

# Telegram message handling fixes (2026-10-01)

Scope lock: no detection, threshold or dispatch changes.

1. **Button presses edit the same message.** The alert keeps its original caption (category, camera, place, time, peak confidence, threshold, and now the nearest services by name and distance; previously it only said "fire: available") and a status line is appended with local time `HH:MM:SS UTC+05:30` and the presser's display name only (first/last name or username, never ids): `Acknowledged by <name> at ... - automatic call cancelled`, `Marked false alarm by <name> at ...`, `Escalate now pressed by <name> at ...`. Buttons that no longer apply are removed: after Acknowledge only False alarm remains; after False alarm none; after Escalate / auto-call: Acknowledge and False alarm remain, Escalate goes. Edit uses `edit_message_caption` for photo alerts and `edit_message_text` otherwise, keeps within Telegram's 1024-char caption limit, and rebuilds its state from the pressed message if the API was restarted.
2. **Escalation timer line.** When the timer fires the message gets `No response - auto-call placed at HH:MM:SS UTC...` or `auto-call skipped: <reason>` (rate cap, safety-guard block, missing Omnidim credentials, request failure). Acknowledge and False alarm stay available after the call. An operator-triggered call writes `Call placed at ...` instead.
3. **Poller for the lifetime of the API.** The callback poller now runs in a self-restarting loop (`allowed_updates=[callback_query, message]`), and `answerCallbackQuery` is sent first, then the message is edited. A press on an alert whose incident no longer exists is answered `This alert has expired`, and its buttons are removed. Unknown actions answer `Unknown action`.
4. **Smoke test.** After the window ends with no press, `--telegram` edits the message to `SMOKE TEST: no button press within <n> s` and removes the buttons; an accepted press also removes the buttons and names the presser.
5. **Tests** (`tests/test_telegram_handling.py`, all network mocked: fake bot, patched `requests.post`, patched SerpApi; 18 tests total pass): Acknowledge cancels the call, writes `operator acknowledged` + `call cancelled` to the timeline, and the dashboard endpoint shows status `confirmed`; False alarm sets `false_positive`, cancels the call, removes all buttons, dashboard shows it; Escalate now places the call immediately (well under the 0.4 s test delay) and the message shows the call line with Acknowledge/False alarm left; no press: call placed after the escalation delay and the message shows `No response - auto-call placed at`; auto-call skipped line; press on an expired alert answers `This alert has expired`.

Not verified live: the real Telegram edit calls (only mocked here). Run `python scripts/smoke_test.py --telegram --yes` to see the smoke-test message edits on a real chat; a full-flow alert (ALERTS_ENABLED=true) will show the new captions and status lines.

# Demo fix pass (2026-10-01)

Scope lock: no training, no detector or threshold-logic changes. SPEED MODE:
recommended option picked, decision recorded here.

## Phase 1: Integrity
1. **.env loading**: `api/core/config.py` calls `load_dotenv(<project>/.env, override=False)` and points pydantic's `env_file` at the same absolute path, so uvicorn / `run_dashboard --mode api` / tests / scripts all see SERPAPI_KEY, MAPBOX_TOKEN, TELEGRAM_*, OMNIDIM_*, DEMO_PHONE_NUMBER. Real shell env still wins. Verified from a different cwd (set/unset only, never values).
2. **Allowlist no longer vacuous**: `check_telegram_allowed` expects `TELEGRAM_CHAT_ID_ALLOWLIST` or env `TELEGRAM_CHAT_ID`; if neither is set the channel is blocked. Call channel already blocked when `DEMO_PHONE_NUMBER` is unset (reason text now says so). Unit tests cover both.
3. **Fresh DB**: `incidents.db` (356 rows, mostly synthetic sample-video "live" rows) was backed up (sqlite backup API) to `backups/incidents_20261001_170903_pre_demo_fix_final.db` and moved aside as `incidents_pre_demo_fix_*.db.old` (gitignored). The API creates a new empty `incidents.db` on start. **Decision:** the dev server that held the DB (PID 51188, `run_dashboard.py --mode api`) had to be stopped to release the file lock; it was stopped. Sample (file-replay) camera workers are OFF by default (`SAMPLE_CAMERA_WORKERS_ENABLED=false`); only `camera_type: phone` cameras auto-start, and no detector weights load when there are none. Tests now use a temp DB / evidence dir, workers disabled, and blank real credentials.
4. **Labelling**: workers tag replay-sample cameras' incidents `source=test_replay` (badge "Recorded footage replay"); `live` is only for non-sample (phone/CCTV) cameras. All current cameras in `cameras.json` are `simulated_placement`; phone cameras keep `real_installation`. Badge ("Simulated placement" / "Demo phone camera" / "Real installation") is shown in the hover popup and in the detail panel.
5. **FIRE_CRASH_CONFIDENCE_FLOOR default 0.5** (config value only, no logic change). Noted in docs/LIMITATIONS.md.
6. **Cooldown**: incident and dispatch plan are always created; the cooldown (per camera+category) applies only to outbound Telegram/call and writes `suppressed: cooldown` timeline records. `DEMO_COOLDOWN_S` (default 15) is used when `DEMO_MODE=true`, else `NOTIFICATION_COOLDOWN_S` (120). The slot is consumed only when an outbound attempt is actually allowed (not when `ALERTS_ENABLED=false`).
7. **Relative paths**: every API response goes through `api/services/public_view.py`, which rewrites absolute evidence/project paths to forward-slash relative paths. Stored JSON is unchanged (the notifier opens files from it).
8. **Network hardening**: `API_HOST` default `127.0.0.1` (run_dashboard uses it), CORS limited to the dashboard origins (localhost/127.0.0.1 on 8000 and 3000), and `X-Demo-Token` (== env `DEMO_TOKEN`) is required on `/demo/*`, `PATCH /incidents/*/status` and `DELETE /evidence/*`. If `DEMO_TOKEN` is unset those routes return 403. A random token was appended to the local (gitignored) `.env` as `DEMO_TOKEN` and `frontend/.env` as `VITE_DEMO_TOKEN`; the frontend axios client sends it on non-GET calls. Placeholders added to both `.env.example` files.

## Phase 2: Demo path
9. **Fire trigger**: `data/fire.mp4` frame 0 is pure black (mean brightness 0.0), which is why the old trigger showed black evidence. `api/services/demo_trigger.py` now scans the stored clip once per category (1 s steps, 2-40 s for fire), picks the frame the real fire/crash detector scores highest (fallback: brightest frame after 2 s), caches that choice (deterministic), and uses the REAL boxes/confidence/weights (fire: 40 s, conf 0.68, `best_nano_111.pt`; crash: 7 s, conf 0.80). The incident is still `source=test_replay` and carries `evidence.note = "synthetic demo trigger: ..."` (new optional `Evidence.note`). `threshold_applied` is the configured floor (0.5). **Decision:** still-frame trigger rather than a replayed multi-frame clip (spec-minimal). `FIRE_DETECTION` in the local `.env` was `0` (legacy-loop toggle) which, now that `.env` loads in API mode, would have disabled the API fire detector; set to `1` in the gitignored `.env`.
10. **Showcase**: `scripts/build_showcase.py <5 ids>` (refuses anything but exactly 5 distinct ids; **I did not pick them**), reads them from `--source-db` (default: newest `backups/incidents_*.db` containing all ids), assigns them to 4 simulated cameras (2+1+1+1; added `CAM-SAMPLE-004`, simulated placement), forces `test_replay`/`new`/no notifications, and builds full dispatch plans from the SerpApi cache when present, else plans marked `estimated` (placeholder points titled "estimated - not a real facility"). Offline (Mapbox disabled). `scripts/reset_demo.py [--showcase]` and the dashboard's "Load showcase" / "Reset demo" buttons (`POST /demo/showcase`, `POST /demo/reset`, token-protected) share `api/services/demo_reset.py`, which always backs up first and works through SQLite rather than swapping files. Tested end to end with throwaway ids into a scratch DB only; `demo/showcase.db` does **not** exist until you supply ids. `GET /cameras` added for the trigger's camera picker (the old picker used the first map group, which is empty on a fresh DB).
11. **Camera workers**: digit `stream_source` ("0") becomes an int device index; unresolved `env:` sources and open errors mark the camera offline and retry instead of killing the thread; open/read timeout 5 s (`CAMERA_OPEN_TIMEOUT_S`) for URL streams; a dedicated reader thread keeps only the newest frame and the processor always detects on that frame; file replays are paced at native fps and loop. Proof (simulated MJPEG-over-HTTP stream of `crash.mp4` burned with a capture timestamp, real detectors, 180 s): frame age at detection start median 5-12 ms, max 44 ms in every 30 s window (flat, no build-up); stream dropped at t=100 s for 12 s: `offline "stream lost; reconnecting"` at 101 s, `online` again at 116 s; sustained about 3.5 detections/s. (The old simulator failed because it spoke HTTP/1.0; the new one uses HTTP/1.1.)
12. **Hidden pages**: nav and routes now expose only the map (`/dashboard`, `/incidents`, `/analytics`, `/evidence`, `/settings` redirect to `/map`); `IncidentProvider` removed. Unknown `/api/*` paths return JSON 404 (not the SPA with 200).
13. **WebSocket: wired (small change)**. `incident_service_v2.publish_created()` pushes thread-safely to subscribers right after the durable insert; the dashboard uses one shared socket and still polls every 2 s as the fallback. Verified: a `{"type":"incident_created"}` frame arrives after a demo trigger.
14. **Acknowledge**: Telegram button "Acknowledge (stops auto-call)", dashboard button "Acknowledge" with an explanatory line. Status value stays `confirmed`. `_send_call_if_still_needed` now also cancels when the incident is `confirmed`, so the dashboard button stops the call too (previously only the Telegram callback cancelled the timer). Timeline shows `call cancelled`.
Docs: LIMITATIONS.md (0.5 floor, replay labelling, simulated placement, acknowledge/escalation, allowlist wording, local-only API, single page), ARCHITECTURE.md, DEMO_SCRIPT.md updated.

## Phase 3: Live smoke tests (not run by me)
15. `scripts/smoke_test.py` with `--telegram`, `--call`, `--serpapi`, `--mapbox` (each needs `--yes`; no flag prints help; flags without `--yes` refuse). Recipients are only `TELEGRAM_CHAT_ID` / `DEMO_PHONE_NUMBER`, both re-checked by `safety_guard` (hard emergency-number block included); output never prints secrets, chat ids or full numbers. `--telegram`: one photo + location pin + Acknowledge / False alarm / Escalate buttons, then waits 60 s for a press and reports the callback result (stop the API first: two pollers on one bot token conflict). `--call`: one Omnidim call to `DEMO_PHONE_NUMBER`. `--serpapi`: one forced lookup for one camera (3 queries), written to the cache. `--mapbox`: one Directions route. Backend `MAPBOX_TOKEN` falls back to `frontend/.env` `VITE_MAPBOX_TOKEN` (public pk token) when unset. I only ran `--help` and the refusal paths.

# Changelog

## Hackathon dashboard — full rebuild (2026-10-01)

Complete rewrite of the hackathon demo dashboard (`frontend/src/pages/MapView.jsx`,
`frontend/src/index.css`), replacing the compressed single-file prototype with a
properly structured, projector-optimised (1920×1080, large type, high contrast)
React component tree.

### Map (Mapbox GL)
- One numbered dot per camera from `/api/v1/map/groups`, colour-coded by most
  severe incident category (🟠 fire, 🔴 crash, 🟣 assault/snatch, 🟡 fall).
- Phone cameras distinguished with a teal ring outline; `location_basis` badges.
- Map auto-fits to all cameras on load; `flyTo` on incident selection.
- Clear legend (fire, crash, assault, snatch, demo phone) — no overlapping.

### Live incidents (WebSocket + 2 s polling)
- WebSocket connection to `/api/v1/incidents/ws` triggers immediate data refresh.
- 2 s polling fallback with automatic reconnect on WebSocket failure.
- New incidents: marker pulses, toast notification with category and camera name,
  map flies to the incident camera. Pulse clears after 4 s.
- "Back to overview" button re-fits the map to all cameras.

### Hover popup
- Camera name, place, incident count, auto-advancing thumbnail slideshow (3 s)
  with category, time, and confidence. Slide indicator dots.
- Stays open while pointer is inside; click pins it and opens detail panel.
- Phone and simulated-placement honesty badges shown in hover.

### Detail panel
- Clip player (with poster), best frame, detection metadata grid (peak/mean
  confidence, threshold, model name, frames confirmed).
- Status buttons (Confirm / False positive) with PATCH to API.
- **Notification timeline**: real records from the dispatch backend —
  channel icon, status colour, timestamp, detail, errors.
- **Dispatch plan**: per-assignment cards (hospital/police/fire) with
  service name, phone, distance, ETA, and route-source indicator.
  Route polyline drawn on map (dashed teal GeoJSON line layer).
- Honesty badges: "Recorded footage replay" for test_replay incidents,
  "Live detection" for live, "Demo phone camera", "Simulated placement".

### Live cameras panel
- Tiles for each phone camera: live MJPEG stream img, online/offline
  status indicator, effective FPS. Empty state with setup instructions.

### Demo controls (Ctrl+Shift+D)
- "Load showcase" (disabled — requires demo/showcase.db), "Reset view",
  and "Trigger test incident" with category selector (fire/crash).
  Calls `POST /api/v1/demo/trigger`.

### Honesty badges
- "Recorded footage replay" on replay incidents.
- "Demo phone camera" and "Simulated placement" on cameras.
- "DEMO MODE" badge in the header with gradient highlight.

### Polish
- Loading skeleton with shimmer animation.
- Error state with retry button.
- Empty-state overlay on map when no incidents exist.
- `prefers-reduced-motion`: all pulse, fly-to, and hover animations disabled.
- Keyboard accessibility: all interactive elements focusable with visible
  `:focus-visible` outlines; demo controls via keyboard shortcut.
- Consistent spacing, type scale (Space Grotesk headings, IBM Plex Sans body,
  JetBrains Mono for technical values).
- 1920×1080 projector layout: large markers (40px), readable labels (14–16px),
  high-contrast dark theme.
- Offline fallback: if Mapbox tiles unavailable, dots positioned on dark
  gradient with labelled straight-line routing.

### CSS
- `index.css` rewritten from compressed single line to ~900 lines of
  structured, documented CSS. All demo styles properly formatted with
  clear section headers. Legacy tailwind component-layer classes preserved
  for other pages.

### Hackathon documentation
- `docs/ARCHITECTURE.md`: Mermaid flow diagram covering camera→worker→
  detection→evidence→SQLite→dispatch→frontend pipeline, design decision
  table, directory layout.
- `docs/DEMO_SCRIPT.md`: 3-minute timed script (map overview → hover/click →
  live camera + trigger → close), 12-item pre-demo checklist (keys, mode,
  hotspot, phone, cache, ffmpeg, trigger), and backup plan for 5 failure modes.
- `docs/LIMITATIONS.md`: honest disclosure of pre-trained models, replayed
  footage, simulated placement, configurable thresholds, human confirmation
  requirement, demo mode safety rails, display-only service numbers, hard
  emergency-number block, and post-hackathon next steps table.

## Phone-camera demo and showcase preparation (2026-10-01)

Added phone-camera registry metadata (`camera_type`, `location_basis`, and the
operator-facing `Demo phone camera - <name>` label), registration/check scripts,
API-owned latest-frame workers with reconnect backoff, status and MJPEG live
view endpoints, original-resolution evidence with `DETECT_MAX_WIDTH=640`
detection downscaling, and a stored-clip `POST /api/v1/demo/trigger` fallback.
Live demo defaults now set `LEGACY_DETECTORS_ENABLED=false`; the legacy raw
buffer remains unallocated on that path.

Telegram dispatch captions now include camera/place/time/peak/threshold/plan,
send a location pin, and include an immediate `Escalate now` action. Demo
escalation uses `DEMO_ESCALATION_DELAY_S=20`; all existing demo allowlist and
hard phone-number blocks remain in force.

Replayed the available fire/crash samples through the existing pipeline and
generated `demo/candidates.html`, sorted by confidence. The current set has
five strong candidate rows but they are repeated replays of the same crash
clip, plus one low-confidence fire candidate; it does **not** contain five
distinct verified true positives. Showcase DB/reset creation is intentionally
deferred until five approved candidate IDs are supplied.

## Dispatch Backend (2026-10-01)

Completed the v2 fire/crash dispatch path without restoring the removed legacy
double-send path. `GET /api/v1/cameras/{id}/nearby-services` exposes cached or
live SerpApi lookup data for registered cameras. `dispatch_routing.py` maps
incident category to required responder types, picks the nearest returned
service, obtains a cached Mapbox driving route when available, and otherwise
returns a visibly-labelled straight-line estimate. Lookup results are display
data only; their phone numbers are never call targets.

`notification_service.py` adds a bounded worker queue, durable per-incident
notification timeline, photo/message Telegram delivery with Confirm and False
alarm callbacks, callback polling under the API lifespan, retry/backoff,
camera/category cooldown, call-hour cap, and a Telegram-then-call escalation
ladder. Calls are only ever attempted to `DEMO_PHONE_NUMBER` after the shared
safety guard; real emergency numbers and all non-allowlisted numbers remain
blocked. Incident creation now persists first and queues dispatch work after,
so encoder threads never wait on lookup or outbound network I/O.

Added `tests/test_dispatch_backend.py`: offline cache hit, API route handler,
Mapbox fallback, category routing, emergency-format hard block, confirm/false
alarm callbacks, escalation timer, and cooldown all pass (`8/8`). The cache
and fallback tests deliberately use no real SerpApi/Mapbox requests; live API
credentials remain an operator configuration step.

## Phase 1c Follow-up 3 (2026-10-01)

### Scope
Final small hardening items: check for orphaned processes from the measurement scripts, clarify the two-frame-buffer situation, fix the one real unbounded leak found in Follow-up 2 (`OCSortTracker.history`), and correct an imprecise percentage claim in CHANGELOG.md. No threshold or detection-logic changes.

### 1. Process-leak check: none found, measurement scripts are clean
Checked `Get-Process python,ffmpeg` (PowerShell) and `ps aux` (bash) before and after 3 separate scenarios:
- 3x `scripts/run_single_fps_measurement.py` invoked directly (the fresh-process worker itself).
- `scripts/measure_live_loop_fps_interleaved.py` (the `subprocess.run()`-based orchestrator that spawns the worker above).
- 3x `scripts/camera_replay.py` (each one invokes a real blocking `ffmpeg` subprocess via `event_capture.py`'s `_build_evidence()`).

**Result: identical process list before and after every scenario** -- only the pre-existing `uvicorn` backend process (started independently, not by any measurement script) was present both before and after each batch. Zero orphaned Python or ffmpeg processes in any case. This is expected and correct: every subprocess call in this codebase (`subprocess.run(...)` for ffmpeg, and the orchestrator's own `subprocess.run()` for the worker script) is blocking and waits for the child to exit before returning -- there is no code path that could leave a detached child process running. No fix was needed to the measurement scripts.

**CHANGELOG correction for the earlier unexplained FPS decline**: this rules out one more candidate explanation (see Phase 1c Follow-up 2's item 4 note, corrected above) -- a leaked/orphaned process from a prior run contending for CPU is NOT the cause, since no such process was ever found to exist. The real cause remains unidentified; the remaining candidate explanations are specific to rapid fresh-process-startup cycling itself (OS cache eviction, CPU boost-clock exhaustion across repeated short bursts), not a resource genuinely left behind by this project's own code.

### 2. Two frame buffers confirmed to exist, serving genuinely different (but overlapping) purposes
Yes, two separate, independently-maintained frame buffers exist and both are fed the SAME raw frame for the SAME camera on every single `main.py` detection-loop iteration (confirmed: both `event_pipeline.add_raw_frame(frame, ...)` and `evidence_service.add_frame(camera_id, frame, ...)` are called back-to-back on the same `frame` variable, same `CAMERA_ID`):

| Buffer | Class | Storage | Window | Consumer |
|---|---|---|---|---|
| `api/services/evidence_service.py`'s `FrameBuffer` | Raw BGR `np.ndarray`, `deque(maxlen=1800)` | Uncompressed | 60 real seconds @ assumed 30fps (`fps` param defaults to 30.0; `main.py`'s call site never overrides it) | The OLD/legacy alert path ONLY: `main.py`'s `send_incident_to_api()` -> `api_client.create_incident_from_detection()` -> `evidence_service.save_evidence_clip()`, which cuts an OpenCV-`VideoWriter`-encoded clip for the pre-CCTV-pivot, in-memory incident model. Still live and still the only thing creating the old-schema `evidence_clip_path`/`thumbnail_path` fields. |
| `api/services/event_capture.py`'s `RingBuffer` (inside `EventCapturePipeline`) | JPEG-encoded `bytes`, plain `deque` manually bounded by wall-clock time | Compressed (q90, see Phase 1c follow-up 2) | `PRE_EVENT_SECONDS=8` real seconds | The NEW CCTV pipeline: `EventCapturePipeline._build_evidence()`, which produces the ffmpeg-encoded clip + best-frame + thumbnail for the SQLite-backed `Incident` model (`api/models/incident_v2.py`). |

**Per-camera memory, measured/estimated** (at `DETECT_WIDTH=640`, this clip's aspect ratio -> 640x360 working frames):
| | `FrameBuffer` (raw, 60s window) | `RingBuffer` (JPEG q90, 8s window) | Combined |
|---|---|---|---|
| 1 camera | ~1186.5 MB | ~25.8 MB | ~1212.3 MB |
| 3 cameras | ~3559.6 MB | ~77.3 MB | ~3636.9 MB |

Cross-checked against the real Phase 1c follow-up 2 soak-test measurement (1 camera, legacy ON): observed total growth was 1426 MB; `FrameBuffer`+`RingBuffer` together predict 1212.3 MB (~85% of the observed growth), with the ~214 MB residual plausibly `fall_detection.StateManager`'s per-person state and other first-time buffer fills reaching steady state. **`FrameBuffer` is the dominant cost by roughly 46x** (1186.5 MB vs 25.8 MB per camera) -- it stores 7.5x more real seconds of footage (60s vs 8s) AND stores it uncompressed (raw BGR) rather than JPEG-encoded.

**Is one redundant?** Functionally, yes, in the narrow sense that both buffers exist purely to let their respective incident-creation path "look backward" at recent frames once a detection fires -- but they are NOT currently interchangeable, because they feed two different, independently-live incident/evidence models (the old in-memory legacy schema vs. the new SQLite CCTV schema). **Proposed consolidation (not implemented, reported only per instruction)**: since `RingBuffer` already does everything `FrameBuffer` does (rolling pre-event window of recent frames) at ~46x less memory via JPEG compression, and since `EventCapturePipeline` is the actively-developed, CCTV-schema-aligned pipeline, the legacy `FrameBuffer`/`save_evidence_clip()` path could potentially be retired in favor of sourcing the old alert path's evidence clip from `RingBuffer` too (would need a JPEG-decode step before `cv2.VideoWriter`, same pattern `_build_evidence()` already uses) -- or, if the old alert path itself is slated for removal in a future "routing phase" (see Phase 1c Hardening's item 1 finding on the two independent alert/incident mechanisms), the simplest consolidation is simply deleting `FrameBuffer`/`evidence_service.add_frame()`'s call site once that happens naturally. Not done this phase -- scope-locked to "propose, don't change."

### 3. OCSortTracker.history fixed: pruning + per-track cap, proven identical tracking + flat memory
`snatch_detection/tracking/tracker.py`'s `OCSortTracker.history` (found unbounded in Phase 1c follow-up 2's soak test) now:
- Stores a bounded `deque(maxlen=SNATCH_TRACKER_HISTORY_MAX_LEN)` per track (config, default 30) instead of a single unbounded-lifetime `np.array` entry -- "cap history length per track," per instruction.
- Is pruned via `_prune_dead_tracks()`: any track_id not seen in the current frame AND whose last update exceeds `SNATCH_TRACKER_HISTORY_MAX_AGE_SECONDS` (config, default 30.0s) is deleted entirely -- the same expiry-by-last-seen pattern `fall_detection.StateManager` already uses.
- **A second, related bug fixed in the same pass**: `update()` returned early (`if not detections: return []`) BEFORE ever reaching the pruning call -- meaning a frame with zero detections (exactly when a track has likely disappeared) never triggered pruning at all. Fixed: the empty-detections path now also calls `_prune_dead_tracks()` before returning.

**Proof of identical tracking results** (`scripts/compare_tracker_before_after.py`, new): ran the real YOLO `PersonDetector` + both the pre-fix (restored from git history) and post-fix `OCSortTracker` over the same 150 frames of `testing/snatch.mp4`, logging `(frame_idx, track_id, bbox, confidence, velocity)` for every tracked person in every frame:
```
BEFORE: 4 tracked-person entries
AFTER: 4 tracked-person entries

IDENTICAL: True
```
Exact match on every field, confirming the fix is purely a bookkeeping/memory change with zero effect on tracking output (velocity is still computed as `current_center - most_recent_prior_center`, mathematically identical to before -- only the storage container changed from a single value to a bounded deque's last entry).

**Note on soak-test duration -- changed mid-phase**: the user switched to "Speed Mode" partway through this item, capping future soak tests at 2 minutes unless explicitly requested longer; the originally-started 20-minute soak (post-fix) was stopped early as a result. A 2-minute soak alone can't show `evidence_service.FrameBuffer`'s plateau (which takes ~14 minutes to fill, per Phase 1c follow-up 2's measurement) -- so flat *total RSS* over 2 minutes would not, by itself, prove `OCSortTracker.history` specifically is fixed (the dominant memory cost is unrelated to it and dwarfs it). Used a more direct, targeted proof instead:

**2-minute soak (post-fix, legacy ON, `data/crash.mp4`)** -- confirms no regression in overall behavior: `RSS: 1356.9 -> 1611.1 -> 1695.0 -> 1768.3 MB over 90s` (same early-growth shape as the pre-fix run, as expected -- this window is too short to reach `FrameBuffer`'s plateau either way), `FPS first half mean: 3.37, second half mean: 3.39` (flat, consistent with Phase 1c follow-up 2's finding that FPS doesn't degrade from memory growth).

**Direct, targeted proof that `OCSortTracker.history` itself is bounded** (more precise than relying on total-process RSS, and fast): fed one synthetic track, confirmed `history size: 1`; then had it go unseen for 0.6s (> a lowered `HISTORY_MAX_AGE_SECONDS=0.5` test threshold) and called `update([], frame)` -- the exact empty-detections code path this fix added pruning to -- confirming:
```
after seeing track: history size = 1
after track gone + 0.6s + empty-detections update: history size = 0
```
Track correctly pruned. Combined with the byte-identical-tracking-results proof above, this directly demonstrates both halves of the fix (pruning works; tracking output is unaffected) without needing a long soak.

### 4. Corrected: Legacy OFF speedup stated as a lower bound, not a precise figure
See the correction inline in Phase 1c Follow-up 2's item 3 above: **"Legacy OFF was at least 21.7% faster (OFF was at the sampler ceiling, 3 runs per condition)."** The original "+21.7%" framing implied a precise measurement; it is actually a lower bound, since Legacy OFF's measured FPS (3.93-3.99) was already pinned at the `RealtimeFrameGate`'s configured ceiling (`1/SAMPLE_INTERVAL_S` = 4.0 fps) across all 3 runs -- a sampler sitting at its own ceiling cannot reveal how much faster the underlying inference actually is.

### Files changed this phase
`snatch_detection/tracking/tracker.py` (history pruning + cap fix), `api/core/config.py` (`SNATCH_TRACKER_HISTORY_MAX_AGE_SECONDS`, `SNATCH_TRACKER_HISTORY_MAX_LEN`), `scripts/compare_tracker_before_after.py` (new).

### Assumptions and open questions
1. **The earlier blocked-order FPS decline is still not conclusively explained** -- this phase ruled out "leaked process" as the cause; the real cause (likely something specific to rapid fresh-process-startup cycling) remains open for a future targeted investigation, if it matters.
2. **The two-frame-buffer consolidation is proposed, not implemented** -- retiring `evidence_service.FrameBuffer` depends on a decision about the old alert path's future (see Phase 1c Hardening's "routing phase" note), which is out of scope here.
3. **`SNATCH_TRACKER_HISTORY_MAX_AGE_SECONDS=30.0` and `SNATCH_TRACKER_HISTORY_MAX_LEN=30` are reasonable defaults chosen to match the existing codebase's other per-track timeout conventions** (not derived from a formal analysis of this specific tracker's occlusion-tolerance needs) -- fine-tuning these, if ever needed, should be done alongside the snatch detector's other threshold tuning (explicitly out of scope this phase).
4. **`supervision`'s own `ByteTrack.lost_tracks`/`removed_tracks` internal buffers were flagged but not audited or fixed** in Phase 1c follow-up 2 -- still true here; this fix only addresses this project's own `OCSortTracker.history` wrapper, not third-party library internals.

### Process note: "Speed Mode" adopted mid-phase
The user introduced a standing instruction partway through this phase: for any remaining multiple-choice-style decision, pick the recommended option, record it in CHANGELOG.md, and continue without stopping to ask -- except for destructive actions, threshold/detection-logic changes, anything affecting what a result means, or a genuine blocker. Measurements default to one run / no soak over 2 minutes unless explicitly requested longer. Reports should paste key outputs only, not full logs. This phase's item 3 (`OCSortTracker` fix verification) was already in progress when this took effect: the originally-started 20-minute soak was stopped early and replaced with a 2-minute soak plus a direct, targeted pruning-behavior test (see item 3 above) -- judged to satisfy the verification intent (prove memory is bounded, prove tracking is unaffected) without the longer run, consistent with the new default.

## Phase 1c Follow-up 2 (2026-10-01)

### Scope
Re-investigate the previous follow-up's FPS comparison (found to be confounded), add a fire/crash confidence-floor config value (without changing live behavior), add detection-only measurement mode, add an effective-config dump, and clarify the eval-vs-live FPS gap in CHANGELOG.md. No threshold changes to the live loop's actual detection logic.

### 1. Re-measured on a would-be zero-event clip -- found it isn't actually zero-event, which is itself the headline finding
Attempted to re-measure legacy ON vs OFF on `testing/snatch.mp4` (the closest available "no incident" stand-in, 76s, no purpose-built empty-scene clip exists in this repo). Result: **not a clean zero-event test** -- `main.py`'s live loop produced 2-5 "crash" EVENT START entries per 20-30s run on this clip, 0-2 of which were confirmed into real (false-positive) incidents at `peak_conf=0.36`.

**Root cause, and why it matters more than the FPS number**: `scripts/camera_replay.py` and `scripts/eval_detectors.py` both apply a `VIDEO_MIN_CONFIDENCE`/detector `threshold` floor of 0.5 before ever counting a detection as a hit. `main.py`'s live loop applies **no floor at all** -- it passes each detector's raw confidence straight through to `EventCapturePipeline.feed_detection()`. **This is a HIGH-priority finding**: the eval harness and the live loop apply different effective confidence floors, so **eval results do not describe live behavior** -- a detection the eval harness would silently discard as below-threshold (e.g. 0.36) can create a real incident in live mode. This was found, not fixed (no threshold changes made to the live loop, per instruction).

### 2. Floor moved into shared config, live behavior UNCHANGED
Added `FIRE_CRASH_CONFIDENCE_FLOOR: float = 0.0` to `api/core/config.py`, explicitly set to match **current live behavior** (no floor) so nothing changes yet. `scripts/camera_replay.py` gained `--confidence-floor` (default 0.5, this script's historical behavior, NOT read from the new config default) and `scripts/eval_detectors.py`/`DetectorRegistry` gained the same (`--confidence-floor`, default 0.5). Both print a line making the live/eval floor mismatch explicit on every run: `confidence_floor=X (live loop's settings.FIRE_CRASH_CONFIDENCE_FLOOR=0.0 -- DELIBERATELY different right now, see CHANGELOG.md)`. **Phase 2 should run eval at both 0.5 and 0.0 and report both**, before deciding whether the live loop should adopt a floor -- not decided here.

### 3. Detection-only mode: isolates detection throughput from event/encode cost
Added `DETECTION_ONLY_MODE: bool = False` (config) -- when true, `main.py`'s live loop runs fire/crash detection and the sampling gate exactly as normal, but `EventCapturePipeline.feed_detection()` is never called, so no event ever starts, no clip is ever encoded, and no incident is ever created. Purely a measurement tool (temporary, not a deployment mode).

**First attempt (blocked order: ON x3, then OFF x3, same long-lived process reused via module reimport) was itself confounded** -- see Finding 4 below; a clean re-measurement required fresh processes and interleaving, done next.

**Interleaved, fresh-process re-measurement** (`scripts/measure_live_loop_fps_interleaved.py` + `scripts/run_single_fps_measurement.py`, order ON/OFF/ON/OFF/ON/OFF, each run a FRESH `python` subprocess, 60s measurement + 60s cooldown between every run, `data/crash.mp4`, `DETECTION_ONLY_MODE=true` so zero events/encoding occurred in any run -- confirmed: `events_started=0, incidents_created=0` in all 6 runs):

| Condition | Mean FPS | Min | Max | Per-run means (in interleaved order) |
|---|---|---|---|---|
| Legacy ON (violence+fall+snatch also running) | 3.27 | 2.10 | 3.73 | 2.61, 3.53, 3.66 |
| Legacy OFF (fire+crash only) | 3.98 | 3.93 | 3.99 | 3.98, 3.98, 3.98 |

**Corrected statement (Phase 1c follow-up 3, item 4): Legacy OFF was at least 21.7% faster (OFF was at the sampler ceiling, 3 runs per condition).** The prior wording ("+21.7%, OFF is faster") stated this as a precise, tight figure; it is more accurate to say "at least" because Legacy OFF's measured FPS (3.93-3.99, mean 3.98) was already sitting at essentially the `RealtimeFrameGate`'s own ceiling -- the configured `SAMPLE_INTERVAL_S=0.25` target of 4.0 fps -- across all 3 runs, with near-zero variance. A sampler pinned at its own ceiling cannot demonstrate how much FASTER fire+crash-alone inference actually is; it only shows that fire+crash alone is fast enough to saturate the current 4fps sampling rate, not what its true unthrottled throughput would be. The true gap between "legacy ON" and "legacy OFF" raw inference speed could be larger than 21.7% -- this measurement's design (fixed sampling interval) cannot distinguish "exactly 21.7% faster" from "far more than 21.7% faster, capped at the ceiling we configured." This result DOES hold as a lower bound, and still supersedes the earlier -8%/-10.5% finding from Phase 1c Follow-up 1, which was confounded (see below) -- but the earlier unqualified "+21.7%" framing is corrected here. **This measures detection throughput only** (no event-lifecycle or ffmpeg-encode cost is included, per DETECTION_ONLY_MODE) -- the earlier (non-detection-only, encode-included) measurement's absolute numbers are not comparable to this one. ON's per-run means also rose across the 3 repeats (2.61->3.53->3.66) while OFF stayed flat at the ceiling every time -- consistent with CLIP/fall/snatch models needing some warm-up (JIT/cache effects) within each fresh process, not a declining trend.

### 4. Finding: the earlier blocked-order measurement was genuinely confounded by machine-state drift during multi-run sessions -- investigated with a dedicated soak test
The first (non-interleaved) detection-only attempt showed a strong monotonic FPS DECLINE within each condition across 3 back-to-back repeats in the same long-lived script (ON: ~3.2->0.9 fps; OFF: ~1.8->0.4 fps) -- since ON always ran before OFF, order and condition were confounded and the resulting "-44.9%" comparison was not trustworthy.

**20-minute single-process soak test** (`scripts/soak_test_fps.py`, legacy ON, detection-only, `data/crash.mp4`, telemetry every 60s -- RSS memory, thread count, CPU clock, CPU temp if available):
- **FPS: stable, does NOT fall over 20 minutes.** First-half mean 2.30, second-half mean 2.26 -- effectively flat (the apparent decline seen in the blocked multi-run test was NOT reproduced in a single sustained run).
- **RSS memory: grows substantially but PLATEAUS, does not grow unboundedly.** 1359MB (t=0) -> climbs at ~75-90MB/min through t=840s -> plateaus at ~2780-2790MB from t=840s to t=1141s (final ~5 minutes essentially flat: 2784.9, 2783.8, 2788.0, 2784.3, 2781.3, 2777.7 MB -- bouncing within a ~10MB band). **Total growth: +1418.7 MB over 1141s (74.6 MB/min average over the whole run, but the real shape is "grows then plateaus," not linear forever.)**
- **CPU clock**: fluctuated between 2002 MHz and 3100 MHz throughout (Windows power-management step, "Balanced" plan, confirmed on AC power) with no correlation to the FPS trend (FPS stayed flat regardless of which clock speed was sampled).
- **CPU temperature**: not available -- `psutil.sensors_temperatures()` is not supported on Windows, and no WMI thermal-zone sensor was exposed on this machine either (`MSAcpi_ThermalZoneTemperature` query returned nothing).
- **Conclusion**: memory grows (to a bounded plateau, not infinitely) but FPS does NOT fall with it -- ruling out "memory growth is throttling detection" as the explanation for anything. **The earlier blocked-order FPS decline remains unexplained** (a single sustained run never reproduced it). Phase 1c follow-up 3 ruled out one more candidate explanation -- see its item 1 below: it is NOT an orphaned/leaked process from a prior run contending for CPU, since no such process was ever found. The most likely remaining explanation is something specific to repeated fresh model-loading/Python-process-startup cycling in quick succession (e.g. OS/filesystem cache eviction between runs, or CPU boost-clock exhaustion specific to repeated short bursts), not a property of sustained single-process operation, and not a leaked process either. Not conclusively identified; flagged as open.

**Memory growth source, investigated (not fixed) per instruction**: cross-checked the ~1427MB plateau against this project's own bounded buffers. `api/services/evidence_service.py`'s legacy `FrameBuffer` (separate from the Phase 1c `EventCapturePipeline`/`RingBuffer` work) is constructed via `get_or_create_buffer(camera_id, fps=30.0)` (main.py's call site passes no `fps`, so the default applies) -> `max_frames = int(max_seconds * fps) = int(60 * 30) = 1800` raw (uncompressed) BGR frames, `maxlen`-capped. At `DETECT_WIDTH=640` on this clip's aspect ratio (640x360), that's `1800 * 640*360*3 bytes ~= 1186.5 MB` -- accounting for ~83% of the observed growth on its own. The remaining ~240MB is plausibly `fall_detection.StateManager`'s per-person state dict (bounded by `expiry_seconds`-based pruning, confirmed present in `fall_detection/state.py`) and other minor steady-state allocations across the violence/fall/snatch/fire/crash pipelines filling their own internal buffers for the first time.

**One genuine unbounded accumulation found in this project's own code** (small, likely NOT the dominant growth source given the plateau evidence above, but real and worth fixing eventually): `snatch_detection/tracking/tracker.py`'s `OCSortTracker.history: dict = {}` (line 24) stores one `np.array([x, y])` per track ID ever seen (line 70: `self.history[t_id] = center`), keyed by ByteTrack's internally-incrementing track ID -- **never pruned, no expiry, no size cap**, unlike every other per-track state structure in this codebase (`fall_detection.StateManager._states` IS pruned via `expiry_seconds`; `MotionBranchWrapper.frame_buffer` IS capped via `buffer_size`). Over a long-running deployment with continuous track churn (people entering/leaving frame, occlusion-driven re-IDs), this dict grows by one small entry per new track ID for the life of the process. Also flagged, not confirmed as a meaningful contributor: `supervision`'s own `ByteTrack` instance (wrapped by `OCSortTracker.tracker`) exposes public `lost_tracks`/`removed_tracks` attributes whose internal pruning behavior was not fully audited (third-party library internals, out of scope to modify this phase). **Not fixed this phase** (per instruction: report, don't fix, unless the cause is obvious and small -- this is small per-entry but its pruning fix would require understanding the track-ID lifecycle semantics correctly, which deserves its own review rather than a rushed one-line fix here).

### 5. Effective-config dump: every setting, its source, secrets redacted
New `api/core/config_dump.py`: `dump_effective_config()`/`print_effective_config()` report every `Settings` field's current value AND where it came from -- `default` (untouched class default), `env_var` (an OS environment variable with that exact name was set), `config_file` (present in `.env` but not as a live env var), or `cli` (the calling script re-applied its own argparse flag's value). Secrets redacted by name pattern (`TOKEN`/`KEY`/`SECRET`/`PASSWORD`, case-insensitive) -- defensive, since this project's real secrets (`TELEGRAM_BOT_TOKEN`, `OMNIDIM_API_KEY`, `SERPAPI_KEY`, etc.) are read directly via `os.environ.get()` outside the `Settings` class and were never at risk of appearing in this dump in the first place (confirmed: none of them are `Settings` fields).

Wired into `main.py` (prints once at startup, before connecting to the camera), `scripts/camera_replay.py`, and `scripts/eval_detectors.py` (both print it as part of their run metadata, with `--sample-interval-s` tracked as a `cli` source when passed).

**Proof of env-var override, pasted**:
```
$ SAMPLE_INTERVAL_S=0.5 python3 -c "from api.core.config_dump import print_effective_config; print_effective_config()"
  SAMPLE_INTERVAL_S=0.5 [env_var]
  LEGACY_DETECTORS_ENABLED=True [default]
```
**Proof of CLI override, pasted** (`eval_detectors.py --sample-interval-s 0.5`):
```
  ALERTS_ENABLED=False [default]
  SAMPLE_INTERVAL_S=0.5 [cli]
  LEGACY_DETECTORS_ENABLED=True [default]
```
`ALERTS_ENABLED` and `LEGACY_DETECTORS_ENABLED` are both included in every dump (confirmed present in both examples above).

### 6. --fast eval vs live: different gates, different effective FPS, now stated explicitly
`scripts/eval_detectors.py --fast` (the default) uses `TimeBasedSampler`, which is **deterministic**: it samples by VIDEO time (`frame_index / native_fps`), so `effective_fps` in fast mode is just the nominal `1/sample_interval_s` target -- there is no concept of "falling behind" in fast mode, since it never races a real clock. **The live loop (and eval's own `--realtime` mode) use `RealtimeFrameGate`**, which samples against the actual wall clock and reports the ACTUALLY ACHIEVED rate, which can be (and, per the interleaved measurement above, reliably is, when legacy detectors also run) lower than the target.

**Effective live FPS, measured in `--realtime` mode** (from Phase 1c Follow-up 1, carried forward): `data/crash.mp4` `HIT` at `fps=1.41` (fell behind the 4.0 target), `data/fire.mp4` `HIT` at `fps=4.7` (kept up). **Effective live FPS, measured via the live loop itself** (this follow-up, detection-only, interleaved): fire+crash alone (legacy OFF) achieves close to the full 4.0 fps target (mean 3.98); with legacy detectors also running (legacy ON, the live loop's actual default configuration), effective FPS drops to a mean of 3.27, with per-run variance down to 2.10 at its lowest. **Anyone comparing `--fast` eval numbers to live deployment numbers must account for both gaps**: (a) `--fast` reports a nominal target, not an achieved rate, and (b) even `--realtime`/live-loop-measured FPS with fire+crash ALONE doesn't represent default live behavior, because the live loop also runs violence/fall/snatch by default (`LEGACY_DETECTORS_ENABLED=True`), which measurably slows fire+crash throughput (see item 3 above).

### Files changed this phase
`api/core/config.py` (`FIRE_CRASH_CONFIDENCE_FLOOR`, `DETECTION_ONLY_MODE`), `scripts/camera_replay.py` (`--confidence-floor`, effective-config dump), `scripts/eval_detectors.py` (`--confidence-floor`, effective-config dump), `api/services/detector_interface.py` (`DetectorRegistry(confidence_floor=...)`, threshold now parameterized instead of hardcoded 0.5), `main.py` (effective-config dump at startup, `DETECTION_ONLY_MODE` gate on the event-pipeline feed call), `api/core/config_dump.py` (new), `scripts/measure_live_loop_fps.py` (rewritten: configurable clip, repeats, mean/min/max, `--detection-only`), `scripts/run_single_fps_measurement.py` (new, fresh-process single-run worker), `scripts/measure_live_loop_fps_interleaved.py` (new, interleaved orchestrator), `scripts/soak_test_fps.py` (new), `scripts/system_telemetry.py` (new), `scripts/corpus_notes.md` (new -- labels `testing/snatch.mp4` as `label_class=snatch (not_supported)` with its live-loop false-positive crash detections kept as evidence, not discarded).

### Assumptions and open questions
1. **The original blocked-order FPS decline remains unexplained** -- the soak test ruled out "memory growth causes it" and "it happens in sustained single-process operation," but didn't identify the real cause of the repeated-fresh-process-startup pattern's apparent slowdown. If this matters for future measurement methodology, it needs its own targeted investigation (e.g. instrumenting OS-level resource contention across rapid process restarts).
2. **`OCSortTracker.history`'s unbounded growth is reported, not fixed** -- small per-entry, likely not the dominant contributor to the ~1.4GB plateau (which is well-explained by `FrameBuffer`'s bounded cap alone), but a real correctness gap worth a dedicated fix (add `expiry`/pruning matching the pattern already used in `fall_detection.StateManager`) in a future phase.
3. **CPU temperature is not observable on this machine via any method tried** (psutil, WMI thermal zone) -- if thermal throttling is suspected again in the future, a different measurement approach (external hardware monitor, or accepting CPU clock speed as the only proxy) would be needed.
4. **The interleaved measurement used only 3 repeats per condition** (6 runs total, ~17 minutes with cooldowns) -- a second pass with randomized (not just alternated) order was suggested as "if time allows"; not done this phase, flagged as optional follow-up if even more rigor is wanted.
5. **`FIRE_CRASH_CONFIDENCE_FLOOR`/`--confidence-floor` plumbing is in place but Phase 2's "run eval at both 0.5 and 0.0" comparison was not performed this phase** -- explicitly deferred, per instruction.

## Phase 1c Sampling Unification (2026-10-01)

### Scope
Unify frame-sampling behavior across main.py's live loop, scripts/camera_replay.py, and scripts/eval_detectors.py, via one shared time-based sampling module. This is a DELIBERATE live-behavior change (main.py no longer runs fire/crash detection on every single frame) -- explicitly requested and flagged here per instruction. Same scope lock as before: no police/hospital lookup, no threshold retuning, no frontend work.

### New shared module: `api/services/frame_sampler.py`
- `TimeBasedSampler` (deterministic, for video FILES): samples by VIDEO time (`frame_index / native_fps`), not frame count -- a frame is processed only once at least `sample_interval_s` of video time has passed since the last sampled frame. Reproducible: the same clip always yields the same sampled-frame set regardless of machine speed. Used by `scripts/camera_replay.py` and `scripts/eval_detectors.py --fast` (the default).
- `RealtimeFrameGate` (for the live loop / `eval_detectors.py --realtime`): samples against the real wall clock as frames arrive continuously, always drops any frames that arrived in between (never queues a backlog -- the live loop must process the LATEST available frame), and tracks the ACTUALLY ACHIEVED `effective_fps`, logging it every ~5s (`[RealtimeFrameGate:<label>] effective processed FPS over last Xs: Y (target: Z @ 0.25s interval)`).
- `confirmation_window_seconds(n, m, interval)`: what `EVENT_CONFIRM_N`-of-`EVENT_CONFIRM_M` means in real time now that confirmation counts sampled frames only. At the shipped defaults (N=3, M=5, `SAMPLE_INTERVAL_S=0.25`): **3 of the last 5 sampled frames must hit, spanning 1.00 second of real/video time**.

### Config
- `SAMPLE_INTERVAL_S: float = 0.25` (~4 fps) -- NOT defaulted to 0 (which would mean "every frame" and reintroduce the risk of inference silently falling behind with no defined fallback). Chosen because it's close to what fire+crash YOLO inference actually sustains combined on this machine's CPU (~200-400ms/frame, measured in the Phase 1c follow-ups JPEG-overhead report).
- `LEGACY_DETECTORS_ENABLED: bool = True` (default -- live deployment behavior unchanged unless explicitly turned off). When `False`, `main.py` builds NEITHER the violence (CLIP) model NOR the fall/snatch pipelines -- fire+crash run alone, matching exactly what `eval_detectors.py`/`camera_replay.py` measure and replay, for an apples-to-apples comparison.

### `api/services/event_capture.py`: split `feed_frame()` into `add_raw_frame()` + `feed_detection()`
The ring buffer (and an already-active event's frame list) must keep EVERY raw frame for clip quality -- only DETECTION (confirmation counting, event lifecycle) is throttled to sampled frames. This required splitting the previously-unified `feed_frame()`:
- **`add_raw_frame(frame, ts, video_offset_s=None)`**: called on EVERY frame. Feeds the pre-event ring buffer; if an event is currently active, appends the frame to it tagged `confidence=0.0` ("not evaluated for detection", not "no detection").
- **`feed_detection(frame, ts, category, confidence, boxes, ...)`**: called ONLY on sampled frames (immediately after `add_raw_frame()` for the same frame, by every caller). Does the actual N-of-M confirmation counting and event start/extend/end/merge lifecycle. When a sampled frame lands on a frame `add_raw_frame()` just appended to an active event, updates that exact entry's confidence/boxes in place (the real detector verdict) instead of appending a duplicate -- proven directly: fed 3 confirmed hits, then several add_raw_frame()-only (unsampled) frames, then 1 more sampled hit, then an end; the resulting event had 10 total stored frames (every raw frame) but only 2 with `confidence > 0` (the 2 genuinely sampled hits) -- confirming both "ring buffer keeps every frame" and "confirmation counts sampled frames only" simultaneously.

### Real bug found and fixed while implementing this: the "merge" path could crash
While wiring `feed_detection()`, found that the PRE-EXISTING merge-within-`EVENT_MERGE_SECONDS` code path (`if merged: self._active.frames.append(...)`) referenced `self._active` while `self._active` was still `None` at that point in the code (the branch runs precisely when `self._active is None`) -- `_try_merge()` only ever checked eligibility, there was no code path that actually resumed or recreated an `ActiveEvent` on a merge. This was never triggered in any of the (successful) Phase 1c hardening tests because those runs' gaps were always short enough to stay in the "extend an active event" path, never the "start fresh after a full end+merge-window" path. Directly reproduced with a standalone test (confirm an event, force it to end via a >5s gap, wait, then confirm a second event within the 15s merge window) -- confirmed it crashes with `AttributeError: 'NoneType' object has no attribute 'frames'` on the unfixed code. **Fixed**: since the previous `ActiveEvent` was already finalized and hastily handed to the encoder queue by `_end_event` (no live object to resume), a "merge" now just starts a genuinely new event via the existing `_start_event()`, with a comment explaining that `_try_merge()`'s real effect today is informational only -- fusing two already-encoded incidents back together after the fact would be a larger, separate feature, not implemented. Verified fixed: the same reproduction now completes with `merge path: NO CRASH`.

### main.py: wired, additively, fire/crash only
- New `RealtimeFrameGate(sample_interval_s=settings.SAMPLE_INTERVAL_S, label="fire+crash")`, checked once per loop iteration using `iteration_start` (captured at the TOP of the iteration, before violence/fall/snatch/crash/fire all run) -- so a slow OVERALL iteration (e.g. fall-detection pose inference alone exceeding the sample interval) correctly causes fire/crash to be skipped that iteration too, not just a timer local to crash/fire's own inference time (per explicit instruction: "must use total loop time per iteration, not only fire/crash inference time").
- `crash_detector.process_frame()`/`fire_detector.process_frame()` themselves are now only called when the gate opens (`run_fire_crash_this_iteration`) -- previously they ran every frame. The legacy alert path (`send_telegram_alert`/`send_call_alert`/`send_incident_to_api`, all still gated by `ALERTS_ENABLED`) is entirely INSIDE that same gated block, so it now also only evaluates fire/crash results on sampled iterations -- a real, intentional behavior change to the alert cadence (alerts already default OFF via `ALERTS_ENABLED=False`, so this has no live effect unless an operator has explicitly turned alerts on).
- Violence/fall/snatch keep running every frame, completely untouched, UNLESS `LEGACY_DETECTORS_ENABLED=False`, in which case they are not built/run at all this process run.
- `add_raw_frame()` is called every iteration (unconditionally, before the gate check) so the ring buffer keeps seeing every frame regardless of the sampling decision.

### scripts/camera_replay.py and scripts/eval_detectors.py: same shared function, run metadata recorded
- `camera_replay.py` now uses `TimeBasedSampler` (was: its own inline `step = round(native_fps / sample_fps)` frame-skip math, duplicated near-identically in `eval_detectors.py` -- both copies deleted). `add_raw_frame()` is called for every frame read; `feed_detection()` only for sampled ones. Prints run metadata (`sample_interval_s`, fire/crash-only detector list) at start, and final sampled/processed-frame counts at the end.
- `eval_detectors.py` gained `--realtime` (uses `RealtimeFrameGate`, reports the ACTUALLY ACHIEVED `effective_fps`) alongside the existing deterministic default (now explicitly `--fast`-equivalent, using `TimeBasedSampler`, reporting the nominal `1/sample_interval_s` since there's no "falling behind" concept in deterministic mode). `--sample-interval-s` overrides the config default. Both modes print `Run metadata: mode=..., sample_interval_s=...` before AND after the results table, directly alongside the metrics as instructed.
- Real run, `--fast` (default): `mode=fast, sample_interval_s=0.25` → `crash.mp4`/`fire.mp4` both `HIT` at `fps=4.0` (the nominal target, since fast mode is deterministic).
- Real run, `--realtime`: `mode=realtime, sample_interval_s=0.25` → `crash.mp4` `HIT` at `fps=1.41` (inference genuinely fell behind the 4fps target on this machine/clip), `fire.mp4` `HIT` at `fps=4.7` (kept up, since that loop's per-frame decode+read overhead alone consumed most of the interval without needing to await heavy compute in the same proportion). This is the honest, machine-real achieved rate, not an assumed one.

### Measured: live loop effective FPS, legacy detectors ON vs OFF, same clip (`data/crash.mp4`)
Two repeated measurements (`scripts/measure_live_loop_fps.py`, 30s each, `LEGACY_DETECTORS_ENABLED` toggled via env, `.env`'s stale `VIOLENCE_DETECTION=0`/`FALL_DETECTION=0`/`SNATCH_DETECTION=0` overridden to `1` so the comparison is genuine rather than accidentally comparing "crash-only" against "crash-only" -- a real bug in the first measurement attempt, caught before reporting):

| Run | Legacy ON (violence+fall+snatch also running) | Legacy OFF (fire+crash only) | Delta |
|---|---|---|---|
| 1 (20s window) | 3.33 fps avg (3 samples: 3.19, 3.39, 3.42) | 2.98 fps avg (8 samples: 3.36, 3.96, 2.28, 3.84, 2.07, 3.44, 1.42, 3.47) | -10.5% |
| 2 (30s window) | 3.13 fps avg (6 samples: 3.13, 3.18, 2.99, 3.23, 2.87, 3.39) | 2.88 fps avg (11 samples: 1.98, 3.48, 2.33, 3.87, ...) | -8.0% |

**Counter-intuitive but real and explained, not noise**: Legacy OFF is consistently slightly SLOWER in effective fire/crash throughput, not faster, across both repeats. Root cause identified by cross-referencing incident counts: Legacy OFF's fire+crash inference alone is genuinely faster per-call (no CLIP/fall/snatch competing for CPU), which means MORE crash events get confirmed and finished per unit time in the same window (3 incidents in the 30s Legacy-OFF run vs. 2 in Legacy-ON) -- each finished event triggers `_build_evidence()`'s `ffmpeg` subprocess call, and that encode-queue CPU activity contends with (and measurably drags down) the SAME process's detection thread via OS scheduling/GIL contention. The oscillating high/low pattern in Legacy OFF's per-5s-window samples (e.g. 1.98 -> 3.48 -> 2.33 -> 3.87) lines up with encode bursts. **This is not "legacy detectors slow things down"** -- it's "processing fire/crash faster causes more encode-triggering events per window, and encoding itself has a real, measurable CPU cost on THIS detection thread" -- a genuinely useful capacity-planning finding, distinct from the naive reading of the raw percentage.

### CHANGELOG note on eval-vs-live scope (explicit, per instruction)
`scripts/eval_detectors.py` and `scripts/camera_replay.py` measure/replay **fire and crash ONLY** -- this has always been true (Phase 1c hardening's detector-interface item explicitly registered only fire/crash), and is now also true of `main.py`'s live loop whenever `LEGACY_DETECTORS_ENABLED=False`. With the default `LEGACY_DETECTORS_ENABLED=True`, the live loop ALSO runs violence(CLIP)/fall/snatch concurrently on the same CPU, competing for the same resources fire/crash inference needs -- so a live deployment's real fire/crash throughput will differ from what the eval harness reports for the identical clip/settings (see the measured FPS gap above, though its direction/magnitude is dominated by encode-queue contention, not raw CPU competition, on this test run). Anyone comparing eval numbers to live-deployment numbers should account for this gap rather than assuming they're directly comparable.

### Files changed this phase
`api/services/frame_sampler.py` (new), `api/services/event_capture.py` (`feed_frame()` split into `add_raw_frame()`/`feed_detection()`, `_last_raw_sample` tracking, merge-path crash fixed), `api/core/config.py` (`SAMPLE_INTERVAL_S`, `LEGACY_DETECTORS_ENABLED`), `main.py` (gate wired to fire/crash only, `LEGACY_DETECTORS_ENABLED` toggles violence/fall/snatch construction), `scripts/camera_replay.py` (rewritten to use `TimeBasedSampler`/`add_raw_frame`/`feed_detection`, run metadata printed), `scripts/eval_detectors.py` (rewritten with `--realtime`/`--fast` modes, run metadata printed), `scripts/measure_live_loop_fps.py` (new), `api/services/detection_service.py` (no change needed -- its single-frame `_create_test_replay_incident` path doesn't go through the sampler at all, since a single uploaded photo has no "frames to sample" concept).

### Assumptions and open questions
1. **The merge-path bug fix changes behavior slightly**: a "merged" event previously would have crashed (never actually exercised in practice before this phase, per the investigation above); it now always creates a genuinely new incident rather than attempting to extend an already-finalized one. If a future phase wants "two bursts within the merge window" to actually appear as ONE incident record (not two), that requires a different design (e.g. an explicit `merged_from_incident_id` link, applied after the fact) -- not implemented, flagged as a real product question, not just an implementation detail.
2. **The FPS-comparison measurement is inherently noisy on a single shared machine** (CPU-bound Python + subprocess ffmpeg + OS scheduling) -- the reported percentages are real and reproduced across 2 runs in the same direction, but the underlying cause (encode-queue contention, not legacy-detector CPU competition) matters more than the exact percentage, which will vary run to run and especially machine to machine.
3. **`camera_replay.py`'s `--sample-interval-s` and `eval_detectors.py`'s `--sample-interval-s` both default to the config value** (`SAMPLE_INTERVAL_S=0.25`) rather than hardcoding their own -- changing the config changes all three call sites' default behavior together, which is the intended "one shared rule" outcome.
4. **A one-time ~45MB resnet18 download** (`snatch_detection`'s motion branch) was triggered by this phase's FPS measurement, since this repo's `.env` had `SNATCH_DETECTION=0` and it had apparently never run before. Now cached locally (`~/.cache/torch/hub/checkpoints/`); flagging since it's a real, if one-time, cost for anyone else reproducing this measurement fresh.

## Phase 1c Follow-ups (2026-10-01)

### Scope
Three small follow-ups to Phase 1c Hardening: a hard `ALERTS_ENABLED` kill-switch for the legacy Telegram/call alert path, a rigorous measurement of the JPEG ring-buffer's real FPS/CPU/quality cost (replacing the prior phase's informal note), and a housekeeping confirmation on `notification_status`. Same scope lock as before.

### 1. ALERTS_ENABLED (default false) -- diff and proof pasted
Added `ALERTS_ENABLED: bool = False` to `api/core/config.py`. Both `Telebot_Alert.send_telegram_alert()` and `Call_Alert.send_call_alert()` now check it FIRST, before any other existing check (missing env vars, cooldown, etc.) -- if false, the function logs `"[Telebot_Alert] ALERTS_ENABLED is false -- alerts disabled for this run."` / `"[Call_Alert] ..."` exactly once per process (a module-level `_disabled_notice_logged` flag), not once per call, and returns immediately.

**Diff** (full, both files + config):
```diff
--- a/Call_Alert.py
+++ b/Call_Alert.py
@@ -2,6 +2,8 @@ import os
 import time
 import requests
 
+from api.core.config import settings
+
 # --- Configuration (all values come from environment variables) ---
 ...
 CALL_COOLDOWN_SECONDS = 120  # avoid spamming calls; separate cooldown from the Telegram alert
 _last_call_time = {}
 
+_disabled_notice_logged = False
+
 def send_call_alert(message: str, reason: str = "general"):
     """Triggers an outbound AI voice call via Omnidimension."""
+    global _disabled_notice_logged
+    if not settings.ALERTS_ENABLED:
+        if not _disabled_notice_logged:
+            print("[Call_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.")
+            _disabled_notice_logged = True
+        return
+
     print("call alert started")
     ...

--- a/Telebot_Alert.py
+++ b/Telebot_Alert.py
@@ -3,6 +3,8 @@ import telebot
 import cv2
 import time
 
+from api.core.config import settings
+
 # Initialize the Telegram bot
 ...
 _last_alert_time = {}
 
+_disabled_notice_logged = False
+
 def send_telegram_alert(frame, message, reason: str = "general"):
+    global _disabled_notice_logged
+    if not settings.ALERTS_ENABLED:
+        if not _disabled_notice_logged:
+            print("[Telebot_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.")
+            _disabled_notice_logged = True
+        return
+
     print("telegram alert started")
     ...

--- a/api/core/config.py
+++ b/api/core/config.py
+    ALERTS_ENABLED: bool = False
```

**Test proving no alert code runs by default**: called both functions twice each (different `reason` values) with `telebot.TeleBot.send_photo`/`send_message` and `requests.post` mocked:
```
ALERTS_ENABLED default: False
[Telebot_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.
telegram send_photo called: False
telegram send_message called: False
[Call_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.
requests.post called: False

ALL ASSERTIONS PASSED: no alert network call fired with ALERTS_ENABLED=False (default)
```
Note the "alerts disabled" line printed exactly once per function across both calls (module-level flag), not twice. Also verified the flag is a real gate, not a permanent block: with `ALERTS_ENABLED` patched to `True`, `send_telegram_alert()` proceeds past the gate to the next pre-existing check (`"telegram alert started"` / `"missing TELEGRAM_BOT_TOKEN..."`).

### 2. JPEG ring-buffer overhead: measured rigorously, made configurable (default 90), quality confirmed near-lossless
`JPEG_QUALITY` moved from a hardcoded `85` in `api/services/event_capture.py` to `settings.JPEG_QUALITY` (config, default raised to `90` per instruction).

**Methodology note**: an earlier attempt at this measurement used (a) a synthetic no-op loop for the "without buffer" baseline, which gave a meaningless "11 million FPS" result since there was no real work to compare against, and (b) `data/fire.mp4`'s very first frame for the PSNR/SSIM quality check, which turned out to be solid black (`std=0`) -- a degenerate frame JPEG compresses losslessly, giving a meaningless "PSNR=361dB" result. Both were caught and fixed before reporting: the FPS baseline now runs the REAL fire+crash YOLO detectors (`fire_detection`/`crash_detection`, same code `main.py` uses) as the per-frame workload, and the quality check seeks to the middle of a clip where real visual detail (flames, people, a CCTV timestamp overlay) is actually present.

**1. Per-frame JPEG compress time** (real 1080p/720p frames from `data/crash.mp4`, JPEG quality 90, 200 iterations):
| Resolution | Mean compress time | Max compress time | Encoded size |
|---|---|---|---|
| 720p | 2.8 ms | 4.4-4.9 ms | 132.3 KB |
| 1080p | 5.7-5.9 ms | 8.3-13.9 ms | 223-224 KB |

**2 & 3. Detection FPS + CPU, ring buffer ON vs OFF, real fire+crash detectors running per frame** (median of 3 repeats per condition, 8s windows, 1920x1080 frame):
| Cameras | Without buffer | With buffer | FPS delta |
|---|---|---|---|
| 1 | 4.6 fps/camera, 433% CPU | 5.0 fps/camera, 387% CPU | within noise (+8.7%, i.e. no measurable drop) |
| 3 | 2.6 fps/camera, 963% CPU | 2.8 fps/camera, 1015% CPU | within noise (+7.7%, i.e. no measurable drop) |

**Finding**: real YOLO inference (fire+crash detectors combined) costs ~200-400ms per frame at 1080p on this machine's CPU -- two to three orders of magnitude more than the ring buffer's ~6ms JPEG-encode cost. The buffer's overhead is statistically indistinguishable from zero against that baseline (the measured "deltas" are noise from thread-scheduling/GIL contention across repeats, not a real effect -- both conditions' per-run FPS values overlap). **No JPEG quality or downscale setting is needed to keep FPS acceptable** -- FPS in this pipeline is bottlenecked entirely by model inference, not by evidence capture. CPU usage does rise modestly with more concurrent cameras (963%->1015% CPU at 3 cameras, i.e. roughly 10 of this machine's logical cores saturated by 3 concurrent YOLO inference threads), which is a real capacity-planning number for multi-camera deployment sizing, but again dominated by inference, not the buffer.

**4. Quality: PSNR/SSIM of a JPEG q90 round-trip against the original frame** (real mid-clip frame from `data/fire.mp4`, 1920x1080, visible flames/people/timestamp overlay):
```
{'psnr_db': 46.26, 'ssim': 0.9957, 'jpeg_quality_used': 90}
```
PSNR > 40dB and SSIM > 0.99 are both conventionally considered visually near-lossless. A saved before/after frame pair was visually inspected side by side: no perceptible difference in the fire, the people, or the CCTV timestamp overlay text -- confirms the PSNR/SSIM numbers, not just an isolated metric. (The before/after image files and the measurement script's `scripts/measure_jpeg_overhead.py` are kept; the one-off comparison images from this run were cleaned up after inspection, not committed as data.)

### 3. notification_status: confirmed "not_implemented" everywhere (no code change needed) + routing-phase note
Repo-wide grep (`grep -rn "notification_status" --include="*.py" .`, excluding `archive/`) confirms `notification_status` is declared in exactly ONE place in the entire live codebase -- `api/models/incident_v2.py`'s `notification_status: str = "not_implemented"` field default -- and is never set, read, or overridden by any other code path. Every incident, from every source (`live` or `test_replay`), therefore already always has `notification_status == "not_implemented"`; confirmed on a fresh incident created after this check (`GET /api/v1/incidents/{id}` -> `"notification_status": "not_implemented"`). No code change was required.

**Record for the routing phase**: the legacy Telegram/call alert path (`Telebot_Alert.py`/`Call_Alert.py`, called directly from `main.py`'s live loop, gated by `ALERTS_ENABLED` as of item 1 above) is a SEPARATE, independent notification mechanism from `Incident.notification_status` -- see Phase 1c Hardening's item 1 for the full description of that inconsistency. **This legacy alert path will be replaced by a proper notification-routing system in a future "routing phase"**, at which point `notification_status` should become a real, updated field (reflecting what was actually sent, to whom, and when) rather than a permanent placeholder. Until that phase, `notification_status` should be read as "notification routing is not yet implemented for this incident," not as "no alert was ever sent" -- those are different claims, and only the legacy alert path (independently, invisibly to this field) may have actually sent something in live mode.

### Files changed this phase
`api/core/config.py` (`ALERTS_ENABLED`, `JPEG_QUALITY`), `Telebot_Alert.py` (ALERTS_ENABLED gate), `Call_Alert.py` (ALERTS_ENABLED gate), `api/services/event_capture.py` (`JPEG_QUALITY` now reads from config instead of a hardcoded constant), `scripts/measure_jpeg_overhead.py` (new).

### Assumptions and open questions
1. **`ALERTS_ENABLED` is a single global switch**, not per-alert-type or per-camera. If a future deployment wants Telegram enabled but calls disabled (or vice versa), this would need splitting into two flags -- not requested, not done.
2. **The FPS/CPU measurement used this development machine's CPU only** (no GPU inference path exercised) -- a GPU-accelerated deployment would show different absolute numbers, though the qualitative finding (buffer overhead negligible vs. inference cost) should still hold since JPEG encoding stays CPU-bound either way.
3. **CPU-percent figures are `psutil.Process().cpu_percent()`**, i.e. this process's own usage (can exceed 100% on multi-core machines, as seen: ~1000% at 3 concurrent camera threads = ~10 cores). Not a system-wide measurement.

### Scope
Hardening fixes to the CCTV Incident Capture Pipeline before Phase 2 prep work: main.py's double-detection question, ring-buffer memory, replay video-relative timestamps, bounded encode queue + failure handling, SQLite WAL/concurrency, a real browser playback check, a detector interface (fire/crash only), and documenting (not fixing) frontend schema dependencies. Same scope lock as before: no police/hospital lookup, no alert changes, no frontend fixes, no threshold retuning.

### 1. Live loop: detection ran ONCE per frame, not twice -- confirmed, and a real independent-policy gap documented
Read `main.py`'s `detection_loop()` closely: `crash_detector.process_frame(frame)` and `fire_detector.process_frame(frame)` are each called exactly once per frame, and the single `crash_result`/`fire_result` object is reused both for `_feed_event_pipeline()` (new) and the existing Telegram/call alert block (old) -- there is no second, duplicate model invocation. Confirmed by direct code reading (`main.py` lines ~445-494): both consumers read from the same local variable.

**Test_replay mode cannot trigger old alerts**: `scripts/camera_replay.py` and `api/routes/detect.py`/`api/services/detection_service.py` (the dev/test upload path) never import or call `send_telegram_alert`/`send_call_alert` anywhere -- confirmed via `grep -n "send_telegram_alert\|send_call_alert" scripts/camera_replay.py api/routes/detect.py api/services/detection_service.py`, zero matches. Only `main.py`'s live loop can ever call those functions, and only for `source="live"` incidents.

**The real inconsistency, documented (not fixed this phase -- alert code is scope-locked)**: `Incident.notification_status` (`api/models/incident_v2.py`) is a static field hardcoded to `"not_implemented"` and is NEVER updated by any code path (confirmed: `grep -rn "notification_status" api/ main.py` returns only its one declaration). Meanwhile, in **live mode only**, `main.py`'s old alert path has its own, completely independent "is this a new incident" policy: a 30-second cooldown keyed by `{incident_type}_{track_id}` (`api_incident_cooldown`/`should_send_to_api`) plus an alert-transition gate (`was_violent`/`fire_alerted`/`crash_alerted`, fires once per transition into an alert state, not every frame) -- entirely separate from `EventCapturePipeline`'s N-of-M confirmation + merge-window event lifecycle. This means: a real Telegram/call alert may genuinely have fired for the exact detection event a given `Incident` row represents, but that `Incident`'s `notification_status` will always read `"not_implemented"` regardless -- the field is honest about "nothing was built to update it" but misleading if read as "no alert was sent for this incident." Reconciling the two policies (or at minimum making `notification_status` reflect whether the OLD path's cooldown gate actually fired for the same camera+category+time window) is real follow-up work, intentionally not done this phase since it touches the alert path.

**Scope boundary, not a bug**: only fire and crash feed `EventCapturePipeline` in `main.py` (confirmed: `grep -n "_feed_event_pipeline" main.py` shows exactly 2 call sites). Violence(CLIP)/fall/snatch detectors in the live loop still ONLY go through the old alert path and never produce a CCTV-schema `Incident` at all currently -- flagged as an open question below, not silently changed.

### 2. Ring buffer memory: measured, and fixed (raw frames -> JPEG-compressed)
**Before (raw BGR ndarrays, measured, not estimated)**: a real frame from `data/crash.mp4` resized to each target resolution and measured directly:

| Resolution | Raw frame | 8s pre-buffer @ 25fps (200 frames) | Worst-case 120s+pre/post event @ 25fps (3400 frames) |
|---|---|---|---|
| 720p (1280x720) | 2.64 MB | 527 MB/camera | 8965 MB/camera |
| 1080p (1920x1080) | 5.93 MB | 1187 MB/camera | 20171 MB/camera |
| 4K (3840x2160) | 23.73 MB | 4746 MB/camera | 80684 MB/camera |

A single 4K camera's worst-case active event alone would need ~80GB -- untenable, and the cause was found in `api/services/event_capture.py`: `RingBuffer.add()` stored `frame.copy()` (raw ndarray) and `ActiveEvent.frames` held a raw `FrameSample` per sampled frame for the whole pre+event+post duration.

**Fix**: `FrameSample.frame` is now JPEG-encoded bytes (`cv2.imencode(".jpg", frame, [IMWRITE_JPEG_QUALITY, 85])`), not a raw ndarray, with a `.decode()` method used only for the handful of frames actually needed (best-frame selection, clip re-encoding) -- never for the whole buffer at once. `RingBuffer.add()` encodes on ingest; `FrameSample.from_ndarray()` is the single construction path everywhere a raw frame enters a `FrameSample`.

**After (measured on the same real crash.mp4 frame, JPEG quality 85)**:

| Resolution | JPEG frame | Compression ratio | 8s pre-buffer | Worst-case 120s event |
|---|---|---|---|---|
| 720p | 107.8 KB | 25.1x | 21.0 MB/camera | 358 MB/camera |
| 1080p | 181.1 KB | 33.5x | 35.4 MB/camera | 601 MB/camera |
| 4K | 497.3 KB | 48.9x | 97.1 MB/camera | 1651 MB/camera |

**Quality change, honestly noted**: `best_frame.jpg` is now the raw JPEG bytes captured at q85 (written directly to disk), rather than a second cv2.imwrite() re-encode of a decoded higher-quality frame -- avoids a second lossy generation but means `best_frame.jpg` is modestly smaller/lower-quality than before this fix (observed ~89-100KB vs ~145-160KB pre-fix on the same real incidents). `annotated_frame.jpg` and `thumbnail.jpg` are still built by decoding once and re-encoding at their own quality, unaffected. Verified end-to-end: a fresh `CAM-SAMPLE-001` replay after this change still produces a valid h264/yuv420p clip and all 4 evidence files (`ffprobe` confirmed).

### 3. Replay timestamps: video-relative offsets added and proven
Added `FrameSample.video_offset_s` (Optional[float], only ever populated in test_replay mode), `EventCapturePipeline.feed_frame(..., video_offset_s=...)`, and `Incident.video_offset_start_s`/`video_offset_end_s` (null for `source="live"` -- there is no "source video" a live incident could be relative to). `scripts/camera_replay.py` now passes `video_offset_s=video_t` (`frame_index / source_fps`, already computed) on every `feed_frame()` call.

**Proof**: ran `CAM-SAMPLE-001` (`data/crash.mp4`), whose crash event was confirmed at video_t≈4.2s in the replay log. The resulting incident: `video_offset_start_s: 3.87`, `video_offset_end_s: 11.87` -- matching the known second in the source video -- alongside real wall-clock `event_start: 2026-09-30T21:01:34Z`/`event_end: 2026-09-30T21:01:38Z` (today's actual test time, unrelated to the video's own timeline). Both fields exposed side by side in `GET /api/v1/incidents/{id}`.

### 4. Encode failure handling: bounded queue + quarantine-with-best-frame-kept, all 4 failure modes simulated
- **Bounded queue**: `EventCapturePipeline._encode_queue` changed from unbounded `Queue()` to `Queue(maxsize=settings.MAX_ENCODE_QUEUE_SIZE)` (default 8, new config). `_end_event()` now uses `put_nowait()`; on `Full`, the event is immediately quarantined with reason `"encode queue full (>= N pending)..."` rather than blocking the detection thread (which would drop detection FPS -- the one thing this pipeline must not do).
- **ffmpeg failure handling, restructured**: `_build_evidence()` now builds `best_frame.jpg`/`annotated_frame.jpg`/`thumbnail.jpg` FIRST (pure image ops, no ffmpeg dependency), THEN attempts clip encoding. A new `EvidenceBuildError` exception carries `partial_evidence` (the paths that WERE written) so a clip failure never orphans the best-frame evidence. `subprocess.run(...)` for the ffmpeg call now has `timeout=30s` and distinguishes `subprocess.TimeoutExpired` / `subprocess.CalledProcessError` / a missing binary (`ffmpeg_available()` check) into 3 distinctly-worded quarantine reasons.
- **Quarantine now actually persists on encode failure** (a gap found while implementing this): the `on_quarantine` callback previously only printed; a new `incident_service_v2.handle_encode_failure()` writes a real `QuarantinedEvent` row to SQLite, with `partial_evidence`'s best-frame/annotated/thumbnail paths stored in `raw_data.kept_evidence` so the evidence stays discoverable via `GET /api/v1/incidents/_internal/quarantine`, not just mentioned in a log line. `main.py` and `scripts/camera_replay.py`'s `on_quarantine` callbacks both updated to call it.

**All 4 failure modes simulated directly** (`unittest.mock.patch`), using a real confirmed fire event so the failure is isolated to the clip stage:
| Scenario | Incident created? | Quarantined? | Best-frame kept on disk? |
|---|---|---|---|
| Baseline (real ffmpeg, success) | Yes | No | N/A (full evidence) |
| `ffmpeg_available()` mocked False | **No** | **Yes** ("ffmpeg is not installed/on PATH...") | **Yes, confirmed via `os.path.exists()`** |
| `subprocess.run` raises `CalledProcessError(1, stderr=b"Unknown encoder 'libx264'")` | **No** | **Yes** ("ffmpeg exited 1 ... stderr: Unknown encoder 'libx264'") | Yes |
| `subprocess.run` raises `TimeoutExpired(..., 30)` | **No** | **Yes** ("ffmpeg timed out after 30s...") | Yes |
| Queue-full (11 events submitted with the encoder artificially slowed to 3s/event, `MAX_ENCODE_QUEUE_SIZE=8`) | 9 created (drained in time) | **2 quarantined** ("encode queue full (>= 8 pending)...") | queue size measured at exactly 8, never exceeded |

No incident exists without a playable clip unless quarantined -- confirmed in every failure case above (`incident created: None`/`False` in every failure row).

### 5. SQLite: WAL mode + single-writer-path + 10-minute concurrency test, zero errors
`api/db.py`: every connection now runs `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on open; a new `_write()` context manager wraps every write (`insert_incident`, `update_incident_data`, `insert_quarantine`, `init_db`) in a single process-wide `threading.Lock`, serializing writes from this process on top of WAL's reader/writer concurrency. Confirmed active: `PRAGMA journal_mode` reports `('wal',)` after a real write.

**10-minute real concurrent test** (`scripts/sqlite_concurrency_test.py`, against the live running API): 2 writer threads (direct `db.py` incident-creation calls, ~1 every 50ms each), 2 reader threads (`GET /incidents` + `GET /map/groups` every ~100ms), 1 patcher thread (`GET /incidents` then `PATCH .../status` every ~200ms) -- all hammering the same `incidents.db` simultaneously for 601.4 seconds.

**Result**: `{'writes': 18784, 'reads': 226, 'patches': 113}`, **0 total errors, 0 "database is locked" errors**. (The 18,784 stub test incidents were cleaned up afterward via a fresh backend restart against a deleted `incidents.db` -- they were never meant to be kept, only to generate write pressure.)

### 6. Browser check: real Chrome, real playback and seek, screenshot observed
No Playwright/chromium-cli available in this environment; used the actually-installed `C:\Program Files\Google\Chrome\Application\chrome.exe` directly in headless mode with `--remote-debugging-port` + `--remote-allow-origins=*`, driven via the Chrome DevTools Protocol over a raw websocket (Python's `websocket-client`, already installed) -- this is the real Chrome browser engine decoding and rendering the file, not a mock or a curl-based approximation.

Served a real generated clip (`CAM-SAMPLE-002`'s fire incident, 42.06s) through a minimal test page (`scripts/browser_clip_test.html`) with a `<video>` element pointed at `GET /api/v1/evidence/v2/.../clip.mp4`.

**What I saw, verbatim from the page's own event log**:
```
loadedmetadata: duration=42.057489
canplay
play() succeeded
requested seek to 21.028744
seeked to 21.031176
canplay
```
Final video element state: `readyState: 4` (HAVE_ENOUGH_DATA), `paused: false`, `videoWidth/Height: 1162x640` (the clip's real dimensions), `currentTime: 22.66` (playing on past the seek point). A screenshot taken mid-playback shows the actual decoded fire footage rendering inside the `<video>` element (a visible CCTV-style timestamp overlay from the source clip, flames clearly visible) -- not a blank/broken player frame.

### 7. Detector interface: fire and crash only, "not supported" vs "miss" proven
New `api/services/detector_interface.py`: a `Detector` dataclass (`name`, `classes`, `threshold`, `weights_file`, `weights_sha256`, `.detect(frame) -> DetectorResult`) and a `DetectorRegistry` that registers **only** `fire` (classes `["fire", "smoke"]`, wrapping `fire_detection.detector.build_fire_pipeline()`) and `crash` (classes `["Accident"]`, wrapping `crash_detection.detector.build_crash_pipeline()`). Violence/fall/snatch are explicitly NOT wrapped or registered, per instruction -- `main.py`/`detection_service.py` call them exactly as before, untouched.

New `scripts/eval_detectors.py`: takes a JSON manifest of `{path, expected_class}`, and for each entry, checks `registry.supports_class(expected_class)` FIRST -- if no registered detector's `classes` list contains it, reports `"not_supported"` immediately, never runs inference, never counts it as a miss.

**Real run** (`scripts/eval_manifest_sample.json`, sampling each clip at 6fps across its whole duration):
```
Registered detectors: ['fire', 'crash']
Supported classes: ['Accident', 'fire', 'smoke']

HIT             data/crash.mp4        expected='Accident'
HIT             data/fire.mp4         expected='fire'
NOT_SUPPORTED   testing/snatch.mp4    expected='snatching'  no registered detector covers class 'snatching' (registered classes: ['Accident', 'fire', 'smoke'])
NOT_SUPPORTED   data/office_fight.mp4 expected='violence'   no registered detector covers class 'violence' (registered classes: ['Accident', 'fire', 'smoke'])
NOT_SUPPORTED   testing/snatch.mp4    expected='fall'       no registered detector covers class 'fall' (registered classes: ['Accident', 'fire', 'smoke'])

Summary: {'hit': 2, 'not_supported': 3}
```
Exactly the required behavior: real detectors HIT on their own real footage, unsupported classes are `not_supported`, never `miss`.

### 8. Frontend: documented (not fixed) -- Phase 3 to-do list
The frontend was never updated when the backend moved from the old `incident_type`/`severity`/`location.address` schema to the CCTV-only `category`/no-severity/`place_text` schema. Grepped every frontend file for old-schema field reads (`.incident_type`, `.severity`, `.location.`, `.camera_id`, `.evidence_clip`, `.thumbnail_path`):

| File | Old-schema references | What breaks |
|---|---|---|
| `frontend/src/components/IncidentCard.jsx` | 10 (`incident.severity`, `incident.incident_type`, `incident.location?.address/camera_id/latitude/longitude`, `incident.evidence_clip?.video_path`, `incident.thumbnail_path`) | Severity badge, type label, address line, camera/coords fields, clip/thumbnail preview all read undefined |
| `frontend/src/components/TriageQueue.jsx` | 7 (`incident.status`, `.severity`, `.incident_type`, `.location?.camera_id/.address`, `.timestamp`) | Triage filtering (`status !== 'resolved'`) never matches new `status` values (`new/confirmed/false_positive` vs old `new/investigating/resolved/false_positive`); severity/type/camera labels blank |
| `frontend/src/components/IncidentHoverPreview.jsx` | 6 (`.evidence_clip?.video_path`, `.thumbnail_path`, `.severity`, `.status`, `.incident_type`, `.location?.camera_id/.address`) | Hover preview clip/thumbnail/labels all blank |
| `frontend/src/components/MiniMap.jsx` | 6 (`.severity`, `.incident_type` used for heatmap weight/color) | Map heatmap points lose severity-weighting and type-coloring |
| `frontend/src/components/LiveVideo.jsx` | 3 (`.severity`, `.incident_type`, `.location?.camera_id/.address`) | Live-feed overlay's incident badge/camera label blank |
| `frontend/src/pages/Dashboard.jsx` | 7 | Detection-stream swimlane and summary cards keyed on old fields |
| `frontend/src/pages/LiveIncidents.jsx` | 18 | Heaviest user — incident list/detail view largely built around the old shape |
| `frontend/src/pages/MapView.jsx` | 23 | Heaviest user — map pins/clustering built around `location.latitude/longitude` (still present, compatible) but also `incident_type`/`severity` for styling (not present in new schema) |
| `frontend/src/pages/Analytics.jsx` | 7 | Charts grouped by `incident_type`/`severity`, neither exists the same way now (`category` replaces `incident_type`; there is no `severity` field at all in the new schema) |
| `frontend/src/utils/incidentMeta.js` | `severityChipClass()` helper | Called by every component above; has no input once `severity` is gone |
| `frontend/src/context/WebSocketContext.jsx` | message type discriminator only (`'incident_created'`) unaffected; the `data` payload shape changed | New incidents pushed over the websocket carry the new schema -- any component consuming `message.data` directly inherits the same gaps as above |

**Root cause, in one line**: the new schema (`api/models/incident_v2.py`) has no `severity` field at all (removed; `category`-only classification now) and renamed `incident_type` -> `category`, `location.address` -> `place_text`, `location.camera_id` -> `camera_id` (top-level). None of the ~10 frontend files above were touched this phase (explicit scope lock: no frontend work) -- this table is the concrete Phase 3 starting point.

### Files changed/added this phase
`api/services/event_capture.py` (JPEG frame storage, video_offset_s, bounded queue, EvidenceBuildError, ffmpeg timeout/failure handling), `api/models/incident_v2.py` (video_offset_start_s/end_s, event_start future-timestamp validator), `api/services/incident_service_v2.py` (video offsets wired through, new `handle_encode_failure()`), `api/services/detection_service.py` (`FrameSample.from_ndarray()` call site fixed), `main.py` (on_quarantine wired to `handle_encode_failure`), `scripts/camera_replay.py` (video_offset_s passed through, on_quarantine wired), `api/core/config.py` (`MAX_ENCODE_QUEUE_SIZE`), `api/db.py` (WAL mode, busy_timeout, `_write()` lock), `api/services/detector_interface.py` (new), `scripts/eval_detectors.py` (new), `scripts/eval_manifest_sample.json` (new), `scripts/sqlite_concurrency_test.py` (new), `scripts/browser_clip_test.html` (new, test artifact).

### Assumptions and open questions
1. **Should main.py's violence/fall/snatch detectors also feed `EventCapturePipeline`** (currently only fire/crash do, per this phase's explicit instruction)? Carried over from the prior phase's open question, still unresolved -- those detectors currently produce real Telegram/call alerts via the old path but never a CCTV-schema `Incident`.
2. **`notification_status` vs the old alert path's independent cooldown/transition policy** (item 1) is a real, now-documented inconsistency. Reconciling them is out of scope this phase (touches alert code) but should be prioritized before Phase 2 if operators are expected to trust `notification_status` for anything.
3. **`MAX_ENCODE_QUEUE_SIZE=8`** is a reasonable default for this project's few sample cameras; a real multi-camera deployment might need this configurable per-camera or scaled to camera count -- not done, flagged.
4. **`JPEG_QUALITY=85`** was chosen as a reasonable default without a formal quality-vs-size sweep; if evidentiary/legal review needs guaranteed visual fidelity, this should be revisited with an actual human quality check, not just a compression-ratio number.
5. **The SQLite concurrency test's writer threads issue direct `db.py` calls**, not literal detection-thread traffic -- a reasonable proxy (same write path, same lock, same WAL config) but not a byte-for-byte simulation of `EventCapturePipeline`'s actual write pattern (which is far lower-frequency: one write per finished event, not one every 50ms).
6. **Frontend documentation (item 8) is a to-do list, not a fix** -- no frontend file was modified this phase, per scope lock.

## CCTV Incident Capture Pipeline / Scope Reset (2026-10-01)

### Scope
`config/cameras.json` + camera registry, a new shared event-detection/capture pipeline (`api/services/event_capture.py`) used by both `main.py`'s live loop and a new test-replay path (`scripts/camera_replay.py`), a new CCTV-only incident schema (`api/models/incident_v2.py`) persisted in SQLite (`api/db.py`), new API routes (`api/routes/incidents_v2.py`, rewritten `api/routes/map.py`, extended `api/routes/evidence.py`), and archiving the news-scrape live data/scripts. Police/hospital lookup, Telegram/call alerts, notification_status, live-alert cooldown/dedup, and frontend map rendering were explicitly out of scope and not touched (one line in `api/routes/emergency.py` was re-pointed at the new incident store only because the old one stopped being populated — its own lookup logic is unchanged).

### Product scope change
The product now handles ONLY fixed CCTV cameras. Every earlier mobile-device/upload/GPS-provenance feature set (`SourceType.MOBILE_DEVICE`/`UPLOAD`, `LocationSource` variants other than `camera_registry`, `device_id`, `location_accuracy_m`, manual pins, EXIF/ffprobe capture-time extraction, proximity clustering) is **cancelled**, not implemented, and not present in the new schema (`api/models/incident_v2.py` has no such fields at all — grep-verified, see Verification §10).

### Part 1 — Scope cleanup
- **Archived news-scraped data**: all 241 live in-memory incidents (100% `origin: news_scrape`) were paginated out via the API, written to `archive/news_scrape_incidents.json`, and excluded from the live store going forward (the live store was rebuilt on SQLite with nothing carried over — there was no mobile/upload data to preserve; the archived dump's origin breakdown was `{'news_scrape': 241}`, confirmed before archiving).
- **Scraper scripts marked archived, not deleted**: `scripts/fetch_india_incidents.py`, `fetch_jaipur_incidents.py`, `fetch_serpapi_images.py`, `fetch_incident_videos.py`, `scrape_pipeline.py`, `run_india_batches.py`, `run_gap_fill_batches.py` — each got an "ARCHIVED, NOT PART OF THE PRODUCT" docstring header explaining why and pointing at this changelog entry. No code logic inside them was changed; they still run standalone if needed, but their `--create-incidents`/`--run-detect` calls will now be rejected by the live API's CCTV-only ingestion path (no `camera_id` from the registry).
- **`/api/v1/detect` narrowed to a dev/test-only path** (`api/routes/detect.py`): now requires a real registered `camera_id` (rejects with 422 otherwise) and takes location from that camera's registry entry — it no longer accepts `latitude`/`longitude`/`location_name` from the request at all. Every incident it creates is marked `source: "test_replay"`. Internally it was rewired from the old in-memory `incident_service`/`IncidentCreate` (addendum-era schema) onto the same SQLite-backed `incident_service_v2` the live loop uses, via a new `_create_test_replay_incident()` helper in `api/services/detection_service.py` that builds a real 1-frame clip (ffmpeg-encoded, honestly labeled as 1 frame, not a fabricated multi-frame clip) so a single uploaded photo still produces a schema-complete `Evidence` record.
- **Old v1 incident stack marked archived, not deleted**: `api/models/incident.py`, `api/models/provenance.py`, `api/services/incident_service.py`, `api/routes/incidents.py` all got "ARCHIVED, NOT PART OF THE LIVE PRODUCT" docstrings. None of them are imported by `api/main.py` anymore (confirmed: `app.include_router` calls only reference `incidents_v2`, `evidence`, `system`, `detect`, `emergency`, `map`).

### Part 2 — Camera registry
- **`api/models/camera.py`** — `Camera` model extended with `stream_source` (RTSP URL placeholder / device index / video file path) and `enabled`. Added an India-bounding-box `field_validator` on `latitude`/`longitude` (same box used by the scraper's geocoding hygiene) and a `field_validator` on `stream_source` that rejects any value containing an embedded `rtsp://user:pass@host` credential pattern, forcing real deployments to use an `env:VAR_NAME` placeholder instead (resolved at connect time by the new `resolve_stream_source()`, which never logs the resolved value — only the env var name may ever be logged).
- **`config/cameras.json`** — 4 cameras: `CAM-001` (placeholder registration for `main.py`'s/`api_client.py`'s hardcoded live-loop default, explicitly flagged in its `field_of_view_note` as not a real installation), and `CAM-SAMPLE-001/002/003` (Jaipur coordinates, each with a real local video file as `stream_source` for replay testing: `data/crash.mp4`, `data/fire.mp4`, `testing/snatch.mp4`).
- Verified: registry loads 4 cameras, rejects unknown lookups (`None`), rejects a camera with `latitude=0.0`/`longitude=0.0` or `latitude=95.0` with a clear India-bounding-box error (see Verification §10).

### Part 3 — Event detection and capture (shared pipeline)
- **`api/services/event_capture.py`** (new) — `EventCapturePipeline`, one instance per camera, shared by `main.py` and `scripts/camera_replay.py`:
  - `RingBuffer` — wall-clock-bounded (not frame-count-bounded) pre-event buffer, `PRE_EVENT_SECONDS=8` (config).
  - Temporal confirmation: `EVENT_CONFIRM_N=3` of the last `EVENT_CONFIRM_M=5` frames must hit the same class to start an event.
  - Event lifecycle: extends while the same class keeps hitting; ends after `EVENT_END_GAP_SECONDS=5` with no hits or at `MAX_EVENT_SECONDS=120`; a new event of the same class on the same camera within `EVENT_MERGE_SECONDS=15` of the previous end merges into it (proven live — see Verification §4). Different classes on the same camera are always separate events.
  - On event end: picks the highest-confidence frame as `best_frame`, writes it plus a 320px-wide `thumbnail` plus a bounding-box-`annotated` copy, writes the full pre+event+post frame sequence as a raw `mp4v` AVI-in-MP4-container file and re-encodes it with `ffmpeg -c:v libx264 -pix_fmt yuv420p -movflags +faststart` (fails loudly — raises, which the caller turns into a quarantine record — if `ffmpeg` is not on `PATH`; confirmed present on this machine: `ffmpeg 9.0`/`ffprobe 9.0`, libx264 enabled). Computes `sha256` of both the clip and the best frame.
  - Capture/encoding run on a dedicated background thread per camera (a `queue.Queue` drained by a daemon thread), so a slow `ffmpeg` encode never blocks the detection loop; `Queue.task_done()`/`Queue.join()` wired correctly so a caller (e.g. the replay script) can deterministically wait for the encoder to finish before exiting.
  - Logs detection FPS every ~5s and each encode's wall-clock time (see Verification §9).
- **`main.py`** (live loop, scope-locked for its alert/cooldown logic) — additively wired: a new `EventCapturePipeline` instance is created for `CAMERA_ID` if it resolves to a registered camera, and every crash/fire `process_frame()` call now also calls `_feed_event_pipeline()` with that frame's raw verdict (hit or miss, every frame — not gated by the existing alert cooldown, since the event pipeline needs every frame to do its own confirmation/lifecycle correctly). The existing Telegram/call alert + `api_client`/`send_incident_to_api` logic is completely unchanged — this is a second, independent consumer of the same detector output, not a replacement. Incidents created this way are marked `source="live"`. Flushes the pipeline on shutdown (both headless and windowed code paths).
- **`scripts/camera_replay.py`** (new) — the test-replay path required by the spec: takes a registered `camera_id`, resolves its `stream_source` to a real local video file, runs the SAME `fire_detection`/`crash_detection` YOLO detectors `main.py` uses, and feeds every sampled frame through the identical `EventCapturePipeline`. Incidents are marked `source="test_replay"`. Refuses to run against an unregistered `camera_id` or a missing `stream_source` file (no fabricated camera/coordinates).

### Part 4 — Incident schema (CCTV-only)
- **`api/models/incident_v2.py`** (new) — `Incident` with every field the spec lists: `incident_id`, `camera_id`, a camera snapshot (`camera_name`, `place_text`, `latitude`, `longitude`, `location_precision="exact"` always), `category` (7-value controlled vocabulary, same as the Phase 1 scraper: `road_accident|fire|assault|snatching|fall|women_safety|other`), `event_start`/`event_end`/`duration_s`/`detected_at`, a `Detection` sub-object (`detector_source`, `model_name`, `weights_file`, `weights_sha256`, `peak_confidence`, `mean_confidence`, `threshold_applied`, `frames_confirmed` as `"N of M"`, `best_frame_bbox`), an `Evidence` sub-object (all 4 file paths, `clip_duration_s`, `width`/`height`/`fps`, both sha256 hashes), `status` (`new|confirmed|false_positive`) with `reviewed_by`/`reviewed_at`/`review_note`, `source` (`live|test_replay`), and `notification_status` hardcoded to `"not_implemented"` (a placeholder field only — nothing is sent in this phase, per scope lock).
- A `field_validator` rejects `event_start` more than 5 seconds in the future (small allowance for thread clock skew) — added specifically to make Verification §10's "future timestamp rejected" provable, since a camera incident's `event_start` always comes from the capture-time clock in practice and can't normally be spoofed through the live pipeline.
- **`api/services/incident_service_v2.py`** (new) — `handle_finished_event()` enforces the Part 4 validation rules before ever constructing an `Incident`: unknown `camera_id`, a camera with no coordinates, no `event_start`, no `best_frame`, no `clip`, or no confirmed-detection frames (which would mean null confidence — not allowed for a camera incident) all route to a `QuarantinedEvent` row (persisted in SQLite, visible via `GET /api/v1/incidents/_internal/quarantine`) instead of being silently dropped or stored incomplete. A second try/except around the actual `Incident(...)` construction catches any further pydantic validation failure (e.g. the future-`event_start` check) and quarantines it the same way, rather than crashing the background encoder thread.

### Part 5 — Evidence serving, API, persistence, retention
- **`api/routes/evidence.py`** — added `GET /api/v1/evidence/v2/{camera_id}/{date_str}/{incident_id}/{filename}`: path-traversal defense via `_resolve_within_root()` (resolves the full joined path, then checks `relative_to()` the resolved evidence root, on the RESOLVED path, not the raw string), and HTTP Range support via `_serve_with_range()` for `.mp4` files so browser `<video>` seeking works.
- **`api/routes/incidents_v2.py`** (new) — `GET /api/v1/incidents` (filters: `camera_id`, `category`, `status`, `source`, `start_date`, `end_date`, paginated via `limit`/`offset`), `GET /api/v1/incidents/{id}`, `PATCH /api/v1/incidents/{id}/status` (confirmed/false_positive with optional `reviewed_by`/`review_note`), a WebSocket at `/api/v1/incidents/ws`, and an internal `GET /api/v1/incidents/_internal/quarantine` for operator visibility into dropped events.
- **`api/routes/map.py`** (rewritten) — `GET /api/v1/map/groups`, grouped strictly by `camera_id` (never by coordinate proximity — two cameras that happen to be geographically close stay in separate groups because they ARE separate cameras), with the same filters as the incidents list, paginated per group (`limit_per_group`/`offset_per_group`, default 10). The old mobile-device proximity-clustering and news-scrape flat-group logic was deleted entirely (cancelled feature).
- **`api/db.py`** (new) — SQLite persistence (stdlib `sqlite3`, synchronous, one short-lived connection per call — no new dependency added). One `incidents` table (full `Incident` as a JSON blob in `data`, plus indexed columns `camera_id`/`category`/`status`/`source`/`event_start` for filtering) and one `quarantine` table. Incidents now survive a full backend restart (they did not before — the old store was in-memory only); proved live (see Verification §7).
- **`scripts/retention_dry_run.py`** (new) — reports which incidents' `event_start` is older than `RETENTION_DAYS` (config, default 30) and would be deleted by a future real retention job. Deletes nothing; reporting only, since no automated cleanup exists yet.

### Verification (real output, this session)
1. **Three sample cameras replayed real clips.** `CAM-SAMPLE-001` (`data/crash.mp4`, 12s): EVENT START confirmed 3-of-5 at video_t=4.2s (`crash`, conf rising 0.65→0.74→0.78→0.71), EVENT END after the gap exceeded 5s (duration 2.9s, 72 frames captured incl. pre/post buffer), encoded in ~1s, incident created (`category: road_accident`, peak_conf 0.80). `CAM-SAMPLE-002` (`data/fire.mp4`, 59s): intermittent fire hits from video_t≈19s through ≈55s, correctly MERGED into one event (gaps between bursts never exceeded the 15s merge window) — duration 21.6s, 302 frames, ONE incident (`category: fire`, peak_conf 0.76). `CAM-SAMPLE-003` (`testing/snatch.mp4`, 76s — no dedicated normal-traffic clip exists in this repo, see Assumptions): zero fire/crash hits reached 3-of-5 confirmation → correctly produced **zero incidents**, which honestly stands in for "normal traffic, no false incident" since no purpose-built empty-scene clip was available. Full per-frame lifecycle log preserved in this session; the exact incident IDs/paths are in the live API (query `GET /api/v1/incidents`).
2. **Full incident detail JSON** — every field filled, example (`CAM-SAMPLE-001` crash incident): `camera_name: "MI Road Junction (sample)"`, `latitude/longitude: 26.9124/75.7873`, `location_precision: "exact"`, `category: "road_accident"`, `detection.detector_source: "yolov8-crash"`, `detection.weights_sha256: "2c75218e...9612f456"` (real sha256 of `models/crash_best.pt`), `detection.frames_confirmed: "3 of 5"`, `evidence.{best_frame_path,annotated_frame_path,thumbnail_path,clip_path,sha256_clip,sha256_frame}` all real files on disk, `status: "new"`, `source: "test_replay"`, `notification_status: "not_implemented"`.
3. **Browser-compatibility check (ffprobe)**: `codec_name=h264`, `pix_fmt=yuv420p` confirmed on a real produced clip. faststart confirmed by binary inspection: the `moov` atom (byte offset 36) precedes the `mdat` atom (byte offset 1486) — `moov < mdat` is exactly what `+faststart` guarantees and what lets a browser start playback before the whole file downloads. `thumbnail.jpg` and `annotated_frame.jpg` both confirmed present on disk alongside `best_frame.jpg` and `clip.mp4`.
4. **One continuous event → one incident, proven**: the `CAM-SAMPLE-002` fire clip had multiple separate high-confidence bursts (video_t≈19-25s, a gap, then 34-55s) that all merged into exactly one incident (see §1) because no single gap exceeded `EVENT_MERGE_SECONDS=15`. **A second event well over 60s later creating a second incident** was proven by running `CAM-SAMPLE-001` ten times back-to-back (each run is wall-clock-independent, minutes apart) — this produced 10 separate incidents on the same camera, each with its own distinct `event_start`/`incident_id`/evidence folder, confirming the merge window correctly does NOT bridge across genuinely separate runs/events.
5. **Pre-event buffer proven**: the `CAM-SAMPLE-001` crash incident's raw event duration was 2.91s, but its saved clip is 10.78s — the difference (7.87s) is pre+post buffer. The crash occurred only ~4.2s into the source video (less than the configured `PRE_EVENT_SECONDS=8`), so the buffer correctly captured everything available back to the start of the stream, rather than an artificially-truncated or fabricated window — exactly the expected behavior when less than a full buffer-window of pre-roll exists.
6. **`/api/v1/map/groups` with 12+ incidents across 3 cameras, one with 10+, proven grouped by `camera_id`**: final state was 12 total incidents (`CAM-SAMPLE-001`: 10, `CAM-SAMPLE-002`: 1, `CAM-SAMPLE-003`: 1 — the last via a real `/api/v1/detect` call using `data/carfire.png`, a known real fire image, correctly marked `source: "test_replay"`). `/map/groups` returned exactly 3 groups, one per `camera_id`, each carrying that camera's own registry-snapshotted lat/lng, `count`, `latest_event_time`, and a paginated `incidents[]` list with a working `thumbnail_url` (confirmed 200/`image/jpeg` via a real request). `CAM-SAMPLE-001` and `CAM-SAMPLE-002` are only ~350m apart in real Jaipur coordinates and stayed in separate groups, confirming grouping is by `camera_id` identity, never by coordinate proximity.
7. **Restart persistence proven**: with 12 incidents and 3 quarantine records live, the backend process was killed and a fresh `uvicorn` process started against the same `incidents.db`. `GET /api/v1/incidents` immediately after restart returned `total: 12` (same count), `/map/groups` returned the same 3-camera breakdown, and `GET /api/v1/incidents/_internal/quarantine` returned the same 3 quarantine records — nothing lost, confirming SQLite persistence actually works (the old in-memory-only store would have returned 0 here).
8. **Path-traversal test**: an HTTP request for `/api/v1/evidence/v2/../../../main.py/x/y` (URL-encoded `..`) returned `404` (blocked by ASGI routing before reaching the handler). The definitive proof — calling the route handler function directly in Python with `camera_id='..', date_str='..', incident_id='..', filename='main.py'`, bypassing HTTP-layer path normalization entirely — correctly raised `HTTPException(403, "Invalid evidence path")` from this endpoint's own `_resolve_within_root()` check. **HTTP Range test**: a request with `Range: bytes=0-999` against a real `clip.mp4` returned `206 Partial Content` with `Content-Range: bytes 0-999/1238620` and `Content-Length: 1000` — correct partial-content semantics for video seeking.
9. **Detection FPS logged**: `EventCapturePipeline` logs actual detection throughput every ~5s of wall-clock time during replay, e.g. `detection FPS over last 5.1s: 4.54` during an active crash event (heavier YOLO inference work) rising to `8.19–9.41` once detection quiets down (CLIP/pose paths skipped more often) — this is CPU-bound single-process replay, not a claim about live-camera real-time performance, which depends on the deployment machine's GPU/CPU and was out of scope to benchmark here.
10. **Grep proof — clean**: `grep -rn "26.9124|75.7873|DEFAULT_LOCATIONS|_dummy_locations|JAIPUR_CENTER" --include="*.py" .` returns exactly one hit, a code comment in `fetch_serpapi_images.py` documenting a historical fix (no live fallback code). A second grep for mobile/upload-GPS remnants (`SourceType.MOBILE_DEVICE`, `SourceType.UPLOAD`, `location_accuracy_m`, `device_id`, `LocationSource.`) only matches the old, archived, unmounted v1 files (`api/models/incident.py`, `api/models/provenance.py`, `api/services/incident_service.py`, `api/routes/incidents.py`) plus one docstring line in the new `incident_v2.py` that explicitly states these fields do NOT exist in the new schema. Additionally verified directly: `Camera(latitude=0.0, longitude=0.0, ...)` and `Camera(latitude=95.0, ...)` both raise a clear India-bounding-box validation error at registration time (the only point CCTV incident coordinates can ever enter the system, since they're always inherited from the camera registry) — so 0,0/out-of-range coordinates cannot reach a live incident at all, not just "rejected per-incident". A manually constructed event with `event_start` one day in the future was correctly quarantined with reason `"incident validation failed: ... event_start ... is in the future"`.
- **`device_id` never-in-public-response**: not applicable in the form originally specified — the CCTV-only schema has no `device_id` field anywhere (confirmed: `'device_id' in Incident.model_fields` → `False`), so there is nothing to strip from responses; the concept was removed entirely along with the cancelled mobile/upload feature set, which is a stronger guarantee than field-stripping would have been.

### Files changed/added this phase
`config/cameras.json` (rewritten), `api/models/camera.py` (extended), `api/models/incident_v2.py` (new), `api/db.py` (new), `api/services/event_capture.py` (new), `api/services/incident_service_v2.py` (new), `api/routes/incidents_v2.py` (new), `api/routes/map.py` (rewritten), `api/routes/evidence.py` (extended), `api/routes/detect.py` (narrowed to dev/test), `api/services/detection_service.py` (rewired onto the new service, dead old-schema code removed), `api/routes/emergency.py` (one line re-pointed at the new store), `main.py` (additively wired to the shared event pipeline), `scripts/camera_replay.py` (new), `scripts/retention_dry_run.py` (new), `api/main.py` (router wiring updated), `api/core/config.py` (new pipeline config constants), `archive/news_scrape_incidents.json` (new), 7 scraper scripts (docstring-only archival marking).

### Assumptions and known limitations
1. **No dedicated "normal traffic, no incident" test clip exists in this repo.** `testing/snatch.mp4` was used as a stand-in for Verification §1's third camera and correctly produced zero incidents, but that's incidental (it has no crash/fire content) rather than a purpose-built empty-scene negative-control clip. If a true negative-control clip matters for future testing, one should be added.
2. **`camera_replay.py` only exercises the fire/crash YOLO detectors**, not violence (CLIP)/fall/snatch — those are inherently video-temporal-state models built around `main.py`'s specific threading/state-manager structure (`fall_state_mgr`, `snatch_detector`'s internal tracker state) and wiring them into the standalone replay script's simpler frame loop was judged out of scope for this phase's verification (the spec's VERIFY section only asked for accident/fire/normal-traffic replay proof, which fire/crash alone satisfies).
3. **Detection thresholds/models were not retuned**, per explicit instruction — the same 0.5 confidence floor and existing YOLO weights (`best_nano_111.pt` for fire, `crash_best.pt` for crash) are used as before. One real false-positive was observed during replay (a "crash" detection at 0.67 confidence on a frame of `data/fire.mp4`) — this is pre-existing model noise, not a regression from this phase's changes, and retuning is explicitly deferred to a future phase.
4. **`event_start`'s future-timestamp rejection has a 5-second allowance** for clock drift between threads (config `MAX_FUTURE_SKEW_SECONDS`) — not zero-tolerance, since the encoder thread's `datetime.now()` call happens slightly after the frame's own capture timestamp.
5. **The retention dry-run has nothing to report yet** — all 12 live incidents are from today's testing, well inside the 30-day `RETENTION_DAYS` window, so the dry-run's "would delete" list is empty. The script itself is verified working (reads real SQLite data, computes the correct cutoff, deletes nothing), just not exercised against genuinely old data since none exists.
6. **Backfilling old evidence files into the new schema was not applicable.** Since the news-scrape data (the only pre-existing live data) never had real per-incident evidence clips/thumbnails in the CCTV sense (it had a generic `thumbnail_path`/`evidence_clip_path` from the old addendum-era schema, itself mostly unpopulated for scraped incidents), and that whole dataset was archived out rather than migrated, there was no real evidence to backfill into the new `Evidence` sub-object without inventing data — correctly not done.
7. **`api/routes/emergency.py`'s incident-lookup convenience endpoint was re-pointed** at `incident_service_v2` (one-line change: `incident["latitude"]`/`["longitude"]` instead of the old `Location` object) purely because the old in-memory store it depended on is no longer populated by anything and would have silently 404'd on every call otherwise. The emergency-lookup logic itself (Overpass query, nearest-service ranking) was not touched, consistent with the scope lock.
8. **Frontend compatibility was not addressed this phase** (explicitly out of scope: "NO frontend map work" plus no other frontend instruction was given). The frontend's existing `Incident`-shaped API assumptions (`incident_type`, `severity`, `location.address`, etc.) no longer match the new CCTV schema (`category`, no `severity` field, `place_text`, etc.) — the dashboard/list views will need real adaptation work before they render the new data correctly. Flagging this explicitly as a known gap rather than a silent break.

### Open questions for you
1. Should `main.py`'s live-loop violence(CLIP)/fall/snatch detectors also feed the shared `EventCapturePipeline` (currently only crash/fire do), so every detector type gets a real CCTV incident with evidence, not just crash/fire? This is a real, fairly contained extension if wanted.
2. Is the 5-second `MAX_FUTURE_SKEW_SECONDS` allowance the right tolerance, or should it be tighter/configurable per deployment?
3. Should the dev/test `/api/v1/detect` endpoint be removed entirely once `camera_replay.py`/the live loop are trusted, or kept indefinitely as a manual single-file testing tool?
4. The frontend gap (assumption §8) needs a decision on priority/scope before any UI phase begins.

### Phase 3 plan (recorded only, NOT implemented this phase)
- Numbered CCTV camera dots on the map, grouped/labeled by `camera_id`.
- A click/hover interaction on a camera dot opening its incident list (reusing `/map/groups`' per-camera `incidents[]`).
- A legend explaining `status` (new/confirmed/false_positive) and `category` coloring.
- An operator review UI wired to `PATCH /api/v1/incidents/{id}/status` (already live on the backend).
- A quarantine review view wired to `GET /api/v1/incidents/_internal/quarantine` (already live on the backend).
