import time
import argparse
from training.train_uam import train_uam
from training.train_tmatrix import train_tmatrix
from training.train_svm import train_svm
from training.train_stgcn import train_stgcn
from training.train_context import train_context

def main():
    parser = argparse.ArgumentParser(description="Offline Training Pipeline for Snatch Detection.")
    parser.add_argument('--data_dir', type=str, default='data/', help='Path to data directories')
    parser.add_argument('--models_dir', type=str, default='models/', help='Path to save models')
    args = parser.parse_args()

    print("========================================")
    print("= Starting Full Offline Training Suite =")
    print("========================================")
    start_time = time.time()
    
    t0 = time.time()
    train_uam(f"{args.data_dir}normal_clips", f"{args.models_dir}uam_gmm_256mix.npy")
    print(f"[Done] UAM Training: {time.time()-t0:.2f}s\n")
    
    t0 = time.time()
    train_tmatrix(f"{args.models_dir}uam_gmm_256mix.npy", f"{args.models_dir}T_matrix.npy", f"{args.models_dir}Sigma.npy")
    print(f"[Done] T-Matrix Training: {time.time()-t0:.2f}s\n")
    
    t0 = time.time()
    train_svm(f"{args.models_dir}T_matrix.npy", f"{args.models_dir}Sigma.npy", f"{args.data_dir}annotations.csv", f"{args.models_dir}svm_action_vector.pkl")
    print(f"[Done] SVM Training: {time.time()-t0:.2f}s\n")
    
    t0 = time.time()
    train_stgcn(f"{args.models_dir}stgcn_snatch.pth")
    print(f"[Done] ST-GCN Training: {time.time()-t0:.2f}s\n")
    
    t0 = time.time()
    train_context(f"{args.models_dir}cnn_lstm_context.pth")
    print(f"[Done] CNN-LSTM Training: {time.time()-t0:.2f}s\n")

    print(f"========================================")
    print(f"All training complete in {time.time()-start_time:.2f} seconds.")
    print(f"Models saved into {args.models_dir}")

if __name__ == "__main__":
    main()
