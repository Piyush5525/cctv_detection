import numpy as np
from typing import Dict, List
from .calibration import get_neck_zone, calculate_bhs_velocity

class BehaviouralMiner:
    def __init__(self, fps: int = 30):
        """
        Geometrical pre-filter to identify anomaly windows (4-6s)
        operating at 30+ FPS without GPU.
        """
        self.fps = fps
        self.history: Dict[int, List[dict]] = {} # Track ID -> List of frame states
        
    def _trigger_proximity(self, victim_kpts, hand_kpt) -> bool:
        """
        Trigger 1 (Proximity): Hand keypoint within neck zone 
        (radius = 0.3 * torso length) for >= 0.5s.
        """
        zone = get_neck_zone(victim_kpts)
        dist = np.linalg.norm(hand_kpt - zone['center'])
        # A full implementation would check history for >= 0.5s via sequence buffer
        return dist <= zone['radius']

    def _trigger_convergence(self, hand_vel, victim_vel) -> bool:
        """
        Trigger 2 (Convergence): Interception angle between hand velocity 
        and victim velocity in range [90, 165] degrees.
        """
        norm_h = np.linalg.norm(hand_vel)
        norm_v = np.linalg.norm(victim_vel)
        if norm_h == 0 or norm_v == 0:
            return False
        
        cos_theta = np.dot(hand_vel, victim_vel) / (norm_h * norm_v)
        angle = np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0)))
        return 90 <= angle <= 165

    def _trigger_velocity_override(self, hand_vel_magnitude, bbox_height) -> bool:
        """
        Trigger 3 (Velocity Override): V_rel = hand_pixel_speed / bbox_height > 1.5 bh/s
        """
        if bbox_height <= 0:
            return False
        v_rel = hand_vel_magnitude / bbox_height
        return v_rel > 1.5

    def evaluate(self, tracks: List[dict]):
        """
        Evaluate frames to check for snatch suspected events.
        tracks: list of dicts with track_id, keypoints, bbox, velocity, etc.
        """
        alerts = []
        for track in tracks:
            t_id = track.get('track_id')
            if t_id is None:
                continue
            
            # Mock extraction of variables
            kpts = track.get('keypoints', np.zeros((17, 2)))
            hand_kpt = track.get('hand_kpt', np.zeros(2))
            hand_vel = track.get('hand_vel', np.array([0,0]))
            victim_vel = track.get('velocity', np.array([0,0]))
            bbox_height = track.get('bbox', [0,0,0,100])[3] - track.get('bbox', [0,0,0,0])[1]
            
            t1 = self._trigger_proximity(kpts, hand_kpt)
            t2 = self._trigger_convergence(hand_vel, victim_vel)
            t3 = self._trigger_velocity_override(np.linalg.norm(hand_vel), bbox_height)
            
            if (t1 and t2) or t3:
                alerts.append(t_id)
                
        return alerts
