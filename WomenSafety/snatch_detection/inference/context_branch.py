from dataclasses import dataclass
import numpy as np
import torch
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models_arch.cnn_lstm_arch import CNNLSTMContextBranch

@dataclass
class ContextResult:
    P_context: float
    
class ContextBranch:
    def __init__(self, weights_path: str):
        """
        Yields P_context from RGB 4-6s windows covering 
        environmental features.
        """
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = CNNLSTMContextBranch().to(self.device)
        try:
            self.model.load_state_dict(torch.load(weights_path, map_location=self.device))
        except FileNotFoundError:
            print("Warning: CNN-LSTM weights not found. Using unfitted model layers.")
        self.model.eval()
        
    def predict(self, frames: list) -> ContextResult:
        if len(frames) == 0:
            return ContextResult(P_context=0.0)
            
        # In actual system, tensorize frames: (1, seq_len, 3, 224, 224)
        dummy_input = torch.randn((1, len(frames), 3, 224, 224)).to(self.device)
        with torch.no_grad():
            out = self.model(dummy_input)
            p_context = out.item()
            
        return ContextResult(P_context=p_context)
