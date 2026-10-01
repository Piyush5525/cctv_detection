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
  (`settings.yaml`, env vars) and require careful deployment-specific
  validation. The demo defaults are not optimised for any real site.

## 📹 Footage & Camera Placement

- **Replayed sample footage.** Most incidents shown in the demo are from
  pre-recorded video files (`data/crash.mp4`, `data/fire.mp4`) replayed
  through the same detection pipeline that processes live feeds. These
  are labelled with a **"Recorded footage replay"** badge.

- **Simulated placement.** Camera locations on the map correspond to
  registered entries in `config/cameras.json`. Unless marked as
  `"location_basis": "real_installation"`, the GPS coordinates are
  simulated for demo purposes and labelled as **"Simulated placement."**

- **Demo phone camera.** Any phone used as a camera source is labelled
  with a **"Demo phone camera"** badge and a teal ring on the map.
  It uses the phone's HTTP video stream over a local hotspot —
  this is not a production-grade camera installation.

## 🧑‍💻 Human Confirmation

- **No autonomous action.** Every detected incident requires a human
  operator to review the evidence (clip, best frame, detection
  metadata) and explicitly confirm or dismiss it via the dashboard
  or Telegram callback buttons.

- **Notifications are not a substitute for emergency response.**
  The system's role is to surface potential incidents faster than
  manual monitoring — the decision to act is always a human's.

## 🛡️ Demo Mode & Safety

- **Demo mode is the default.** `DEMO_MODE=true` is set in `.env`
  and enforced by `api/services/safety_guard.py`. When active:
  - Voice calls go **only** to the explicitly configured
    `DEMO_PHONE_NUMBER`.
  - Telegram messages go **only** to the `TELEGRAM_CHAT_ID_ALLOWLIST`.
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
