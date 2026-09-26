# Complete Project Explanation: Real-Time Snatch Theft Detection System

This document serves as the absolute, top-to-bottom master explanation of the **Multi-Branch Deep Learning Fusion Architecture for Real-Time Snatch Theft Detection**.

## 1. High-Level Summary
This objective of this project is to create an artificial intelligence pipeline that can analyze CCTV / surveillance video streams in real time and mathematically detect if a "chain-snatching", "purse-snatching", or "pickpocketing" event is occurring. It is designed to act on subtle clues that even a human viewer might miss.

To accomplish this without generating excessive false positives (like people just bumping into each other), the system breaks the visual data into **three parallel "branches"** of analysis and then legally fuses their opinions together via a **Weighted Verification Engine**.

---

## 2. Core Detection Pipeline (The 3 Branches)
Every suspicious frame is routed through three immensely powerful deep learning nodes:

### Branch A: The Motion Branch (`inference/motion_branch.py`)
* **What it looks at:** The raw pixel-flow and physics of movement.
* **How it works:** It uses Dense Optical Flow models (RAFT) to chart exactly how pixels are shifting. It histograms this data into motion boundaries (MBH) and maps it against a Universal Attribute Model (UAM). Finally, a mathematical classifier (SVM) scores the raw "aggressiveness" or "speed" of the movement.
* **Output:** `P_motion` (A score representing pure kinematic violence).

### Branch B: The Pose Branch (`inference/pose_branch.py`)
* **What it looks at:** The bodily skeleton and joints of the people.
* **How it works:** It uses `RTMPose` to detect 17 crucial joints on a human body (shoulders, elbows, wrists). It then feeds these joint movements over time into a Spatial-Temporal Graph Convolutional Network (`ST-GCN`). The GCN watches the *interactions* of these joints—looking specifically for outstretched arms converging rapidly onto another skeleton.
* **Output:** `P_pose` (A score representing skeletal snatching gestures).

### Branch C: The Context Branch (`inference/context_branch.py`)
* **What it looks at:** The background and the situational environment.
* **How it works:** An attacker on a motorcycle behaves differently than an attacker on foot. A pre-trained `ResNet-18` looks at the background structures (bikes, streets, crowds) while a 2-layer `LSTM` tracks how the physical background interacts with the foreground subjects over a 4-second timeframe.
* **Output:** `P_context` (A score representing environmental risk factors).

---

## 3. The Object Tracking & Geometric Miner
Deep learning models are incredibly heavy. We cannot afford to run the three deep branches on every single millisecond of an empty street.

* **Tracking (`tracking/`)**: The system uses `YOLOv8` backed by `OC-SORT` to draw green bounding boxes around living entities and assigns them persistent IDs.
* **Behavioral Miner (`core/miner.py`)**: A lightweight, rules-based engine that monitors all bounding boxes. It only wakes up the heavy Deep Learning branches if two bounding boxes get uncomfortably close to each other or their trajectories rapidly intersect.

---

## 4. The Fusion Engine (`core/fusion.py`)
Once a suspicious event triggers the neural networks, they all return their scores (`P_motion`, `P_pose`, `P_context`). Not all scores are equal depending on the video quality.

The `FusionEngine` relies on a highly intelligent **visibility-aware weighted voting engine**:
- **Scenario 1 (Good Lighting / Clear View):** If the skeleton is clearly visible (`c_avg >= 0.4`), the AI leans heavily on Pose.
  `Vote = (0.50 * Motion) + (0.35 * Pose) + (0.15 * Context)`
- **Scenario 2 (Blurry / Occluded):** If the camera is bad and limbs can't be seen, the AI ignores Pose completely to prevent false logic, relying strictly on brute physical motion and environment.
  `Vote = (0.77 * Motion) + (0.23 * Context)`

If the final `Vote` climbs above **`0.75`**, the system fires a critical **ALERT**. If the score is higher than **`0.50`**, it issues a **FLAG**.

---

## 5. Outputs and Real-World Logging
When an ALERT or FLAG is triggered (`main_inference.py`), the software immediately:
1. Takes the raw CCTV frame and overlays a massive colored banner (Red for ALERT, Orange for FLAG).
2. Explicitly prints the snatching `Technique` (e.g., "Ground-level Snatch", "High-Speed Bike-By") determined by the `P_motion` severity.
3. Outlines the primary suspect and the victim in ultra-thick strokes, labeling them `[Assailant] ID:X` and `[Target] ID:Y`.
4. Saves this pristine image into `outputs/snapshots/`.
5. Logs a fully structured JSON payload containing timestamps and exact metric decimals into `outputs/logs/alerts.json` for police/security software databases.

---

## 6. Offline Training Mode (`main_train.py`)
To train this system from scratch:
Instead of running inference, `main_train.py` iterates sequentially. It trains the UAM Gaussian Mixtures, factors the T-Matrix, builds the SVM margin lines, trains the ST-GCN graph, and compiles the CNN-LSTM. This creates the exact `.pth` and `.pkl` weights used in the live inference pipeline.
