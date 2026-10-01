# Test corpus notes

Ground-truth labels and known behavior for the video clips used in replay/eval testing (`scripts/camera_replay.py`, `scripts/eval_detectors.py`, `scripts/measure_live_loop_fps.py`). Not an exhaustive dataset -- just what exists in this repo (`data/`, `testing/`).

| File | label_class | Registered detector coverage | Notes |
|---|---|---|---|
| `data/crash.mp4` | road_accident / Accident | supported (crash) | Real dashcam/CCTV crash footage. Crash detector reliably hits (peak_conf ~0.55-0.80 across replay runs). |
| `data/fire.mp4` | fire | supported (fire) | Real CCTV fire footage. Fire detector reliably hits (peak_conf ~0.65-0.76). |
| `data/office_fight.mp4` | violence | **not_supported** | No registered detector covers "violence" (only fire/crash are registered -- see `api/services/detector_interface.py`). Correctly reported as `not_supported` by `eval_detectors.py`, never as a miss. |
| `testing/snatch.mp4` | **snatch** | **not_supported** | No registered detector covers "snatching". Correctly reported as `not_supported` by `eval_detectors.py` (which only runs fire/crash and checks `supports_class()` before ever running inference). **However**, this clip is NOT a clean "zero event" clip when run through `main.py`'s LIVE LOOP: the crash detector produces low-confidence false-positive "crash" detections on it (peak_conf observed 0.36, well under the 0.5 floor `scripts/camera_replay.py`/`eval_detectors.py` apply by default), because `main.py`'s live loop currently applies NO confidence floor at all (`settings.FIRE_CRASH_CONFIDENCE_FLOOR` defaults to `0.0`, matching current live behavior -- see CHANGELOG.md's HIGH-priority finding on the eval/live floor inconsistency). Across 3 live-loop runs (Phase 1c follow-up 2), this produced 2-5 "crash" events per 20-30s window, 0-2 of which were confirmed into real (false-positive) incidents. **Kept as evidence, not discarded**: these low-confidence false-positive detections are a real, reproducible example of why the floor inconsistency matters -- the SAME clip is "zero events" through the replay/eval tooling's 0.5 floor, but is NOT zero-events through the live loop's current no-floor behavior.

## Known gap
No clip in this repo is genuinely "normal traffic, no incident of any kind, at any confidence, through any code path" -- `testing/snatch.mp4` was the closest available stand-in and is still not clean under the live loop's current (floor-less) confidence handling. If a true negative-control clip is needed for future measurement, one should be added.
