# Limitations & Honest Disclosure

> This document exists to give judges, reviewers, and operators an
> accurate picture of what this system can and cannot do.

---

## 🔬 Detection Models

- **Pre-trained open-source models.** The fire and crash detectors use
  YOLOv8 checkpoints trained on public datasets, not on local Jaipur
  road/building footage. Detection accuracy on local scenes has not
  been validated with a labelled test set from the deployment area.

- **No local fine-tuning.** We have not collected, labelled, or trained
  on any data from the cameras shown in the demo. Real deployment
  would require a local validation dataset and threshold calibration.

- **Configurable thresholds.** The confidence thresholds that determine
  when an event becomes an incident are operator-configurable
  (env vars / `.env`) and require careful deployment-specific
  validation. The demo defaults are not optimised for any real site.

- **Confidence floor 0.5 in demo mode.** `FIRE_CRASH_CONFIDENCE_FLOOR`
  defaults to 0.5 (it was 0.0 before the 2026-10-01 fix pass, which let
  0.3-0.4 confidence detections become incidents). Detections below the
  floor are dropped before an event can start. 0.5 is the value the eval
  harness uses; it has not been tuned on local footage, and a higher floor
  trades missed incidents for fewer false alarms.

## 📹 Footage & Camera Placement

- **Replayed sample footage.** Incidents shown in the demo from
  pre-recorded video files (`data/crash.mp4`, `data/fire.mp4`, the
  showcase set, and the "Trigger test incident" control) are stored with
  `source=test_replay` and labelled **"Recorded footage replay"** - never
  "Live detection". Sample-file camera workers are off by default. The
  trigger control is additionally marked "synthetic demo trigger" in the
  evidence note: it uses a stored frame, not a live stream.

- **Simulated placement.** Camera locations on the map correspond to
  registered entries in `config/cameras.json`. All
  sample cameras are `"location_basis": "simulated_placement"` (the GPS
  coordinates are demo placements, not real installations) and are
  labelled **"Simulated placement"** in the hover popup and detail panel.
  Only phone cameras are `real_installation` (the phone really is where
  it is registered).

- **Demo phone camera.** Any phone used as a camera source is labelled
  with a **"Demo phone camera"** badge and a teal ring on the map.
  It uses the phone's HTTP video stream over a local hotspot —
  this is not a production-grade camera installation.

## 🧑‍💻 Human Confirmation

- **Human review, with an automatic escalation call.** A detected
  incident is shown for an operator to review (clip, best frame,
  detection metadata) and to **Acknowledge** (stops the automatic call)
  or mark **False alarm** / **False positive**, on the dashboard or via
  the Telegram buttons. If nobody acts, the system places ONE call to
  the allowlisted demo number after the escalation delay (20 s in demo
  mode, immediately for confidence >= 0.6, at most 5 calls per hour).
  Outbound Telegram/call is rate-limited per camera and category
  (`DEMO_COOLDOWN_S`, default 15 s); suppressed alerts are recorded in
  the timeline and the incident itself is still created.

- **Notifications are not a substitute for emergency response.**
  The system's role is to surface potential incidents faster than
  manual monitoring — the decision to act is always a human's.

## 🛡️ Demo Mode & Safety

- **Demo mode is the default.** `DEMO_MODE` defaults to true in
  `api/core/config.py` (it is not set in `.env`) and is enforced by
  `api/services/safety_guard.py`. `ALERTS_ENABLED` defaults to false.
  When alerts are enabled:
  - Voice calls go **only** to the explicitly configured
    `DEMO_PHONE_NUMBER`; if it is unset the call channel is blocked.
  - Telegram messages go **only** to `TELEGRAM_CHAT_ID_ALLOWLIST`, or
    failing that `TELEGRAM_CHAT_ID`; if neither is set the Telegram
    channel is blocked (it never falls back to "allow any chat").
  - **No real emergency service number is ever dialled**, regardless
    of what the nearby-services lookup discovers.

- **Discovered service numbers are display only.** The dispatch plan
  shows the nearest hospital, police station, and fire station with
  their publicly listed phone numbers. These numbers are **never
  auto-dialled** — they exist as lookup data for the operator's
  reference.

- **Hard emergency-number block.** Known emergency numbers (100, 101,
  102, 108, 112, etc.) are blocked at the safety-guard level and
  cannot be dialled by the system under any configuration.

## 📊 Dashboard Scope

- **Single working page.** Only the incident map is exposed; the older
  Dashboard / Incidents / Analytics / Evidence / Settings pages called
  endpoints that no longer exist and were hidden in the 2026-10-01 fix
  pass.

- **Local-only API.** The API binds 127.0.0.1, allows only the
  dashboard origins, and `/demo/*`, PATCH and DELETE routes need the
  `X-Demo-Token` header (`DEMO_TOKEN`). This is a demo guard, not user
  authentication.

- **No real-time video analytics dashboard.** The live camera panel
  shows MJPEG snapshots at ≤8 FPS, not a full video analytics view.
  Detection runs server-side; the browser displays results, not
  inference.

- **Offline fallback.** If Mapbox tiles or the Directions API are
  unreachable, the map shows camera dots on a plain dark background
  with straight-line distance estimates instead of road routes.
  This fallback is explicitly labelled.

## 🚀 Next Steps (Post-Hackathon)

| Area | Action |
|------|--------|
| Data | Collect and label a local validation dataset from actual camera feeds |
| Models | Fine-tune or evaluate on local data; publish per-site accuracy metrics |
| Thresholds | Run threshold sweep against local validation set; document chosen operating point |
| Field testing | Controlled pilot at one intersection with operator feedback loop |
| Operator UX | Multi-user auth, audit log, shift handoff, alert routing rules |
| Credentials | Secrets in vault (not `.env`), TLS everywhere, RBAC on API |
| Production | Async DB driver if scaling beyond single process; object storage for evidence |
| Compliance | Privacy impact assessment, data retention policy, camera signage |
