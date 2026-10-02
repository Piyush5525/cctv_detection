# Known cross-triggers on the provided clips (no tuning)

A **cross-trigger** is a detector confirming an event on a clip that was provided for a different class. Source: `docs/DEMO_CLIPS_CHECK.md` (`scripts/demo_clips_check.py`: real detectors, same pipeline as live, video time, current thresholds, one run per clip; the check is deterministic, a repeat gave identical numbers). Tiny sample. Whether each one is a true false alarm is a human call; I only looked at the best-frame thumbnails in `demo/candidates.html`, not at the full clips. No threshold was changed because of any of this.

| # | Detector | Clip (class it was provided for) | Time range (video) | Peak score | Floor | Confirmed |
|---|---|---|---|---|---|---|
| 1 | fire | data/demo/fall.mp4 (fall) | 0.5-5.9 s | 0.66 | 0.5 | 3 of 3 frames |
| 2 | crash | data/demo/fall.mp4 (fall) | 11.2-20.0 s | 0.65 | 0.5 | 5 of 5 frames |
| 3 | crash | data/demo/snatch.mp4 (snatch, 30 s version) | 24.6-28.3 s | 0.62 | 0.5 | 3 of 5 frames |

No action detector (fall, violence, snatch) confirmed an event on any clip, its own or another.

## Near cross-triggers (frames above the floor, but never confirmed, so no event)

| Detector | Clip | Highest single-frame score | Floor |
|---|---|---|---|
| fire | data/demo/violence.mp4 | 0.53 | 0.5 |
| fire | data/demo/snatch.mp4 | 0.54 | 0.5 |
| crash | data/fire.mp4 | 0.48 (under the floor) | 0.5 |

## Why this matters for the demo

- Fire and crash alerts are the only ones that **auto-call**. On a camera that films people (an action scene), fire and crash can fire on cars, lighting or night footage (#1-#3 above). Keep fire and crash off on a camera used for an action scene; see "Per-camera detector presets" in `docs/LIVE_TEST_CHECKLIST.md`.
- Items #1 and #2 are reproducible on the provided `fall.mp4`: do not use that clip on a camera with fire/crash enabled while alerts are on.
- The candidate gallery (`demo/candidates.html`) lists these three as candidates labelled with their clip, so they can be excluded when choosing showcase ids.
