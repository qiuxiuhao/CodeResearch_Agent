class TinyDataset:
    def __len__(self):
        return 2

    def __getitem__(self, index):
        return index

