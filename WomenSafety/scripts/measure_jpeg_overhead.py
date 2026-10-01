"""Measures the real cost of Phase 1c hardening's JPEG-compressed
ring-buffer/event-frame storage (Phase 1c follow-ups item 2):
  1. Per-frame JPEG compress time at 720p and 1080p.
  2. Detection FPS with the ring buffer ON vs OFF, for 1 and 3
     simulated cameras running concurrently (threads, since that's how
     main.py/multiple EventCapturePipeline instances would run).
  3. CPU usage during each of the above.
  4. PSNR and SSIM of a clip's re-encoded frame against the original
     source frame, to quantify the real quality cost of storing frames
     as JPEG q90 instead of raw.

Usage:
    python scripts/measure_jpeg_overhead.py
"""
import os
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import cv2
import numpy as np
import psutil

from api.services.event_capture import RingBuffer, _encode_jpeg, _decode_jpeg, JPEG_QUALITY


def get_real_frame(path: str, resolution: tuple[int, int], seek_fraction: float = 0.5) -> np.ndarray:
    """Seeks partway into the clip rather than always grabbing frame 0 --
    data/fire.mp4's very first frame is degenerate (solid black, std=0),
    which JPEG compresses losslessly and gives a meaningless PSNR/SSIM
    result. seek_fraction=0.5 grabs a frame from the middle of the clip,
    where real visual detail (flames, texture) is actually present."""
    cap = cv2.VideoCapture(path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_frames * seek_fraction))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"could not read a frame from {path}")
    frame_std = frame.std()
    if frame_std < 5.0:
        raise RuntimeError(f"frame from {path} at fraction {seek_fraction} is degenerate (std={frame_std:.2f}), "
                            f"not a meaningful quality test -- pick a different seek_fraction")
    return cv2.resize(frame, resolution)


def measure_compress_time(frame: np.ndarray, iterations: int = 200) -> dict:
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        encoded = _encode_jpeg(frame, JPEG_QUALITY)
        times.append(time.perf_counter() - t0)
    return {
        "mean_ms": round(sum(times) / len(times) * 1000, 3),
        "max_ms": round(max(times) * 1000, 3),
        "encoded_size_kb": round(len(encoded) / 1024, 1),
    }


def _build_real_detectors():
    """Real fire+crash detectors (same ones main.py/camera_replay.py use)
    -- measuring the ring buffer's FPS cost against a no-op loop would be
    meaningless (nothing to compare against); this measures it against
    the SAME real per-frame workload a live camera loop actually does."""
    from fire_detection.detector import build_fire_pipeline
    from crash_detection.detector import build_crash_pipeline
    return build_fire_pipeline(), build_crash_pipeline()


def simulate_camera_detection_loop(frame: np.ndarray, duration_s: float, use_buffer: bool,
                                    frame_counter: list, stop_flag: list,
                                    fire_detector, crash_detector):
    """Simulates one camera's detection-loop frame processing: run the
    REAL fire+crash detectors on the frame (the actual per-frame cost a
    live camera loop pays), optionally also push it into a ring buffer
    (JPEG-encoding it), count how many frames were processed in
    duration_s. The FPS delta between use_buffer=True/False is
    specifically the ring buffer's added cost on top of real inference
    work, not a comparison against doing nothing."""
    from datetime import datetime, timezone
    buffer = RingBuffer(8.0) if use_buffer else None
    idx = 0
    t_end = time.time() + duration_s
    while time.time() < t_end and not stop_flag[0]:
        fire_detector.process_frame(frame)
        crash_detector.process_frame(frame)
        if buffer is not None:
            buffer.add(frame, datetime.now(timezone.utc))
        idx += 1
    frame_counter[0] = idx


def measure_fps_with_and_without_buffer(frame: np.ndarray, num_cameras: int, duration_s: float = 8.0) -> dict:
    """Runs the without/with comparison for the SAME set of detector
    instances back-to-back (not concurrently with each other) so the
    two conditions are measured under identical thread-scheduling/GIL
    contention from the num_cameras threads -- only the buffer on/off
    flag differs between the two runs. Repeats each condition 3 times
    and reports the median, since a single 8s window still has enough
    OS-scheduling jitter under GIL contention to occasionally show
    nonsensical deltas on one run alone."""
    import statistics
    process = psutil.Process()
    detector_pairs = [_build_real_detectors() for _ in range(num_cameras)]

    def run_once(use_buffer: bool) -> tuple[float, float]:
        counters = [[0] for _ in range(num_cameras)]
        stop_flag = [False]
        threads = [
            threading.Thread(target=simulate_camera_detection_loop,
                              args=(frame, duration_s, use_buffer, counters[i], stop_flag,
                                    detector_pairs[i][0], detector_pairs[i][1]))
            for i in range(num_cameras)
        ]
        cpu_samples = []
        process.cpu_percent()
        for t in threads:
            t.start()
        t0 = time.time()
        while time.time() - t0 < duration_s:
            cpu_samples.append(process.cpu_percent())
            time.sleep(0.2)
        for t in threads:
            t.join()
        total_frames = sum(c[0] for c in counters)
        avg_fps_per_camera = (total_frames / num_cameras) / duration_s
        avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
        return avg_fps_per_camera, avg_cpu

    def run_median(use_buffer: bool, repeats: int = 3) -> dict:
        fps_vals, cpu_vals = [], []
        for _ in range(repeats):
            fps, cpu = run_once(use_buffer)
            fps_vals.append(fps)
            cpu_vals.append(cpu)
        return {"avg_fps_per_camera": round(statistics.median(fps_vals), 2),
                "avg_cpu_percent": round(statistics.median(cpu_vals), 1),
                "all_runs_fps": [round(f, 2) for f in fps_vals]}

    without = run_median(use_buffer=False)
    with_buf = run_median(use_buffer=True)
    return {"without_buffer": without, "with_buffer": with_buf}


def measure_quality(frame: np.ndarray) -> dict:
    encoded = _encode_jpeg(frame, JPEG_QUALITY)
    decoded = _decode_jpeg(encoded)

    psnr = cv2.PSNR(frame, decoded)

    gray1 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    ssim_score, _ = cv2.quality.QualitySSIM_compute(gray1, gray2)
    ssim_mean = float(ssim_score[0])

    return {"psnr_db": round(psnr, 2), "ssim": round(ssim_mean, 4), "jpeg_quality_used": JPEG_QUALITY}


def main():
    print(f"JPEG_QUALITY in effect (from config): {JPEG_QUALITY}\n")

    print("=== 1. Per-frame JPEG compress time ===")
    for name, res in [("720p", (1280, 720)), ("1080p", (1920, 1080))]:
        frame = get_real_frame("data/crash.mp4", res)
        result = measure_compress_time(frame)
        print(f"{name}: {result}")
    print()

    print("=== 2 & 3. Detection FPS + CPU, buffer ON vs OFF, 1 and 3 simulated cameras ===")
    frame_1080p = get_real_frame("data/crash.mp4", (1920, 1080))
    for num_cameras in (1, 3):
        result = measure_fps_with_and_without_buffer(frame_1080p, num_cameras, duration_s=5.0)
        print(f"{num_cameras} camera(s): {result}")
        fps_drop_pct = (1 - result["with_buffer"]["avg_fps_per_camera"] / result["without_buffer"]["avg_fps_per_camera"]) * 100
        print(f"  -> FPS drop from buffer: {fps_drop_pct:.1f}%")
    print()

    print("=== 4. Quality: PSNR/SSIM of JPEG-encoded-then-decoded frame vs original ===")
    frame_1080p_quality = get_real_frame("data/fire.mp4", (1920, 1080))
    quality = measure_quality(frame_1080p_quality)
    print(quality)

    # Save before/after frame pair for visual inspection.
    out_dir = Path("scripts") / "_jpeg_quality_check"
    out_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(out_dir / "before_original.png"), frame_1080p_quality)
    encoded = _encode_jpeg(frame_1080p_quality, JPEG_QUALITY)
    decoded = _decode_jpeg(encoded)
    cv2.imwrite(str(out_dir / "after_jpeg_q90.jpg"), decoded)
    print(f"\nSaved before/after frames to {out_dir}/")


if __name__ == "__main__":
    main()
