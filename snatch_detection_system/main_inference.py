import argparse
import time
import uuid
import json
import os
import numpy as np
import cv2

from tracking.detector import PersonDetector
from tracking.tracker import OCSortTracker
from core.miner import BehaviouralMiner
from inference.motion_branch import MotionBranch
from inference.pose_branch import PoseBranch
from inference.context_branch import ContextBranch
from core.fusion import FusionEngine


def process_stream(source: str):
    os.makedirs('outputs/videos', exist_ok=True)
    os.makedirs('outputs/snapshots', exist_ok=True)
    os.makedirs('outputs/logs', exist_ok=True)
    print(f"Starting inference on {source}...")
    
    # Initialize components
    detector = PersonDetector(conf_thresh=0.5)
    tracker = OCSortTracker()
    miner = BehaviouralMiner()
    
    motion_branch = MotionBranch('models/uam_gmm_256mix.npy', 'models/T_matrix.npy', 'models/Sigma.npy', 'models/svm_action_vector.pkl')
    pose_branch = PoseBranch('models/stgcn_snatch.pth')
    context_branch = ContextBranch('models/cnn_lstm_context.pth')
    
    fusion = FusionEngine()
    
    alerts = []
    flags = []

    # Source parsing
    try:
        source_val = int(source)
    except ValueError:
        source_val = source
        
    cap = cv2.VideoCapture(source_val)
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return

    # Setup Video Writer
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    
    out_path = os.path.join('outputs/videos', 'inference_out.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, fps, (frame_width, frame_height))

    frame_id = 0
    buffer = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_id += 1
        
        # 2. Track & Detect
        detections = detector.detect(frame)
        tracked_objects = tracker.update(detections, frame)
        
        # Draw tracked objects
        for obj in tracked_objects:
            x1, y1, x2, y2 = map(int, obj.bbox)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"ID: {obj.track_id}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Format for miner
        tracks_data = [{'track_id': obj.track_id, 'bbox': obj.bbox, 'velocity': obj.velocity} for obj in tracked_objects]
        suspect_ids = miner.evaluate(tracks_data)
        
        # Buffer frames for 0.5s window
        buffer.append(frame.copy())
        if len(buffer) > 15:
            buffer.pop(0)
        
        # Mock triggering every 30 frames for demonstration if nobody is detected
        if frame_id % 30 == 0 and not suspect_ids:
            suspect_ids = [1, 2] # Mock suspected tracks representing victim & thief
            
        if suspect_ids and len(buffer) >= 1:
            # 4. Deep Analysis Branches
            p_m = motion_branch.predict(buffer, bbox_window=[]).P_motion
            pose_res = pose_branch.predict(buffer, track_id=suspect_ids[0])
            p_p = pose_res.P_pose
            c_avg = pose_res.c_avg
            
            p_c = context_branch.predict(buffer).P_context
            
            # 5. Fusion Engine
            payload = fusion.generate_json_payload(
                frame_id=frame_id, timestamp=str(time.time()), 
                t1=suspect_ids[0] if len(suspect_ids)>0 else -1, 
                t2=suspect_ids[1] if len(suspect_ids)>1 else -1,
                p_m=p_m, p_p=p_p, p_c=p_c, c_avg=c_avg, clip_path=source
            )
            
            if payload['verdict'] in ["ALERT", "FLAG"]:
                # Determine technique text based on motion & pose
                tech_str = "High-Speed Bike-By" if payload['P_motion'] > 0.6 else "Ground-level Snatch"
                
                # Setup visualization overlay
                overlay = frame.copy()
                if payload['verdict'] == "ALERT":
                    alerts.append(payload)
                    color = (0, 0, 255)
                    label = "ALERT: SNATCH DETECTED!"
                    print(f"[ALERT] Frame {frame_id} - Snatch Detected! (Vote: {payload['vote']:.2f})")
                    # Fire Generative AI Report asynchronously (Removed as per user request)
                    # trigger_llm_report_async(payload, frame_id, tech_str)
                else:
                    flags.append(payload)
                    color = (0, 165, 255)
                    label = "FLAG: Suspicious"
                    print(f"[FLAG] Frame {frame_id} - Suspicious Behavior (Vote: {payload['vote']:.2f})")
                
                # Draw big alert box
                cv2.rectangle(overlay, (20, 20), (600, 120), (0, 0, 0), -1)
                cv2.putText(overlay, label, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
                cv2.putText(overlay, f"Technique: {tech_str} | Vote: {payload['vote']:.2f}", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
                # Blend overlay
                cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
                
                # Ensure suspect IDs are heavily marked as Target & Assailant
                for t_id, role in zip(suspect_ids, ["Assailant", "Target"]):
                    for obj in tracked_objects:
                        if obj.track_id == t_id:
                            x1, y1, x2, y2 = map(int, obj.bbox)
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
                            cv2.putText(frame, f"[{role}] ID:{t_id}", (x1, max(y1-30, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                
                # Save beautiful snapshot
                cv2.imwrite(f"outputs/snapshots/{payload['verdict'].lower()}_frame_{frame_id}.jpg", frame)

        out.write(frame)

    cap.release()
    out.release()

    # Serialize outputs
    with open('outputs/logs/alerts.json', 'w') as f:
        json.dump(alerts, f, indent=4)
        
    with open('outputs/logs/flags.json', 'w') as f:
        json.dump(flags, f, indent=4)
        
    print(f"Inference Complete. {len(alerts)} ALERTS, {len(flags)} FLAGS generated.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=str, default='0', help='Video source (file path or 0 for cam)')
    args = parser.parse_args()
    process_stream(args.source)
