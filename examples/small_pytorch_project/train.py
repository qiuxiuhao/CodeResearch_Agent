import torch


def train_one_epoch(model):
    batch = torch.randn(2, 4)
    output = model(batch)
    loss = output.mean()
    return loss

