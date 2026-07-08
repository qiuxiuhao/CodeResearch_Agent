from models.simple_model import SimpleNet
from train import train_one_epoch


def main():
    model = SimpleNet(input_dim=4, hidden_dim=8, output_dim=2)
    train_one_epoch(model)


if __name__ == "__main__":
    main()

