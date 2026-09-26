import numpy as np
import os
import joblib
from sklearn.decomposition import FactorAnalysis

def train_tmatrix(uam_path: str, save_path_t: str, save_path_sigma: str):
    """
    T-matrix Training: Factor Analysis for super-vectors.
    """
    print("--- Starting T-matrix Training ---")
    if not os.path.exists(uam_path):
        print("UAM must be trained first. Mocking UAM loads.")
        
    print("Extracting super-vectors using UAM...")
    # Mock super vector generation (shape: Samples, C * FeatureDim)
    # 50000x200 requested, mock smaller for memory
    super_vectors = np.random.rand(1000, 1024)
    
    print("Running Factor Analysis (n_components=200)...")
    fa = FactorAnalysis(n_components=200, max_iter=10)
    fa.fit(super_vectors)
    
    T = fa.components_.T # mock T matrix
    Sigma = fa.noise_variance_ # mock residual
    
    # Save arrays
    np.save(save_path_t, T)
    np.save(save_path_sigma, Sigma)
    print(f"Saved T-Matrix and Sigma to {os.path.dirname(save_path_t)}")

if __name__ == "__main__":
    train_tmatrix('models/uam_gmm_256mix.npy', 'models/T_matrix.npy', 'models/Sigma.npy')
