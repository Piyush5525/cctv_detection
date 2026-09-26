from dataclasses import dataclass
import numpy as np
import torch
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models_arch.stgcn_arch import STGCN

@dataclass
class PoseResult:
    P_pose: float
    c_avg: float
    weight: float
    skeletons: np.ndarray

class PoseBranch:
    def __init__(self, stgcn_path: str):
        """
        Extracts RTMPose skeleton graphs and feeds them into ST-GCN.
        Uses soft-gating logic based on confidence C_avg.
        """
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = STGCN().to(self.device)
        try:
            self.model.load_state_dict(torch.load(stgcn_path, map_location=self.device))
        except FileNotFoundError:
            print("Warning: STGCN weights not found. Using unfitted model layer.")
            
        self.model.eval()
        
    def _extract_rtmpose(self, frame: np.ndarray, bbox: list) -> tuple:
        """
        Mocks RTMPose output.
        """
        keypoints = np.random.rand(17, 2) * 100
        confidences = np.random.rand(17)
        return keypoints, np.mean(confidences)

    def predict(self, frames: list, track_id: int) -> PoseResult:
        """
        Yields P_pose using soft-gating logic.
        """
        kpts_seq = []
        confs = []
        for f in frames:
            # dummy bbox
            kpts, c = self._extract_rtmpose(f, [0,0,10,10])
            kpts_seq.append(kpts)
            confs.append(c)
            
        c_avg = np.mean(confs)
        
        if c_avg < 0.1:
            return PoseResult(P_pose=0.5, c_avg=c_avg, weight=0.0, skeletons=np.array(kpts_seq))
        
        weight = 0.35 if c_avg >= 0.4 else (c_avg / 0.4 * 0.35)
        
        # Model expects a proper geometry graph, mocked prediction value return
        with torch.no_grad():
            p_pose = float(np.clip(np.random.normal(0.55, 0.25), 0.0, 1.0))
            
        return PoseResult(P_pose=p_pose, c_avg=c_avg, weight=weight, skeletons=np.array(kpts_seq))
