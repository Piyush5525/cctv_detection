"""Open a registered stream, report delivery health, and save its first frame."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import cv2
from api.models.camera import get_camera, resolve_stream_source

def main():
    if len(sys.argv) != 2: raise SystemExit("usage: python scripts/check_camera.py <camera_id>")
    camera = get_camera(sys.argv[1])
    if camera is None: raise SystemExit("ERROR: unknown camera id")
    source = resolve_stream_source(camera); started = time.monotonic(); cap = cv2.VideoCapture(source)
    if not cap.isOpened(): raise SystemExit(f"ERROR: unreachable stream for {camera.camera_id}; check URL, phone app, and same Wi-Fi.")
    times, frame = [], None
    for _ in range(20):
        before = time.monotonic(); ok, frame = cap.read()
        if not ok: cap.release(); raise SystemExit("ERROR: stream opened but stopped delivering frames")
        times.append(time.monotonic())
    cap.release(); output = Path(__file__).parent.parent / "data" / f"camera_check_{camera.camera_id}.jpg"; cv2.imwrite(str(output), frame)
    fps = (len(times)-1) / (times[-1]-times[0]) if len(times) > 1 and times[-1] > times[0] else 0
    h, w = frame.shape[:2]; print(f"camera={camera.camera_id} resolution={w}x{h} measured_fps={fps:.2f} first_frame_latency_s={times[0]-started:.3f} test_frame={output}")
if __name__ == "__main__": main()
