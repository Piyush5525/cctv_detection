import torch
import torch.nn as nn
import torch.optim as optim
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models_arch.stgcn_arch import STGCN

def train_stgcn(save_path: str):
    """
    Train the ST-GCN Binary Classifer.
    Logs loss per epoch to console.
    """
    print("--- Starting ST-GCN Pose Classification Training ---")
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = STGCN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    print("Classes:")
    print(" 0: Hard Neg (walk, stand, push, adjust collar, etc.)")
    print(" 1: Targets (drag, neck-grab, chain-snatch)")

    # Dummy Training Loop
    epochs = 3
    for epoch in range(epochs):
        # mock inputs: (batch_size, num_nodes, node_features) = (32, 17, 2)
        node_features = torch.randn((32 * 17, 2)).to(device)
        edge_index = torch.randint(0, 17, (2, 50)).to(device) # dummy graph edges
        labels = torch.randint(0, 2, (1,)).to(device)
        
        optimizer.zero_grad()
        outputs = model(node_features, edge_index)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        print(f"Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}")
        
    torch.save(model.state_dict(), save_path)
    print(f"Saved STGCN checkpoint to {save_path}")

if __name__ == "__main__":
    train_stgcn('models/stgcn_snatch.pth')
