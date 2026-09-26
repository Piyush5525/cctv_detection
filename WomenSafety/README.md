# Table of Contents

[Introduction](#introduction)

[Setup](#setup)

[How to Run](#howtorun)

[Live Camera Feed (Phone as IP Camera)](#livecamera)

[Fall Detection](#falldetection)

[Telegram & Call Alerts](#alerts)

[Resutls](#results)

[Further Work](#work)
<a name="introduction"/>

# Introduction

This repo presents code for Deep Learning based algorithm for
**detecting violence** in indoor or outdoor environments. The algorithm can
detect following scenarios with high accuracy: fight, fire, car crash and even
more.

To detect other scenarios you have to add **descriptive text label** of a
scenario in `settings.yaml` file under `labels` key. At this moment model can
detect 16`+1` scenarios, where one is default `Unknown` label. You can change,
add or remove labels according to your use case. The model is trained on wide
variety of data. The task for the model at training was to predict similar
vectors for image and text that describes well a scene on the image. Thus model
can generalize well on other scenarios too if you provide proper textual
information about a scene of interest.
<a name="setup"/>

# Setup

These steps set up an isolated Python virtual environment so the project's
dependencies don't clash with anything else on your machine. Python 3.8 or
3.9 is recommended, since some of the pinned dependencies (e.g. `torch==1.7.1`)
are old.

**1. Clone the repo and open it in a terminal.**

**2. Create and activate a virtual environment.**

Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
If PowerShell blocks the activation script, run this once (in an admin
PowerShell) and try again: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

macOS / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies.**
```bash
pip install -r requirements.txt
```
> Note: `pyheif` (used only for optional HEIC image support) can be tricky to
> install on Windows because it needs the native `libheif` library. If
> `pip install` fails on it and you don't need HEIC images, just delete the
> `pyheif==0.5.1` and `whatimage==0.0.3` lines from `requirements.txt` and
> re-run the install — nothing else in the repo depends on them.

<a name="howtorun"/>

# How to Run

To test the model on a single image:
`python run.py --image-path ./data/7.jpg`

Or you can test it through the web app:
`streamlit run app.py`

Or run it live on a video/camera feed (see below for using your phone as the
camera):
`python main.py`

Or you can see the example code in `tutorial.ipynb` jupyter notebook

Or incorporate this model in your project using this code:

```python
from model import Model
import cv2

model = Model()
image = cv2.imread('./your_image.jpg')
image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
label = model.predict(image=image)['label']
print('Image label is: ', label)
```

<a name="livecamera"/>

# Live Camera Feed (Phone as IP Camera)

`main.py` runs the detection model continuously on a live video stream and
shows the predicted label on-screen in real time. By default it uses your
laptop's webcam (`CAMERA_SOURCE` unset, or `0`), but you can point it at any
video source that OpenCV can open, including a phone streaming over Wi-Fi as
an IP camera. The detection model itself always runs on the laptop — the
phone is only used as the camera source.

**1. Turn your phone into an IP camera.**

- Android: install an app such as **IP Webcam** from the Play Store, open it,
  and tap **Start server**. It will show a URL like
  `http://10.232.61.112:8080` — the video stream itself is at
  `http://10.232.61.112:8080/video`.
- Make sure your phone and laptop are connected to the **same Wi-Fi network**.

**2. Set the `CAMERA_SOURCE` environment variable to your phone's stream URL
and run `main.py`.**

Windows (PowerShell):
```powershell
$env:CAMERA_SOURCE="http://10.232.61.112:8080/video"
python main.py
```

macOS / Linux:
```bash
export CAMERA_SOURCE="http://10.232.61.112:8080/video"
python main.py
```

Replace the IP address with whatever your phone's IP camera app shows —
it changes whenever your phone reconnects to Wi-Fi. A window will open on
the laptop showing the live feed from your phone with the model's predicted
label (e.g. `fight on a street`, `fire on a street`, `Unknown`) and confidence
overlaid on each frame. Press `q` in that window to stop.

**Rotation:** phone IP camera apps stream in the sensor's native orientation
regardless of how you're holding the phone, so `main.py` rotates the feed
90° clockwise by default (`CAMERA_ROTATE` defaults to `90`). If your feed
still looks rotated, override it (accepted values: `0`, `90`, `-90`/`270`,
`180` — try `-90` if `90` over-rotates it):

```powershell
$env:CAMERA_SOURCE="http://10.232.61.112:8080/video"
$env:CAMERA_ROTATE="-90"
python main.py
```

**Performance / lag:** detection (CLIP + the fall-detection pose model, both
CPU-bound) runs on a background thread, separate from the thread that
displays the video — so the picture itself stays smooth and never waits on
inference; only the overlaid label/boxes lag behind by a frame or two on a
slow CPU. The working frame (used for both detection and what's displayed)
is also downscaled to `DETECT_WIDTH` pixels wide (default `640`) before
processing, since inference on a phone's full 1080p+ stream is much slower
per frame. If you have a beefier CPU/GPU and want higher-res display, raise
or disable it:

```powershell
$env:DETECT_WIDTH="0"   # disable downscaling, use native camera resolution
```

<a name="falldetection"/>

# Fall Detection

`main.py` also runs a **fall / collapse detection** pipeline alongside the
CLIP violence detector, on the same live feed, at the same time. This part
is ported from [vjn6805/Fall-Detection-Model](https://github.com/vjn6805/Fall-Detection-Model)
— it's a completely different approach from the CLIP scene classifier above:
a pose-based temporal state machine rather than a single-frame label
prediction. It lives in the [`fall_detection/`](fall_detection) package.

**Pipeline** (unchanged from the source repo):

```
frame → YOLOv8n-pose (person + 17 keypoints) → ByteTrack (stable per-person ID)
      → per-person history buffer (~3s rolling window)
      → FallDetector: temporal state machine over posture/transition/persistence/motion
      → RiskEngine: post-fall inactivity scoring → "potential health emergency"
      → overlay: skeleton, per-person state label, colored box, red banner on emergency
```

**Logic, in detail** (from `fall_detection/fall_detector.py`):

Every tracked person gets their own independent state machine with states
`NORMAL → POSSIBLE_FALL → FALL_CONFIRMED → POST_FALL_MONITORING → RECOVERED`
(plus `UNKNOWN_LOW_POSTURE` for someone already lying down when they enter
frame, so it's never miscounted as a fall). Each frame, a `fall_score` is
computed as a weighted blend of 4 signals:

- **posture_score** (35%) — how horizontal the torso currently is (torso
  angle from vertical + bounding-box aspect ratio)
- **transition_score** (30%) — whether an upright→horizontal transition was
  just observed, *and* whether it was fast (a real fall, <0.5s) vs. slow
  (sitting/lying down on purpose, gets penalized)
- **persistence_score** (20%) — how much of the recent window has been spent
  in a low/horizontal posture
- **motion_score** (15%) — stillness after the posture change (a collapse
  stays still; a stumble-and-recover moves)

A fall only moves past `POSSIBLE_FALL` into `FALL_CONFIRMED` if it persists
for `confirm_fall_seconds` and the pose is well-observed enough (an
`observability` gate based on keypoint confidence prevents confirming a fall
from a blurry/occluded pose). A separate `RiskEngine` only activates after
`FALL_CONFIRMED`, and raises `POTENTIAL_HEALTH_EMERGENCY` if the person then
stays down, inactive, and shows no recovery motion for long enough — a fall
alone is not treated as an emergency.

All thresholds live in [`fall_detection/config.yaml`](fall_detection/config.yaml),
copied unchanged from the source repo's `config.yaml` (only the
incident-database/evidence-recording/dashboard sections were dropped — those
serve the source repo's standalone CCTV archival tool, which isn't part of
this live-feed script).

**What was not carried over, and why:** the source repo is a full CCTV
health-emergency system — it also includes a SQLite incident store, a
pre/post-event video evidence recorder, a Flask review dashboard, and a
multi-camera registry. Only the detection core (`detector.py`,
`state.py`, `fall_detector.py`, `risk_engine.py`, `visualization.py`) was
ported, since the ask here was to add fall detection to *this* live feed,
not to run a second archival system alongside it. Bringing the rest over is
possible later if you want persisted incident history.

**Testing, in the source repo:** there's no pytest unit-test suite — it's
tested empirically. `tools/evaluate.py` runs the pipeline against labeled
videos (a `.csv` of `frame,event` ground truth per clip — see
`tools/label_format.md`) and reports precision/recall on fall and emergency
detection; `tools/sweep.py` sweeps threshold values against those same
labeled videos to tune `config.yaml`; `benchmark.py` is a plain latency/FPS
smoke test for the YOLO model on CPU. None of that harness was ported here
(it operates on the source repo's own labeled video set) — if you want to
validate detection quality on your own footage, the same approach (label a
video, run it through the state machine, compare transitions) is the
pattern to follow.

**Toggle / tuning:**

- Set `FALL_DETECTION=0` to disable it and run violence detection only (e.g.
  if `ultralytics`/pose model download isn't available on a machine):
  ```powershell
  $env:CAMERA_SOURCE="http://10.232.61.112:8080/video"
  $env:FALL_DETECTION="0"
  python main.py
  ```
- The first run downloads `yolov8n-pose.pt` (~6.5MB) automatically via
  `ultralytics` — needs internet access once.
- If fall detection fails to load for any reason (no internet, missing
  dependency), `main.py` logs a warning and falls back to violence-detection-only
  rather than crashing.

<a name="alerts"/>

# Telegram & Call Alerts

`main.py` sends a **Telegram message + photo** and places an **AI voice call**
whenever violence or a fall/health emergency is detected. This is ported
unchanged from another project's `Telebot_Alert.py` and `Call_Alert.py` —
same cooldown logic, same message flow, nothing about those two files was
modified.

**What triggers an alert:**

| Trigger | Source | `reason` (cooldown key) |
|---|---|---|
| CLIP scene label looks violent (`violence`/`fight`/`fire`/`crash`) | violence detector | `violence` |
| A tracked person's fall state reaches `FALL_CONFIRMED` | fall detection | `fall_detected` |
| A tracked person's risk state reaches `POTENTIAL_HEALTH_EMERGENCY` | fall detection | `health_emergency` |

Each `reason` has its own independent cooldown (60s for Telegram, 120s for
the call), so one alert type firing repeatedly can't block a different kind
of alert — exactly as in the reference implementation.

**Setup — create a `.env` file** in the project root (already gitignored,
never commit it):

```env
# Telegram bot (Telebot_Alert.py)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Omnidimension call bot (Call_Alert.py)
OMNIDIM_API_KEY=your_omnidim_api_key
OMNIDIM_AGENT_ID=your_agent_id
OMNIDIM_FROM_NUMBER_ID=your_from_number_id
ALERT_PHONE_NUMBER=+91xxxxxxxxxx
```

- Telegram: create a bot via [@BotFather](https://t.me/BotFather) for the
  token, and message [@userinfobot](https://t.me/userinfobot) (or your bot
  itself) to get your chat ID.
- Omnidimension: get `OMNIDIM_API_KEY` from
  [omnidim.io/api-management](https://omnidim.io/api-management), and
  `OMNIDIM_AGENT_ID`/`OMNIDIM_FROM_NUMBER_ID` from the voice agent and phone
  number you've set up on your Omnidimension account.

If any of these env vars are missing, the corresponding alert is skipped
with a console message (`Telegram alert skipped: ...` / `Call alert
skipped: ...`) — the detection pipeline itself keeps running either way.

> Security note: `.env` holds live credentials (bot token, API key, phone
> number). It's gitignored so `git add`/commits won't pick it up — don't
> paste its contents anywhere public, and rotate any of these values if they
> ever do leak.

<a name="results"></a>

# Results

Below are the resulting videos and images. I used the model to make predictions
on each frame of the videos and print model's predictions on the left side of
frame of saved videos. In case of images, titles are model's predictions. You
can find code that produces that result in `tutorial.ipynb` jupyter notebook.

![Result video](./results/output_fire.gif)

![Result video](./results/output_fight.gif)

### Result Images

![Result image](./results/3.jpg)
![Result image](./results/9.jpg)
![Result image](./results/2.jpg)
![Result image](./results/4.jpg)
![Result image](./results/10.jpg)
![Result image](./results/7.jpg)
![Result image](./results/0.jpg)

<a name="work"></a>

# Further Work

Needs further work for enhancements like: Batch processing support for speedup, return of
multiple suggestions, threshold fine-tuning for specific data, ect.

cd WomenSafety
pip install -r requirements.txt
python run_dashboard.py --mode all

in the env file 

Webcam (built-in):
CAMERA_SOURCE=0
(Use 1, 2, etc. if you have multiple cameras)

IP camera (RTSP - most common for CCTV):
CAMERA_SOURCE=rtsp://username:password@192.168.1.100:554/stream1

IP camera (HTTP/MJPEG stream):
CAMERA_SOURCE=http://192.168.1.100:8080/video

Video file:
CAMERA_SOURCE=data/crash.mp4

to enalable disable the detection model set 0/1 in the .env file
0- to dialble detection pipleline in front of certain model
1- to enable detection pipeline for the certain model
