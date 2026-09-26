import os
import json
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import f1_score, precision_score, recall_score, roc_curve, auc

def compute_metrics(y_true, y_pred, y_prob):
    f1 = f1_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    roc_auc = auc(fpr, tpr)
    return {
        "F1": float(f1),
        "Precision": float(prec),
        "Recall": float(rec),
        "AUC": float(roc_auc)
    }, fpr, tpr

def plot_demo_images(out_dir: str):
    """
    Generates the requested hardcoded dummy outputs (output_001 -> output_004).
    """
    # Create empty mock image templates
    for i in range(1, 5):
        ext = 'jpg' if i <= 2 else 'png'
        filename = f"output_{i:03d}.{ext}"
        path = os.path.join(out_dir, filename)
        
        # create a dummy image (e.g. random noise or blank)
        img = (np.random.rand(400, 400, 3) * 255).astype(np.uint8)
        plt.imsave(path, img)

def generate_graphs(y_true, y_vote, fpr_m, tpr_m, auc_m, fpr_p, tpr_p, auc_p, fpr_f, tpr_f, auc_f, out_dir):
    """
    Generates output_005.png and output_006.png
    """
    # output_005.png - Histogram
    plt.figure()
    plt.hist(y_vote[y_true==0], bins=20, alpha=0.5, label='Normal', color='blue')
    plt.hist(y_vote[y_true==1], bins=20, alpha=0.5, label='Snatch', color='red')
    plt.axvline(x=0.75, color='k', linestyle='--', label='Alert Thresh')
    plt.title("Fusion Vote Distribution (Normal vs Snatch)")
    plt.legend()
    plt.savefig(os.path.join(out_dir, "output_005.png"))
    plt.close()

    # output_006.png - ROC
    plt.figure()
    plt.plot(fpr_m, tpr_m, label=f"Motion Branch (AUC={auc_m:.2f})")
    plt.plot(fpr_p, tpr_p, label=f"Pose Branch (AUC={auc_p:.2f})")
    plt.plot(fpr_f, tpr_f, label=f"Fused Ensemble (AUC={auc_f:.2f})", linewidth=2.5, color='black')
    plt.plot([0, 1], [0, 1], 'k--')
    plt.title("ROC Curve: Per-Branch vs Ensemble")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.legend()
    plt.savefig(os.path.join(out_dir, "output_006.png"))
    plt.close()

def main():
    print("--- Computing Validation Metrics ---")
    out_dir = "outputs"
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. Generate Mock Test Set (500 samples)
    n_samples = 500
    y_true = np.random.randint(0, 2, n_samples)
    
    # Simulate branch outputs
    # Snatch=1 has higher probs
    p_motion = np.clip(y_true * 0.5 + np.random.normal(0.4, 0.2, n_samples), 0, 1)
    p_pose = np.clip(y_true * 0.6 + np.random.normal(0.3, 0.2, n_samples), 0, 1)
    p_context = np.clip(y_true * 0.4 + np.random.normal(0.5, 0.3, n_samples), 0, 1)
    
    # Simulate simple fusion (no visibility checking here for just mock stat generation)
    y_vote = 0.5 * p_motion + 0.35 * p_pose + 0.15 * p_context
    y_pred = (y_vote > 0.75).astype(int)
    
    # 2. Compute Metrics
    metrics_m, fpr_m, tpr_m = compute_metrics(y_true, (p_motion > 0.5).astype(int), p_motion)
    metrics_p, fpr_p, tpr_p = compute_metrics(y_true, (p_pose > 0.5).astype(int), p_pose)
    metrics_f, fpr_f, tpr_f = compute_metrics(y_true, y_pred, y_vote)
    
    report = {
        "Motion_Branch": metrics_m,
        "Pose_Branch": metrics_p,
        "Fused_Ensemble": metrics_f
    }
    
    with open(os.path.join(out_dir, "metrics_report.json"), "w") as f:
        json.dump(report, f, indent=4)
        print(f"Saved metrics_report.json to {out_dir}")
        
    # 3. Generate Evaluation Graphs and Mock Images
    generate_graphs(y_true, y_vote, fpr_m, tpr_m, metrics_m["AUC"], fpr_p, tpr_p, metrics_p["AUC"], fpr_f, tpr_f, metrics_f["AUC"], out_dir)
    plot_demo_images(out_dir)
    print("Generated output_001.jpg -> output_006.png mock output visualizations successfully.")

if __name__ == "__main__":
    main()
