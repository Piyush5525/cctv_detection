from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class FusionResult:
    vote: float
    verdict: str

class FusionEngine:
    def __init__(self, alert_thresh: float = 0.75, flag_thresh: float = 0.50):
        self.alert_thresh = alert_thresh
        self.flag_thresh = flag_thresh

    def compute_vote(self, p_motion: float, p_pose: float, p_context: float, c_avg: float) -> FusionResult:
        """
        Visibility-aware weighted voting engine.
        """
        if c_avg >= 0.4:
            # Case 1 (pose reliable)
            vote = 0.50 * p_motion + 0.35 * p_pose + 0.15 * p_context
        else:
            # Case 2 (pose unreliable)
            vote = 0.77 * p_motion + 0.23 * p_context
            
        if vote > self.alert_thresh:
            verdict = "ALERT"
        elif vote > self.flag_thresh:
            verdict = "FLAG"
        else:
            verdict = "NORMAL"
            
        return FusionResult(vote=vote, verdict=verdict)

    def generate_json_payload(self, frame_id: int, timestamp: str, t1: int, t2: int, 
                              p_m: float, p_p: float, p_c: float, c_avg: float, clip_path: str) -> Dict[str, Any]:
        result = self.compute_vote(p_m, p_p, p_c, c_avg)
        return {
            "frame_id": frame_id,
            "timestamp_iso": timestamp,
            "track_id_1": t1,
            "track_id_2": t2,
            "P_motion": round(float(p_m), 4),
            "P_pose": round(float(p_p), 4),
            "P_context": round(float(p_c), 4),
            "vote": round(float(result.vote), 4),
            "verdict": result.verdict,
            "clip_path": clip_path
        }
