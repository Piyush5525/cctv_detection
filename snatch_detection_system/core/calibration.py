import numpy as np

def calculate_bhs_velocity(velocity_pixels: float, torso_length_pixels: float) -> float:
    """
    Converts raw pixel velocity to bh/s (body-height per second).
    Here body-height is approximated as 2.5 * torso_length.
    """
    if torso_length_pixels <= 0:
        return 0.0
    bh = torso_length_pixels * 2.5
    return velocity_pixels / bh

def get_neck_zone(keypoints: np.ndarray) -> dict:
    """
    Computes the neck zone dynamically based on shoulder keypoints.
    COCO format: L_shoulder is 5, R_shoulder is 6, L_hip is 11, R_hip is 12.
    """
    try:
        ls = keypoints[5]
        rs = keypoints[6]
        lh = keypoints[11]
        
        neck_center = (ls + rs) / 2.0
        torso_length = np.linalg.norm(neck_center - (lh + keypoints[12])/2.0)
        radius = 0.3 * torso_length
        return {
            'center': neck_center,
            'radius': radius,
            'torso_length': torso_length
        }
    except Exception:
        # Fallback if keypoints are missing or shape mismatches
        return {'center': np.array([0,0]), 'radius': 1.0, 'torso_length': 1.0}
