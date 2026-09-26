import torch
import torch.nn as nn
import torch.optim as optim
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models_arch.cnn_lstm_arch import CNNLSTMContextBranch

def train_context(save_path: str):
    """
    Train the CNN-LSTM context branch.
    Logs loss per epoch to console.
    """
    print("--- Starting CNN-LSTM Context Branch Training ---")
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = CNNLSTMContextBranch().to(device)
    criterion = nn.BCELoss()
    optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=0.001)

    # Dummy Training Loop
    epochs = 3
    for epoch in range(epochs):
        # mock inputs: (batch, seq_len, C, H, W)
        x = torch.randn((8, 16, 3, 224, 224)).to(device)
        labels = torch.rand((8, 1)).to(device)
        
        optimizer.zero_grad()
        outputs = model(x)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        print(f"Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}")
        
    torch.save(model.state_dict(), save_path)
    print(f"Saved CNN-LSTM Context checkpoint to {save_path}")

if __name__ == "__main__":
    train_context('models/cnn_lstm_context.pth')
