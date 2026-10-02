# Live test checklist (things only you can do)

All commands are PowerShell. Nothing here was run against your phones, your Telegram chat or your demo phone number during the build; everything below is what to run and what you should see. Run from the app folder:

```powershell
cd D:\Projects\Detection-Models\WomenSafety
```

## READ FIRST: three things that can surprise you

1. **`.env` currently has `ALERTS_ENABLED=true` and `DEMO_MODE=true`.** With alerts on, any trigger sends a real Telegram message to your demo chat, and fire/crash can place a real call to `DEMO_PHONE_NUMBER`. Calls are capped at `MAX_CALLS_PER_HOUR` (5, shared by auto-calls and Escalate now). Every real call you test uses one. Use DRY RUN (below) whenever you do not need to hear the phone ring.
2. **Fire and crash triggers call immediately, so Acknowledge cannot stop them.** The stored-sample triggers score about 0.68 (fire) and 0.80 (crash), which is at or above `CALL_MIN_CONFIDENCE` (0.6): the call is scheduled with zero delay. To test the Acknowledge / False alarm / no-press paths, start the API with `$env:CALL_MIN_CONFIDENCE = '0.99'` (see section 2); then the 20 s escalation delay applies and the buttons can win the race.
3. **Fall, Violence and Snatching triggers are disabled** (the real detectors did not fire on the three provided clips; see `docs/DEMO_CLIPS_CHECK.md`). In the Demo panel they show "unavailable" with the reason. If you refilm, replace the clip in `data/demo/`, run `python scripts/demo_clips_check.py`, and a category is enabled only if its detector fired.

A token helper used below (reads `DEMO_TOKEN` from `.env`, never prints it):

```powershell
$tok = ((Get-Content .env | Where-Object { $_ -match '^DEMO_TOKEN=' }) -replace '^DEMO_TOKEN=','').Trim()
$hdr = @{ 'X-Demo-Token' = $tok }
```

## 0. Venue pre-check (do this before anyone arrives, and again at the venue)

```powershell
# a) one API instance only
Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object LocalPort, OwningProcess
```
Expect at most one row. If two Python processes serve the dashboard, stop the extra one.

```powershell
# b) network: laptop and both phones on the SAME hotspot/Wi-Fi. Phone IPs change per network: read each from the IP Webcam app,
#    update PHONE_CAM001_URL / PHONE_CAM002_URL in .env, restart the API.
Test-NetConnection <phone-1-ip> -Port 8080
Test-NetConnection <phone-2-ip> -Port 8080
```
Expect `TcpTestSucceeded : True` for both.

```powershell
# c) cameras readable (no address is printed)
python scripts/check_camera.py CAM-001
python scripts/check_camera.py CAM-002
```

```powershell
# d) nearby-services cache is warm for CAM-001 (prints only warm/COLD, no coordinates)
python -c "from api.models.camera import get_camera; from api.services.nearby_services import lookup_cached; c=get_camera('CAM-001'); print('cache warm' if c and c.latitude is not None and lookup_cached(c.latitude, c.longitude) else 'cache COLD or location missing')"
```
Expect `cache warm`. If COLD and you are online, one real lookup happens on the first incident (3 SerpApi calls); offline, the plan shows the services as unavailable. Note: CAM-001, CAM-002 and the MI Road sample camera currently resolve to the same ~100 m cache cell, so CAM-001's coordinates may be a copy of the sample placement: set real `PHONE_CAM001_LAT` / `PHONE_CAM001_LNG` if the phone is somewhere else (a new location needs its own lookup, 3 SerpApi calls).

```powershell
# e) frontend demo token matches the backend one (compares hashes, prints only True/False)
$a = ((Get-Content .env | Where-Object { $_ -match '^DEMO_TOKEN=' }) -replace '^DEMO_TOKEN=','').Trim()
$b = ((Get-Content frontend\.env | Where-Object { $_ -match '^VITE_DEMO_TOKEN=' }) -replace '^VITE_DEMO_TOKEN=','').Trim()
($a -ne '') -and ($a -eq $b)
```
Expect `True`. (If you changed `frontend\.env`, rebuild: `python run_dashboard.py --mode build`.)

```powershell
# f) checks
python scripts/check_demo_clips.py
python -m unittest discover -s tests 2>&1 | Select-Object -Last 4
```
`check_demo_clips.py` reports problems until `data/demo/SOURCES.md` rows are filled (that file is yours to fill). The test suite should end with `OK` (131 tests at the time of writing).

**ALERTS_ENABLED only at start.** Keep `ALERTS_ENABLED=false` in `.env` between rehearsals and enable it only for the API process you start for the demo:

```powershell
$env:ALERTS_ENABLED = 'true'            # real Telegram (and calls) ONLY in this process
python run_dashboard.py --mode api --no-build
```
Open http://localhost:8000/map. To rehearse without any outbound traffic, start with `$env:ALERTS_ENABLED = 'false'` (the timeline then shows `skipped: ALERTS_ENABLED is false`).

## Per-camera detector presets (decide before the demo)

Detectors are chosen per camera (`"detectors"` in `config/cameras.json`, env override `DETECTORS_<CAMERA_ID>`, or the Demo panel toggles, which apply live and are written to the session audit trail). Two presets:

| Preset | Detectors | Use for | Why |
|---|---|---|---|
| **Fire/crash camera** (the default) | fire, crash | the camera pointed at a screen playing the fire/crash sample clips, or any scene where fire or a vehicle crash is the story | the only two detectors that fired on their sample clips; no pose model is loaded, so the least CPU |
| **Action-scene camera** | fall, violence, snatch (optionally with fire and crash off) | a camera filming people acting out a fall, a fight or a snatch | action detectors are EXPERIMENTAL, never auto-call, and **did not fire on the provided clips**, so treat this preset as unproven until a refilmed clip passes `python scripts/demo_clips_check.py` |

Rules of thumb, from measurements and the cross-trigger list in `docs/KNOWN_FALSE_POSITIVES.md`:
- Do not put fire/crash and the action detectors on the same camera for an action scene: fire and crash fired on the fall and snatch clips (people, cars and lighting), so an action scene on a fire/crash camera can raise fire or crash alerts that auto-call. Turn fire and crash OFF on the action-scene camera (Demo panel toggles) or give that camera an action-only list, e.g. `$env:DETECTORS_CAM_002 = 'fall,violence,snatch'` before starting the API.
- Use the action-scene preset on ONE camera only: on this laptop, with two cameras running, the guard throttles the action detectors to roughly 0.6 pose passes per second each, which makes fall and snatch effectively blind.
- Changing a camera's detector list at runtime restarts that camera's action detectors' state (a half-finished fall or approach is forgotten).
- Check the list on the camera tiles (detector chips) or with `Invoke-RestMethod http://localhost:8000/api/v1/cameras/status` (the `detectors` field) before starting.

## 1. Both phones online and /cameras/status

Start IP Webcam on both phones, then:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/cameras/status | Select-Object -ExpandProperty cameras |
  Select-Object camera_id, status, error, effective_fps, last_frame_age_s, detectors | Format-Table -AutoSize
```
Expect for CAM-001 and CAM-002: `status = online`, `error` empty, `effective_fps` around 2-4 once running 10+ seconds, `last_frame_age_s` under 2, `detectors = {fire, crash}`. `offline` plus an error text means the phone, IP or credentials are wrong (the text names the env variable, never its value). The dashboard's Live Cameras panel should show both tiles with their active-detector chips.

## 2. The four Telegram paths on a Crash

Start the API for this test as:

```powershell
$env:ALERTS_ENABLED = 'true'
$env:CALL_MIN_CONFIDENCE = '0.99'       # so the 20 s escalation delay applies and the buttons can act first
python run_dashboard.py --mode api --no-build
```

**Call-cap warning:** paths B and C below place a REAL call to your demo phone each time (5 per hour in total, after which calls are refused with `MAX_CALLS_PER_HOUR reached`). To test the buttons without calls, turn on DRY RUN (Demo panel, "Dry run" button, or `Invoke-RestMethod -Method Post http://localhost:8000/api/v1/demo/dry-run -ContentType application/json -Headers $hdr -Body '{"enabled":true}'`): the header shows **DRY RUN**, Telegram stays real, calls are recorded `suppressed: dry run`.

Trigger a crash (Demo panel: Ctrl+Shift+D, pick CAM 001, Crash, "Trigger test incident"; or):

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/demo/trigger -ContentType application/json -Headers $hdr -Body '{"camera_id":"CAM-001","category":"road_accident"}' | Select-Object incident_id, category, source
```
Expect a Telegram photo message "Incident: road_accident ... Peak confidence ... Threshold ..." with buttons **Acknowledge (stops auto-call)**, **False alarm**, **Escalate now**, a location pin, and the nearest services (hospital first, then police station; never a fire station). Do each path with a fresh trigger (wait out the cooldown: 15 s in DEMO_MODE):

| Path | You do | Expect in Telegram | Expect on the dashboard / timeline |
|---|---|---|---|
| A. Acknowledge | press Acknowledge within 20 s | message edited: "Acknowledged by <you> at HH:MM:SS ... - automatic call cancelled"; only False alarm remains | incident status `confirmed`; timeline `operator acknowledged`, `call cancelled`; **no call** |
| B. False alarm | press False alarm within 20 s | "Marked false alarm by ... - automatic call cancelled", no buttons left | status `false_positive`; `call cancelled`; **no call** |
| C. Escalate now | press Escalate now | "Escalate now pressed by ...", then "Call placed at ..." (or "call skipped: suppressed: dry run") | `operator escalate`, then `call sent` (or `call suppressed` with `suppressed: dry run`) |
| D. No press | do nothing for 20 s | "No response - auto-call placed at ..." (or `auto-call skipped: suppressed: dry run`) | `call scheduled`, then `call sent` (or `suppressed`) |

The demo phone should ring within a few seconds for C and D (not in dry run). The call text starts with "This is a test call for the Room 118 demo."

## 3. Experimental categories in dry run

Only possible once a clip's detector fires (see READ FIRST item 3). With DRY RUN on, trigger Fall / Violence / Snatching from the Demo panel. Expect: Telegram caption starts "EXPERIMENTAL detection - verify before acting" with confidence and threshold, buttons Acknowledge / False alarm / Escalate now, timeline `call manual_only` (no automatic call, ever); pressing Escalate now gives `call suppressed: dry run`; dashboard shows the EXPERIMENTAL badge, the signals panel and the primary service (fall: hospital; violence and snatching: police station). Until then the picker shows them "unavailable" with the reason and a trigger attempt returns HTTP 409 with that reason.

## 4. The five-category sequence

```powershell
python scripts/run_demo.py --sequence fire,crash,fall,violence,snatching --delay 25 --dry-run
```
Expect a timestamped timeline: fire and crash created (Telegram sent, call `suppressed`), then fall / violence / snatching either created (if enabled) or `SKIPPED (<reason>)`, then a SUMMARY table; DRY RUN is switched on for the run and restored to its previous state at the end. Add `--camera CAM-002` to use the other phone.

## 5. Screen-in-front-of-phone live detection test (fire / crash only)

Keep `detectors = {fire, crash}` on CAM-001 (the default). Play the **sample clips** `data\fire.mp4` or `data\crash.mp4` full-screen on the laptop (or any monitor), hold the phone steady 20-40 cm from the screen in a dim room, glare off the screen.

```powershell
Start-Process data\fire.mp4        # or data\crash.mp4
Invoke-RestMethod http://localhost:8000/api/v1/cameras/status | Select-Object -ExpandProperty cameras | Select-Object camera_id, status, effective_fps
```
Expect an incident within roughly 5-15 s of a clear fire/crash scene (confirmation needs 3 of 5 sampled frames, about 4 per second), `source = live` (not `test_replay`) in the detail panel with the "Live detection" badge, evidence clip and best frame from the phone's view. Not guaranteed: this was never tested end to end with your phones; a screen shown to a phone loses contrast and adds moiré, and detector confidence may stay under 0.5. If nothing fires within 30 s, use section 7.

## 6. No-internet run

Disconnect the laptop from the internet (keep the local network to the phones, or use the sample cameras only). Start with `$env:ALERTS_ENABLED = 'false'`. Expect: the map falls back to the plain local background within about 8 s (camera positions only, labelled), dispatch plans come from the cache (cache warm required, section 0d) with routes labelled "Straight-line estimate ... Mapbox driving route unavailable", Telegram and calls cannot be sent (with alerts on, the timeline shows `failed` after retries), model weights are local so detection still runs. Reconnect before the real demo.

## 7. If live detection fails (fallback)

Do not claim a live detection. Use the Demo panel: **Trigger test incident** (fire or crash) creates a clearly labelled replay (`source = test_replay`, evidence note "synthetic demo trigger"), or **Load showcase** (needs `demo/showcase.db`, built after you pick candidates). Say it is a replay. **Reset demo** clears everything (the current DB is backed up to `backups\` first).

## Never tested end to end (to rehearse once)

Real phones through the whole chain (stream, detect, Telegram, call), the screen-to-phone test, the no-internet run, Escalate now on a real call, Telegram button presses after an API restart, the DRY RUN header on the projector, and any of Fall / Violence / Snatching live (their detectors did not fire on the provided clips).
