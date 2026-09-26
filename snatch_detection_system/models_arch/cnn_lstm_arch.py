import torch
import torch.nn as nn
from torchvision.models import resnet18, ResNet18_Weights

class CNNLSTMContextBranch(nn.Module):
    def __init__(self, hidden_size=256, num_layers=2):
        """
        ResNet-18 CNN + 2-layer LSTM context model.
        Extracts 512-d feature vector per frame.
        Evaluates 4-6s window yielding P_context.
        """
        super(CNNLSTMContextBranch, self).__init__()
        # Pretrained ResNet-18 backbone
        self.cnn = resnet18(weights=ResNet18_Weights.DEFAULT)
        # Freeze early layers
        for param in list(self.cnn.parameters())[:-10]:
            param.requires_grad = False
            
        # Removing the fully connected layer to output 512 embedding
        self.cnn.fc = nn.Identity()
        
        # LSTM over sequential frames
        self.lstm = nn.LSTM(
            input_size=512,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.5
        )
        
        # Fully connected binary classification
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        # x shape: (batch_size, seq_len, C, H, W)
        batch_size, seq_len, C, H, W = x.size()
        
        # Flatten for CNN
        c_in = x.view(batch_size * seq_len, C, H, W)
        c_out = self.cnn(c_in) # shape: (batch_size * seq_len, 512)
        
        # Reshape for LSTM
        r_in = c_out.view(batch_size, seq_len, -1)
        lstm_out, (hn, cn) = self.lstm(r_in)
        
        # Take the last output of the sequence
        last_out = lstm_out[:, -1, :] # shape: (batch_size, hidden_size)
        
        # Sigmoid output P_context in [0, 1]
        out = torch.sigmoid(self.fc(last_out))
        return out
