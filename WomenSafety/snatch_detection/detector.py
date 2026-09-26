"""
Snatch detection wrapper for WomenSafety integration.
Uses existing YOLOv8-pose for keypoints + ST-GCN + CNN-LSTM + Motion heuristics.
"""

import os
import sys
import time
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import torch
import torch.nn.functional as F

# Add parent directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snatch_detection.tracking.detector import PersonDetector as SnatchPersonDetector
from snatch_detection.tracking.tracker import OCSortTracker
from snatch_detection.core.miner import BehaviouralMiner
from snatch_detection.core.fusion import FusionEngine
from snatch_detection.models_arch.stgcn_arch import STGCN
from snatch_detection.models_arch.cnn_lstm_arch import CNNLSTMContextBranch

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


@dataclass
class SnatchResult:
    """Result of snatch detection for a frame."""
    verdict: str  # "ALERT", "FLAG", or "NORMAL"
    vote: float
    p_motion: float
    p_pose: float
    p_context: float
    c_avg: float
    track_ids: List[int]
    frame_id: int


class YOLOPoseExtractor:
    """Wrapper for YOLOv8-pose keypoint extraction (reuses fall detection model)."""
    
    def __init__(self, model_path: str = 'yolov8n-pose.pt', device: str = 'cpu', conf: float = 0.3):
        if YOLO is None:
            raise RuntimeError("ultralytics not installed")
        self.device = device
        self.conf = conf
        self.model = YOLO(model_path)
        self.model.to(device)
        print(f"[YOLOPoseExtractor] Loaded {model_path} on {device}")
    
    def extract(self, frame: np.ndarray, bboxes: List[np.ndarray]) -> List[Dict]:
        """
        Extract keypoints for each tracked bbox using YOLOv8-pose.
        Returns list of dicts with keypoints (17,2), scores (17,), bbox
        """
        if len(bboxes) == 0:
            return []
        
        # Run YOLOv8-pose on full frame
        results = self.model(frame, verbose=False, conf=self.conf)
        
        # Build lookup: bbox -> keypoints
        pose_results = []
        if results[0].keypoints is not None:
            all_kpts = results[0].keypoints.xy.cpu().numpy()  # (N, 17, 2)
            all_scores = results[0].keypoints.conf.cpu().numpy()  # (N, 17)
            all_boxes = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes is not None else []
            
            # Match tracked bboxes to detected poses by IoU
            for bbox in bboxes:
                best_idx = -1
                best_iou = 0.3
                for i, det_box in enumerate(all_boxes):
                    iou = self._bbox_iou(bbox, det_box)
                    if iou > best_iou:
                        best_iou = iou
                        best_idx = i
                
                if best_idx >= 0:
                    kpts = all_kpts[best_idx]
                    scores = all_scores[best_idx]
                else:
                    kpts = np.zeros((17, 2))
                    scores = np.zeros(17)
                
                pose_results.append({
                    'keypoints': kpts,
                    'scores': scores,
                    'bbox': bbox
                })
        else:
            # No poses detected
            for bbox in bboxes:
                pose_results.append({
                    'keypoints': np.zeros((17, 2)),
                    'scores': np.zeros(17),
                    'bbox': bbox
                })
        
        return pose_results
    
    def _bbox_iou(self, box1, box2):
        """Compute IoU between two boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0


class PoseBranchWrapper:
    """Proper Pose Branch using YOLOv8-pose + ST-GCN."""
    
    def __init__(self, stgcn_path: str, device: str = 'cpu'):
        self.device = torch.device(device)
        self.model = STGCN().to(self.device)
        try:
            self.model.load_state_dict(torch.load(stgcn_path, map_location=self.device))
            print(f"[PoseBranch] Loaded STGCN weights from {stgcn_path}")
        except FileNotFoundError:
            print(f"[PoseBranch] Warning: STGCN weights not found at {stgcn_path}")
        self.model.eval()
        
        # COCO skeleton edges for ST-GCN (17 keypoints)
        # Nose(0), L_eye(1), R_eye(2), L_ear(3), R_ear(4), 
        # L_shoulder(5), R_shoulder(6), L_elbow(7), R_elbow(8),
        # L_wrist(9), R_wrist(10), L_hip(11), R_hip(12),
        # L_knee(13), R_knee(14), L_ankle(15), R_ankle(16)
        edges = [
            (0, 1), (0, 2), (1, 3), (2, 4),  # head
            (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),  # arms
            (5, 11), (6, 12), (11, 12),  # torso
            (11, 13), (13, 15), (12, 14), (14, 16)  # legs
        ]
        edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous().to(self.device)
        self.edge_index = edge_index
    
    def predict(self, frames: List[np.ndarray], tracked_persons: List[Dict]) -> Dict:
        """
        Predict P_pose for the primary suspect.
        tracked_persons: list of dicts with 'track_id', 'keypoints', 'scores', 'bbox'
        """
        if len(tracked_persons) == 0 or len(frames) == 0:
            return {'P_pose': 0.5, 'c_avg': 0.0, 'weight': 0.0}
        
        # Use first tracked person as suspect
        person = tracked_persons[0]
        keypoints = person.get('keypoints', np.zeros((17, 2)))
        scores = person.get('scores', np.zeros(17))
        
        c_avg = float(np.mean(scores)) if len(scores) > 0 else 0.0
        
        if c_avg < 0.1:
            return {'P_pose': 0.5, 'c_avg': c_avg, 'weight': 0.0}
        
        weight = 0.35 if c_avg >= 0.4 else (c_avg / 0.4 * 0.35)
        
        # Build skeleton sequence for ST-GCN
        # Use current frame keypoints (in full impl, track across frames)
        kpts_seq = []
        for _ in frames:
            kpts_seq.append(keypoints)
        kpts_seq = np.array(kpts_seq)  # (T, 17, 2)
        
        # Convert to ST-GCN input format: (1, T, 17, 2)
        x = torch.from_numpy(kpts_seq).float().unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            try:
                out = self.model(x, self.edge_index)
                # out shape: (1, 2) - binary classification
                p_pose = float(torch.softmax(out, dim=-1)[0, 1].cpu().item())
            except Exception as e:
                print(f"[PoseBranch] STGCN forward error: {e}")
                p_pose = 0.5
        
        return {'P_pose': p_pose, 'c_avg': c_avg, 'weight': weight}


class ContextBranchWrapper:
    """Proper Context Branch using ResNet-18 + LSTM."""
    
    def __init__(self, weights_path: str, device: str = 'cpu'):
        self.device = torch.device(device)
        self.model = CNNLSTMContextBranch().to(self.device)
        try:
            self.model.load_state_dict(torch.load(weights_path, map_location=self.device))
            print(f"[ContextBranch] Loaded CNN-LSTM weights from {weights_path}")
        except FileNotFoundError:
            print(f"[ContextBranch] Warning: CNN-LSTM weights not found at {weights_path}")
        self.model.eval()
        
        # ImageNet normalization
        self.mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 1, 3, 1, 1).to(self.device)
        self.std = torch.tensor([0.229, 0.224, 0.225]).view(1, 1, 3, 1, 1).to(self.device)
    
    def predict(self, frames: List[np.ndarray]) -> Dict:
        """Predict P_context from frame sequence."""
        if len(frames) == 0:
            return {'P_context': 0.0}
        
        # Resize frames to 224x224 and normalize
        processed = []
        for f in frames:
            f_resized = cv2.resize(f, (224, 224))
            f_rgb = cv2.cvtColor(f_resized, cv2.COLOR_BGR2RGB)
            f_norm = f_rgb.astype(np.float32) / 255.0
            processed.append(f_norm)
        
        # Stack: (T, H, W, C) -> (1, T, C, H, W)
        x = np.stack(processed)  # (T, 224, 224, 3)
        x = torch.from_numpy(x).permute(0, 3, 1, 2).unsqueeze(0).float().to(self.device)
        x = (x - self.mean) / self.std
        
        with torch.no_grad():
            try:
                out = self.model(x)
                p_context = float(torch.sigmoid(out).item())
            except Exception as e:
                print(f"[ContextBranch] CNN-LSTM forward error: {e}")
                p_context = 0.0
        
        return {'P_context': p_context}


class MotionBranchWrapper:
    """Motion Branch using optical flow + pre-trained SVM (simplified)."""
    
    def __init__(self, uam_path: str, t_path: str, sigma_path: str, svm_path: str):
        self.uam_path = uam_path
        self.t_path = t_path
        self.sigma_path = sigma_path
        self.svm_path = svm_path
        
        # Load SVM and UAM params
        try:
            import joblib
            self.svm = joblib.load(svm_path)
            self.uam_gmm = np.load(uam_path, allow_pickle=True)
            self.T_matrix = np.load(t_path)
            self.Sigma = np.load(sigma_path)
            print(f"[MotionBranch] Loaded SVM/UAM weights")
        except Exception as e:
            print(f"[MotionBranch] Warning: Could not load motion weights: {e}")
            self.svm = None
    
    def _compute_optical_flow(self, frames: List[np.ndarray]) -> np.ndarray:
        """Compute dense optical flow between consecutive frames using Farneback."""
        if len(frames) < 2:
            return np.zeros((frames[0].shape[0], frames[0].shape[1], 2), dtype=np.float32)
        
        flows = []
        prev_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        for i in range(1, len(frames)):
            gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            flows.append(flow)
            prev_gray = gray
        
        if flows:
            avg_flow = np.mean(np.stack(flows), axis=0)
            return avg_flow
        return np.zeros((frames[0].shape[0], frames[0].shape[1], 2), dtype=np.float32)
    
    def predict(self, frames: List[np.ndarray], bbox_window: List) -> Dict:
        """Predict P_motion from optical flow."""
        if self.svm is None:
            return {'P_motion': 0.5, 'confidence_scale': 1.0}
        
        # Compute optical flow
        flow = self._compute_optical_flow(frames)
        
        # Average flow magnitude in bbox region
        if len(bbox_window) > 0:
            bbox = bbox_window[0]
            x1, y1, x2, y2 = map(int, bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(flow.shape[1], x2), min(flow.shape[0], y2)
            if x2 > x1 and y2 > y1:
                roi_flow = flow[y1:y2, x1:x2]
                flow_mag = np.mean(np.sqrt(roi_flow[:,:,0]**2 + roi_flow[:,:,1]**2))
            else:
                flow_mag = 0
        else:
            flow_mag = np.mean(np.sqrt(flow[:,:,0]**2 + flow[:,:,1]**2))
        
        # Normalize and use as feature for SVM
        feature = np.array([[flow_mag * 10]])
        
        try:
            decision = self.svm.decision_function(feature)[0]
            p_motion = 1.0 / (1.0 + np.exp(-decision))
            p_motion = float(np.clip(p_motion, 0.0, 1.0))
        except Exception as e:
            print(f"[MotionBranch] SVM error: {e}")
            p_motion = 0.5
        
        return {'P_motion': p_motion, 'confidence_scale': 1.0}


class SnatchDetector:
    """
    Wrapper for the snatching detection pipeline.
    Provides a simple interface: process_frame(frame) -> Optional[SnatchResult]
    """
    
    def __init__(self, model_dir: str, buffer_size: int = 15, device: str = 'cpu', pose_model_path: str = 'yolov8n-pose.pt'):
        self.model_dir = model_dir
        self.buffer_size = buffer_size
        self.device = device
        self.frame_id = 0
        self.frame_buffer = []
        self.pose_model_path = pose_model_path
        
        self._init_components()
        
    def _init_components(self):
        try:
            # Tracking components
            self.detector = SnatchPersonDetector(conf_thresh=0.5)
            self.tracker = OCSortTracker()
            self.miner = BehaviouralMiner()
            
            # YOLOv8-pose for keypoint extraction (reuse fall detection model)
            self.pose_extractor = YOLOPoseExtractor(
                model_path=self.pose_model_path,
                device=self.device,
                conf=0.3
            )
            
            # Deep learning branches
            self.motion_branch = MotionBranchWrapper(
                os.path.join(self.model_dir, 'uam_gmm_256mix.npy'),
                os.path.join(self.model_dir, 'T_matrix.npy'),
                os.path.join(self.model_dir, 'Sigma.npy'),
                os.path.join(self.model_dir, 'svm_action_vector.pkl')
            )
            self.pose_branch = PoseBranchWrapper(
                os.path.join(self.model_dir, 'stgcn_snatch.pth'),
                device=self.device
            )
            self.context_branch = ContextBranchWrapper(
                os.path.join(self.model_dir, 'cnn_lstm_context.pth'),
                device=self.device
            )
            self.fusion = FusionEngine()
            
            self._initialized = True
            print('[SnatchDetector] All components initialized successfully')
        except Exception as e:
            print(f'[SnatchDetector] Initialization failed: {e}')
            import traceback
            traceback.print_exc()
            self._initialized = False
            raise
    
    def process_frame(self, frame: np.ndarray) -> Optional[SnatchResult]:
        if not self._initialized:
            return None
            
        self.frame_id += 1
        
        # 1. Detect & Track persons
        detections = self.detector.detect(frame)
        tracked_objects = self.tracker.update(detections, frame)
        
        # 2. Extract keypoints for tracked persons using YOLOv8-pose
        bboxes = [obj.bbox for obj in tracked_objects]
        pose_results = self.pose_extractor.extract(frame, bboxes)
        
        # Merge pose data with tracked objects
        tracked_persons = []
        for obj, pose in zip(tracked_objects, pose_results):
            tracked_persons.append({
                'track_id': obj.track_id,
                'bbox': obj.bbox,
                'velocity': obj.velocity,
                'keypoints': pose['keypoints'],
                'scores': pose['scores'],
            })
        
        # 3. Behavioral Miner evaluation
        tracks_data = [
            {
                'track_id': p['track_id'],
                'bbox': p['bbox'],
                'velocity': p['velocity'],
                'keypoints': p['keypoints'],
                'hand_kpt': p['keypoints'][9] if len(p['keypoints']) > 9 else np.zeros(2),  # right wrist
                'hand_vel': p['velocity'],
            }
            for p in tracked_persons
        ]
        
        suspect_ids = self.miner.evaluate(tracks_data)
        
        # 4. Buffer frames
        self.frame_buffer.append(frame.copy())
        if len(self.frame_buffer) > self.buffer_size:
            self.frame_buffer.pop(0)
        
        if len(self.frame_buffer) < 1:
            return None
        
        # 5. Run deep analysis if suspects found
        if suspect_ids:
            # Filter tracked persons to suspects
            suspect_persons = [p for p in tracked_persons if p['track_id'] in suspect_ids]
            
            # Motion branch
            motion_res = self.motion_branch.predict(self.frame_buffer, 
                                                     [p['bbox'] for p in suspect_persons])
            p_m = motion_res['P_motion']
            
            # Pose branch
            pose_res = self.pose_branch.predict(self.frame_buffer, suspect_persons)
            p_p = pose_res['P_pose']
            c_avg = pose_res['c_avg']
            
            # Context branch
            context_res = self.context_branch.predict(self.frame_buffer)
            p_c = context_res['P_context']
            
            # Fusion
            payload = self.fusion.generate_json_payload(
                frame_id=self.frame_id,
                timestamp=str(time.time()),
                t1=suspect_ids[0] if len(suspect_ids) > 0 else -1,
                t2=suspect_ids[1] if len(suspect_ids) > 1 else -1,
                p_m=p_m, p_p=p_p, p_c=p_c, c_avg=c_avg, clip_path='live'
            )
            
            return SnatchResult(
                verdict=payload['verdict'],
                vote=payload['vote'],
                p_motion=payload['P_motion'],
                p_pose=payload['P_pose'],
                p_context=payload['P_context'],
                c_avg=c_avg,
                track_ids=suspect_ids,
                frame_id=self.frame_id
            )
        
        return None
    
    def draw_detections(self, frame: np.ndarray, result: Optional[SnatchResult], 
                        tracked_objects: List = None) -> np.ndarray:
        """Draw detection overlays on frame."""
        if tracked_objects is not None:
            for obj in tracked_objects:
                x1, y1, x2, y2 = map(int, obj.bbox)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"ID: {obj.track_id}", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        if result is None:
            return frame
            
        if result.verdict in ["ALERT", "FLAG"]:
            overlay = frame.copy()
            if result.verdict == "ALERT":
                color = (0, 0, 255)
                label = "ALERT: SNATCH DETECTED!"
            else:
                color = (0, 165, 255)
                label = "FLAG: Suspicious"
            
            tech_str = "High-Speed Bike-By" if result.p_motion > 0.6 else "Ground-level Snatch"
            
            cv2.rectangle(overlay, (20, 20), (600, 120), (0, 0, 0), -1)
            cv2.putText(overlay, label, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
            cv2.putText(overlay, f"Technique: {tech_str} | Vote: {result.vote:.2f}", 
                        (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
            
            for t_id, role in zip(result.track_ids, ["Assailant", "Target"]):
                if tracked_objects:
                    for obj in tracked_objects:
                        if obj.track_id == t_id:
                            x1, y1, x2, y2 = map(int, obj.bbox)
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
                            cv2.putText(frame, f"[{role}] ID:{t_id}", 
                                        (x1, max(y1-30, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        
        return frame


def build_snatch_pipeline(model_dir: str = None, device: str = 'cpu', pose_model_path: str = 'yolov8n-pose.pt'):
    """
    Build the snatch detection pipeline.
    Returns (detector, None) or (None, None) if unavailable.
    """
    if os.environ.get('SNATCH_DETECTION', '1') == '0':
        print('Snatch detection disabled via SNATCH_DETECTION=0')
        return None, None
    
    if model_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_dir = os.path.join(base_dir, '..', 'snatch_detection_system', 'models')
        model_dir = os.path.normpath(model_dir)
    
    try:
        detector = SnatchDetector(model_dir, device=device, pose_model_path=pose_model_path)
        print('Snatch detection: ON')
        return detector, None
    except Exception as e:
        print(f'[Warning] Snatch detection unavailable, continuing without it: {e}')
        import traceback
        traceback.print_exc()
        return None, None