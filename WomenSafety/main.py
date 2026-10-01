import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
import threading
import time
from datetime import datetime, timezone

import cv2
import yaml
from dotenv import load_dotenv

load_dotenv()

from model import Model
from Telebot_Alert import send_telegram_alert
from Call_Alert import send_call_alert
from snatch_detection.detector import build_snatch_pipeline
from fire_detection.detector import build_fire_pipeline
from crash_detection.detector import build_crash_pipeline
from api_client import api_client, create_incident_from_detection
from api.services.evidence_service import evidence_service
from api.models.camera import get_camera
from api.models.incident_v2 import SourceKind
from api.services.event_capture import EventCapturePipeline
from api.services import incident_service_v2 as svc_v2
from api.services.frame_sampler import RealtimeFrameGate
from api.core.config import settings
from api.core.config_dump import print_effective_config

ROTATE_MAP = {
    '90': cv2.ROTATE_90_CLOCKWISE,
    '-90': cv2.ROTATE_90_COUNTERCLOCKWISE,
    '270': cv2.ROTATE_90_COUNTERCLOCKWISE,
    '180': cv2.ROTATE_180,
    '0': None,
}

LIVE_FRAME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live_frame.jpg')
_last_frame_write = 0.0


def publish_live_frame(frame, min_interval=0.1):
    global _last_frame_write
    now = time.time()
    if now - _last_frame_write < min_interval:
        return
    _last_frame_write = now
    try:
        cv2.imwrite(LIVE_FRAME_PATH, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    except Exception as e:
        print(f'[LiveFrame] Write failed: {e}')


def resolve_source(raw_source: str):
    '''Turns "0", "1" into a webcam index, otherwise returns the URL as-is.'''
    if raw_source.isdigit():
        return int(raw_source)
    return raw_source


def resolve_rotation(raw_rotation: str):
    if raw_rotation not in ROTATE_MAP:
        raise ValueError(
            f'Invalid CAMERA_ROTATE value "{raw_rotation}". '
            'Use one of: 0, 90, -90, 180, 270.'
        )
    return ROTATE_MAP[raw_rotation]


class LatestFrameReader:
    '''Continuously reads raw frames on a background thread and only ever
    keeps the newest one, so a slow consumer never falls behind and causes a
    growing lag against a live network stream.'''

    def __init__(self, source, fps: float = 0.0):
        self.source = source
        self.cap = cv2.VideoCapture(source)
        self.lock = threading.Lock()
        self.frame = None
        self.stopped = False
        self.last_reconnect_attempt = 0.0
        self.thread = threading.Thread(target=self._update, daemon=True)
        
        # FPS throttling for video files
        self.fps = fps
        self.frame_interval = 1.0 / fps if fps > 0 else 0.0
        self.last_read_time = 0.0

    def is_opened(self):
        return self.cap.isOpened()

    def start(self):
        self.thread.start()
        return self

    def _update(self):
        while not self.stopped:
            # Throttle frame reading for video files
            if self.frame_interval > 0:
                now = time.time()
                elapsed = now - self.last_read_time
                if elapsed < self.frame_interval:
                    time.sleep(self.frame_interval - elapsed)
            
            ret, frame = self.cap.read()
            if not ret:
                if self.frame_interval > 0:  # video file — loop it
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                # For live streams, reconnect
                now = time.time()
                if now - self.last_reconnect_attempt > 2:
                    print('Lost connection to camera, retrying...')
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.source)
                    self.last_reconnect_attempt = now
                time.sleep(0.05)
                continue
            
            self.last_read_time = time.time()
            with self.lock:
                self.frame = frame

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.stopped = True
        self.thread.join(timeout=2)
        self.cap.release()


def build_fall_pipeline():
    '''Loads the pose-based fall detector (ported from
    vjn6805/Fall-Detection-Model). Returns (detector, state_manager) or
    (None, None) if it can't be set up (missing deps / no model download),
    so the live feed still runs with violence detection alone.'''
    if os.environ.get('FALL_DETECTION', '1') == '0':
        print('Fall detection disabled via FALL_DETECTION=0')
        return None, None

    try:
        from fall_detection.detector import PersonDetector
        from fall_detection.state import StateManager

        cfg_path = os.path.join(os.path.dirname(__file__), 'fall_detection', 'config.yaml')
        with open(cfg_path, 'r') as f:
            cfg = yaml.safe_load(f)

        detector = PersonDetector(
            model_name=cfg['model']['name'],
            confidence=cfg['model']['confidence'],
            input_size=cfg['model']['input_size'],
            tracker=cfg['tracking']['tracker'],
        )
        state_mgr = StateManager(
            max_frames=cfg['history']['max_frames'],
            expiry_seconds=cfg['history']['expiry_seconds'],
            pose_conf_threshold=cfg['tracking']['pose_conf_threshold'],
            fall_cfg=cfg.get('fall_detection'),
            risk_cfg=cfg.get('risk_engine'),
            camera_id=cfg.get('camera', {}).get('id', 'CAM-001'),
        )
        return detector, state_mgr
    except Exception as e:
        print(f'[Warning] Fall detection unavailable, continuing without it: {e}')
        return None, None


def main(headless: bool = False):
    # Phase 1c follow-up 2 item 3: effective-config dump at startup --
    # every Settings field's value AND where it came from (default,
    # env_var, config_file i.e. .env, or cli), secrets redacted by name
    # pattern. See api/core/config_dump.py.
    print_effective_config(label="main.py startup")

    source = resolve_source(os.environ.get('CAMERA_SOURCE', '0'))
    rotation = resolve_rotation(os.environ.get('CAMERA_ROTATE', '90'))
    # Downscale the working frame for both detection and display -- this is
    # what actually fixes the lag: CLIP + YOLO pose inference on a full-res
    # phone stream (often 1920x1080+) is far slower per-frame than on a
    # smaller frame. 0 disables resizing.
    detect_width = int(os.environ.get('DETECT_WIDTH', '640'))
    print(f'Connecting to camera source: {source}')

    # Determine if source is a video file (for FPS throttling)
    is_video_file = isinstance(source, str) and not source.isdigit()
    if is_video_file:
        cap_tmp = cv2.VideoCapture(source)
        video_fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
        cap_tmp.release()
        print(f'Video FPS: {video_fps:.1f} (throttling enabled)')
    else:
        video_fps = 0.0  # No throttling for live streams

    # LEGACY_DETECTORS_ENABLED (config, default True): a single master
    # switch for violence/fall/snatch, on top of their existing individual
    # env-var toggles -- lets fire+crash run alone (matching exactly what
    # scripts/eval_detectors.py and scripts/camera_replay.py measure/
    # replay) for apples-to-apples FPS comparison. Default True means
    # ordinary live-deployment behavior is UNCHANGED unless explicitly
    # turned off.
    legacy_enabled = settings.LEGACY_DETECTORS_ENABLED
    if not legacy_enabled:
        print('LEGACY_DETECTORS_ENABLED=false -- violence/fall/snatch detectors disabled for this run (fire+crash only)')

    model = None
    if legacy_enabled and os.environ.get('VIOLENCE_DETECTION', '1') != '0':
        model = Model()
        print('Violence detection: ON')
    else:
        print('Violence detection: OFF')

    fall_detector, fall_state_mgr = (None, None)
    if legacy_enabled:
        fall_detector, fall_state_mgr = build_fall_pipeline()
    if fall_detector is not None:
        from fall_detection.visualization import draw_persons, draw_emergency_banner
        print('Fall detection: ON')
    else:
        print('Fall detection: OFF')

    snatch_detector = None
    if legacy_enabled:
        snatch_detector, _ = build_snatch_pipeline()
    if snatch_detector is not None:
        print('Snatch detection: ON')
    else:
        print('Snatch detection: OFF')

    fire_detector = build_fire_pipeline()
    if fire_detector is not None:
        print('Fire detection: ON')
    else:
        print('Fire detection: OFF')

    crash_detector = build_crash_pipeline()
    if crash_detector is not None:
        print('Crash detection: ON')
    else:
        print('Crash detection: OFF')

    # Initialize API client for dashboard integration
    api_enabled = os.environ.get('API_ENABLED', '1') != '0'
    if api_enabled:
        api_client.start()
        print('API client: ON')
    else:
        print('API client: OFF')

    # Shared CCTV event-capture pipeline (CHANGELOG.md "CCTV Incident
    # Capture Pipeline" phase) -- the same EventCapturePipeline class
    # scripts/camera_replay.py uses for test replays. This is additive:
    # it creates real SQLite-backed Incident rows with source="live" and
    # a real evidence clip/best-frame, alongside (not instead of) the
    # existing Telegram/call alert + dashboard-API-push logic above,
    # which stays untouched (scope-locked).
    live_camera_id = os.environ.get('CAMERA_ID', 'CAM-001')
    event_pipeline = None
    if get_camera(live_camera_id) is not None:
        def _on_incident_ready(cam_id, ev, evidence):
            svc_v2.handle_finished_event(cam_id, ev, evidence, source=SourceKind.LIVE)

        def _on_quarantine(cam_id, category, reason, event_start, partial_evidence=None):
            svc_v2.handle_encode_failure(cam_id, category, reason, event_start, partial_evidence)

        event_pipeline = EventCapturePipeline(live_camera_id, _on_incident_ready, _on_quarantine)
        print(f'CCTV event-capture pipeline: ON (camera_id={live_camera_id})')
    else:
        print(f'CCTV event-capture pipeline: OFF (camera_id {live_camera_id!r} not in camera registry -- '
              f'set CAMERA_ID to a registered camera_id to enable real incident capture)')

    # Frame-sampling unification (same rule as scripts/camera_replay.py and
    # scripts/eval_detectors.py, via api/services/frame_sampler.py):
    # detection now runs on sampled frames only (SAMPLE_INTERVAL_S, config,
    # default 0.25s / ~4fps), not on every single frame. The ring buffer/
    # event-capture pipeline's add_raw_frame() is still called every
    # frame (unaffected -- clip quality). If inference falls behind the
    # sampling interval, the gate drops the frames in between and always
    # hands the detector the LATEST available frame, never queuing a
    # backlog; effective_fps (the actually-achieved rate) is logged
    # periodically. This is a deliberate behavior change from "every
    # frame" -- see CHANGELOG.md.
    detection_gate = RealtimeFrameGate(sample_interval_s=settings.SAMPLE_INTERVAL_S, label="fire+crash")
    print(f'Detection sampling: every {settings.SAMPLE_INTERVAL_S}s (~{1/settings.SAMPLE_INTERVAL_S:.1f} fps target) '
          f'-- ring buffer still captures every raw frame')
    if settings.DETECTION_ONLY_MODE:
        print('DETECTION_ONLY_MODE=true -- fire/crash detection and sampling run normally, but '
              'EventCapturePipeline.feed_detection() is skipped: no events, no incidents, no ffmpeg encoding this run')

    reader = LatestFrameReader(source, fps=video_fps if is_video_file else 0.0)

    if not reader.is_opened():
        raise RuntimeError(
            f'Could not open camera source "{source}". '
            'If you are streaming from your phone, make sure the IP camera '
            'app is running and the laptop is on the same Wi-Fi network.'
        )

    reader.start()

    def get_current_frame():
        frame = reader.read()
        if frame is None or frame.size == 0:
            return None
        try:
            if rotation is not None:
                frame = cv2.rotate(frame, rotation)
            if detect_width and frame.shape[1] > detect_width:
                scale = detect_width / frame.shape[1]
                frame = cv2.resize(frame, (detect_width, int(frame.shape[0] * scale)))
        except cv2.error:
            # Occasionally a torn/partial frame slips through right after a
            # stream reconnect -- just skip it rather than crashing a thread.
            return None
        return frame

    # Detection (CLIP + fall pipeline) runs on its own thread so it never
    # blocks the displayed video -- the display loop always shows the
    # latest camera frame and just overlays whatever detection result was
    # most recently computed, even if it lags behind by a frame or two.
    results_lock = threading.Lock()
    latest = {'label': 'Unknown', 'confidence': 0.0, 'states': {}}
    stop_detection = False

    # Alerts fire once per *transition into* an alert condition, not on every
    # frame the condition continues to hold -- otherwise a violent scene that
    # stays on screen for 10 seconds spams send_telegram_alert/send_call_alert
    # every loop iteration (the cooldown inside those functions blocks the
    # actual send, but still prints "started"/"waiting" every time and does
    # unnecessary work).
    was_violent = False
    fall_alerted_ids = set()
    emergency_alerted_ids = set()
    snatch_alerted = False
    fire_alerted = False
    crash_alerted = False

    # Track incidents sent to API to avoid duplicates
    api_incident_cooldown = {}
    API_COOLDOWN_SECONDS = 30

    def should_send_to_api(incident_type: str, track_id: str = None) -> bool:
        key = f"{incident_type}_{track_id or 'global'}"
        now = time.time()
        last = api_incident_cooldown.get(key, 0)
        if now - last >= API_COOLDOWN_SECONDS:
            api_incident_cooldown[key] = now
            return True
        return False

    def send_incident_to_api(frame, detection_type: str, confidence: float, detection_data: dict = None, track_id: str = None):
        if not api_enabled:
            return
        if not should_send_to_api(detection_type, track_id):
            return
        try:
            camera_lat = os.environ.get('CAMERA_LAT')
            camera_lng = os.environ.get('CAMERA_LNG')
            if not camera_lat or not camera_lng:
                print('[APIClient] CAMERA_LAT/CAMERA_LNG not set in environment -- '
                      'refusing to send incident with an unknown location (no dummy coordinate fallback).')
                return
            incident = create_incident_from_detection(
                frame=frame,
                detection_result={'confidence': confidence, **(detection_data or {})},
                detection_type=detection_type,
                camera_id=os.environ.get('CAMERA_ID', 'CAM-001'),
                location_name=os.environ.get('CAMERA_LOCATION', 'MI Road, Jaipur'),
                latitude=float(camera_lat),
                longitude=float(camera_lng),
            )
            if incident:
                api_client.submit_incident(incident)
        except Exception as e:
            print(f'[APIClient] Error creating incident: {e}')

    def _feed_event_pipeline_detection(frame, category, confidence, boxes, detector_source, model_name, threshold):
        if event_pipeline is None:
            return
        if settings.DETECTION_ONLY_MODE:
            # Phase 1c follow-up 2 item 3: detection + sampling still ran
            # (the caller already called process_frame() and the sampling
            # gate already decided to process this iteration) -- only the
            # event-lifecycle/encode side is skipped, isolating detection
            # throughput from event+ffmpeg-encode cost for measurement.
            return
        formatted_boxes = [
            {"label": b.get("class", category), "confidence": b.get("confidence", confidence), "box": list(b.get("box", (0, 0, 0, 0)))}
            for b in (boxes or [])
        ]
        event_pipeline.feed_detection(
            frame=frame, ts=datetime.now(timezone.utc),
            category=category, confidence=confidence, boxes=formatted_boxes,
            detector_source=detector_source, model_name=model_name, threshold_applied=threshold,
        )

    def detection_loop():
        nonlocal latest, was_violent, snatch_alerted, fire_alerted, crash_alerted
        while not stop_detection:
            iteration_start = time.time()
            frame = get_current_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            # Write frame immediately — don't wait for inference to finish
            publish_live_frame(frame)
            # Ring buffer/event-capture keeps EVERY raw frame regardless of
            # the detection sampling interval below (clip quality) -- see
            # api/services/frame_sampler.py's module docstring.
            if event_pipeline is not None:
                event_pipeline.add_raw_frame(frame, datetime.now(timezone.utc))

            # Phase 1c sampling follow-up item 4: this decision is made
            # from iteration_start (captured at the TOP of this loop
            # iteration, before violence/fall/snatch/fire/crash all run),
            # not from any single detector's own inference time -- so a
            # slow overall iteration (e.g. fall-detection pose inference
            # alone exceeding the sample interval) correctly causes
            # fire/crash to be skipped this iteration too, using the
            # freshest frame next time the gate opens (LatestFrameReader
            # already guarantees get_current_frame() never returns a
            # stale queued frame).
            run_fire_crash_this_iteration = detection_gate.should_process(now=iteration_start)
            # Feed into evidence buffer
            try:
                evidence_service.add_frame(os.environ.get('CAMERA_ID', 'CAM-001'), frame, datetime.utcnow())
            except Exception:
                pass

            label = 'Unknown'
            confidence = 0.0
            is_violence = False

            if model is not None:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                prediction = model.predict(image=rgb_frame)
                label = prediction['label']
                confidence = prediction['confidence']
                is_violence = 'violence' in label.lower() or 'fight' in label.lower() or 'fire' in label.lower() or 'crash' in label.lower()

                if is_violence and not was_violent:
                    message = f'Possible violence detected: {label} (confidence {confidence:.2f})'
                    send_telegram_alert(frame, message, reason='violence')
                    send_call_alert(message, reason='violence')
                    send_incident_to_api(frame, 'violence', confidence, {'label': label})
                was_violent = is_violence

            states = {}
            if fall_detector is not None:
                try:
                    persons = fall_detector.track(frame)
                    # StateManager.update() returns its own internal dict by
                    # reference. It keeps mutating that dict (adding/expiring
                    # people) on this thread while the display thread iterates
                    # it in draw_persons() -- snapshot the keys/values here so
                    # the display thread can't see a dict resize mid-iteration.
                    states = dict(fall_state_mgr.update(persons, time.time(), frame=frame))

                    current_ids = set(states.keys())
                    fall_alerted_ids.intersection_update(current_ids)
                    emergency_alerted_ids.intersection_update(current_ids)

                    for pid, state in states.items():
                        fr = state.fall_result
                        rr = state.risk_result
                        if fr and fr.state.value == 'FALL_CONFIRMED' and pid not in fall_alerted_ids:
                            send_telegram_alert(frame, f'Fall detected! Person #{pid} may be injured.', reason='fall_detected')
                            send_call_alert('Fall detected! A person may be injured.', reason='fall_detected')
                            send_incident_to_api(frame, 'fall', 0.85, {'track_id': pid, 'fall_state': fr.state.value}, track_id=str(pid))
                            fall_alerted_ids.add(pid)
                        elif fr and fr.state.value != 'FALL_CONFIRMED':
                            fall_alerted_ids.discard(pid)

                        if rr and rr.state.value == 'POTENTIAL_HEALTH_EMERGENCY' and pid not in emergency_alerted_ids:
                            send_telegram_alert(frame, f'Potential health emergency! Person #{pid} has been down and inactive.', reason='health_emergency')
                            send_call_alert('Potential health emergency detected.', reason='health_emergency')
                            send_incident_to_api(frame, 'fall', 0.9, {'track_id': pid, 'risk_state': rr.state.value}, track_id=str(pid))
                            emergency_alerted_ids.add(pid)
                        elif rr and rr.state.value != 'POTENTIAL_HEALTH_EMERGENCY':
                            emergency_alerted_ids.discard(pid)
                except Exception as e:
                    print(f'[Warning] Fall detection frame error: {e}')

            # Snatch detection
            snatch_result = None
            if snatch_detector is not None:
                try:
                    snatch_result = snatch_detector.process_frame(frame)
                    if snatch_result and snatch_result.verdict in ['ALERT', 'FLAG']:
                        if not snatch_alerted:
                            reason = 'snatching' if snatch_result.verdict == 'ALERT' else 'snatching_suspicious'
                            message = f'SNATCHING DETECTED: {snatch_result.verdict} (Vote: {snatch_result.vote:.2f}, Motion: {snatch_result.p_motion:.2f}, Pose: {snatch_result.p_pose:.2f}, Context: {snatch_result.p_context:.2f})'
                            send_telegram_alert(frame, message, reason=reason)
                            send_call_alert(message, reason=reason)
                            send_incident_to_api(frame, 'snatch', snatch_result.vote, {
                                'verdict': snatch_result.verdict,
                                'vote': snatch_result.vote,
                                'p_motion': snatch_result.p_motion,
                                'p_pose': snatch_result.p_pose,
                                'p_context': snatch_result.p_context,
                                'track_ids': snatch_result.track_ids,
                            }, track_id=str(snatch_result.track_ids[0]) if snatch_result.track_ids else None)
                            snatch_alerted = True
                    else:
                        snatch_alerted = False
                except Exception as e:
                    print(f'[Warning] Snatch detection frame error: {e}')

            # Crash detection -- the fire_crash_gate decision (based on
            # TOTAL loop-iteration time, not just this detector's own
            # inference time -- Phase 1c sampling follow-up item 4) was
            # already made above, before violence/fall/snatch ran, so
            # that a slow overall iteration (e.g. fall-detection pose
            # inference taking longer than the sample interval) also
            # correctly causes this iteration's frame to be skipped for
            # fire/crash, not just a too-fast crash-detector-only timer.
            crash_result = None
            if crash_detector is not None and run_fire_crash_this_iteration:
                try:
                    crash_result = crash_detector.process_frame(frame)
                    _feed_event_pipeline_detection(
                        frame,
                        'crash' if crash_result and crash_result.detection else None,
                        crash_result.confidence if crash_result and crash_result.detection else 0.0,
                        crash_result.boxes if crash_result and crash_result.detection else [],
                        'yolov8-crash', 'crash_best.pt', 0.5,
                    )
                    if crash_result and crash_result.detection and not crash_alerted:
                        message = f'CRASH/ACCIDENT DETECTED: {crash_result.detection} (confidence {crash_result.confidence:.2f})'
                        send_telegram_alert(frame, message, reason='crash')
                        send_call_alert(message, reason='crash')
                        send_incident_to_api(frame, 'crash', crash_result.confidence, {
                            'detection': crash_result.detection,
                            'boxes': crash_result.boxes,
                        })
                        crash_alerted = True
                    elif not crash_result.detection:
                        crash_alerted = False
                except Exception as e:
                    print(f'[Warning] Crash detection frame error: {e}')

            # Fire detection -- same gate as crash above.
            fire_result = None
            if fire_detector is not None and run_fire_crash_this_iteration:
                try:
                    fire_result = fire_detector.process_frame(frame)
                    _feed_event_pipeline_detection(
                        frame,
                        'fire' if fire_result.detection else None,
                        fire_result.confidence if fire_result.detection else 0.0,
                        fire_result.boxes if fire_result.detection else [],
                        'yolov8-fire', 'best_nano_111.pt', 0.5,
                    )
                    if fire_result.detection and not fire_alerted:
                        message = f'FIRE/SMOKE DETECTED: {fire_result.detection} (confidence {fire_result.confidence:.2f})'
                        send_telegram_alert(frame, message, reason='fire')
                        send_call_alert(message, reason='fire')
                        send_incident_to_api(frame, 'fire', fire_result.confidence, {
                            'detection': fire_result.detection,
                            'boxes': fire_result.boxes,
                        })
                        fire_alerted = True
                    elif not fire_result.detection:
                        fire_alerted = False
                except Exception as e:
                    print(f'[Warning] Fire detection frame error: {e}')

            with results_lock:
                latest = {'label': label, 'confidence': confidence, 'is_violence': is_violence, 'states': states, 'snatch_result': snatch_result, 'fire_result': fire_result, 'crash_result': crash_result}

    detection_thread = threading.Thread(target=detection_loop, daemon=True)
    detection_thread.start()

    frame_times = []
    fps = 0.0

    if headless:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_detection = True
            detection_thread.join(timeout=2)
            reader.stop()
            if api_enabled:
                api_client.stop()
            if event_pipeline is not None:
                event_pipeline.flush(datetime.now(timezone.utc))
        return

    window_name = 'Violence & Fall Detection - Live Feed'

    try:
        while True:
            t_start = time.perf_counter()
            frame = get_current_frame()
            if frame is None:
                cv2.waitKey(10)
                continue

            with results_lock:
                label = latest['label']
                confidence = latest.get('confidence', 0.0)
                is_violence = latest.get('is_violence', False)
                states = latest['states']
                snatch_result = latest.get('snatch_result')
                fire_result = latest.get('fire_result')
                crash_result = latest.get('crash_result')

            overlay_text = f'{label} ({confidence:.2f})'
            color = (0, 0, 255) if is_violence else (0, 200, 0)
            cv2.putText(frame, overlay_text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

            if fall_detector is not None and states:
                draw_emergency_banner(frame, states)
                draw_persons(frame, states)

            # Snatch detection overlay
            if snatch_result is not None:
                if snatch_result.verdict == 'ALERT':
                    snatch_color = (0, 0, 255)
                    snatch_label = f'SNATCH ALERT (Vote: {snatch_result.vote:.2f})'
                elif snatch_result.verdict == 'FLAG':
                    snatch_color = (0, 165, 255)
                    snatch_label = f'SNATCH FLAG (Vote: {snatch_result.vote:.2f})'
                else:
                    snatch_color = (0, 255, 0)
                    snatch_label = f'Snatch: Normal (Vote: {snatch_result.vote:.2f})'
                cv2.putText(frame, snatch_label, (10, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, snatch_color, 2)

            # Fire detection overlay
            if fire_result is not None:
                if fire_result.detection == 'Fire':
                    fire_color = (0, 0, 255)
                    fire_label = f'FIRE ALERT (Conf: {fire_result.confidence:.2f})'
                elif fire_result.detection == 'Smoke':
                    fire_color = (0, 165, 255)
                    fire_label = f'SMOKE ALERT (Conf: {fire_result.confidence:.2f})'
                else:
                    fire_color = (0, 255, 0)
                    fire_label = 'Fire: No Detection'
                cv2.putText(frame, fire_label, (10, 105),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, fire_color, 2)

                if fire_detector is not None and fire_result.boxes:
                    for box_info in fire_result.boxes:
                        box = box_info['box']
                        class_name = box_info['class']
                        conf = box_info['confidence']
                        fire_detector.draw_detection(frame, box, class_name, conf)

            # Crash detection overlay
            if crash_result is not None:
                if crash_result.detection == 'Accident':
                    crash_color = (0, 0, 255)
                    crash_label = f'CRASH ALERT (Conf: {crash_result.confidence:.2f})'
                else:
                    crash_color = (0, 255, 0)
                    crash_label = 'Crash: No Detection'
                cv2.putText(frame, crash_label, (10, 140),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, crash_color, 2)

                if crash_detector is not None and crash_result.boxes:
                    for box_info in crash_result.boxes:
                        box = box_info['box']
                        class_name = box_info['class']
                        conf = box_info['confidence']
                        crash_detector.draw_detection(frame, box, class_name, conf)

            frame_times.append(time.perf_counter() - t_start)
            if len(frame_times) > 30:
                frame_times.pop(0)
            fps = 1.0 / (sum(frame_times) / len(frame_times))
            cv2.putText(frame, f'FPS: {fps:.1f}', (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        stop_detection = True
        detection_thread.join(timeout=2)
        reader.stop()
        if api_enabled:
            api_client.stop()
        if event_pipeline is not None:
            event_pipeline.flush(datetime.now(timezone.utc))
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
