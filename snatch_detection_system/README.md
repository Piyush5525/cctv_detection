# Multi-Branch Deep Learning Fusion Architecture for Real-Time Snatch Theft Detection in Urban CCTV Streams

This is a complete, production-grade AI/ML research project that implements a full offline training and online inference pipeline for real-time snatch theft detection. It fuses three parallel analysis branches (Motion, Pose, and Context) using a visibility-aware weighted voting engine.

## Architecture Overview

### 1. Motion Branch
Extracts dense optical flow (via RAFT), converts it to MBH (Motion Boundary Histograms), maps to a Super-vector using a Universal Attribute Model (UAM GMM), reduces dimensions using a T-Matrix, and classifies using an SVM (`P_motion`).

### 2. Pose Branch
Leverages RTMPose for 17-point skeleton extraction and an ST-GCN (Spatial-Temporal Graph Convolutional Network) to identify snatching actions via joint trajectories (`P_pose`).

### 3. Context Branch
Passes raw frames into a frozen ResNet-18 feature extractor into a 2-layer LSTM. Evaluates the 4-6 second context window for environment-level features (e.g., bike presence, trajectory convergence) yielding `P_context`.

### 4. Fusion Engine
Merges predictions using a visibility-aware weighted voting engine:
- High confidence pose: `Vote = 0.50*P_motion + 0.35*P_pose + 0.15*P_context`
- Low confidence pose: `Vote = 0.77*P_motion + 0.23*P_context`

### 5. Behavioural Miner (Pre-filter)
Runs geometric analysis (Proximity, Convergence, Velocity) purely on bounding box/keypoint kinematics to isolate 4-6s windows that warrant deep analysis.

## Offline Training

To train the models offline from scratch, use the `main_train.py` script.
```bash
python main_train.py
```
This executes:
1. UAM Training
2. T-Matrix Factor Analysis
3. SVM Classification
4. ST-GCN Graph network
5. CNN-LSTM Context evaluation

## Online Inference

Run `main_inference.py` to stream video or RTSP files into the pipeline.
```bash
python main_inference.py --source data/snatch_clips/sample_1.mp4 
```

## Performance & Outputs
Outputs will be produced in the `outputs/` folder. Evaluate the model performance metrics tracking Precision, Recall, and ROC curves executing:
```bash
python evaluate.py
```
