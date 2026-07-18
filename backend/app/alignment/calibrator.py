from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationExample:
    repo_paper_pair_id: str
    score: float
    label: int


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    probability: float
    sample_count: int


class IdentityCalibrator:
    profile_id = "identity-v1"

    def predict(self, score: float) -> float:
        return max(0.0, min(1.0, score))


class MonotonicBinningCalibrator:
    def __init__(self, bins: list[CalibrationBin], *, profile_id: str = "monotonic-bins-v1") -> None:
        self.bins = bins
        self.profile_id = profile_id

    @classmethod
    def fit(cls, examples: list[CalibrationExample], *, bin_count: int = 5) -> "MonotonicBinningCalibrator":
        if not examples:
            return cls([CalibrationBin(0.0, 1.0, 0.5, 0)])
        width = 1.0 / max(1, bin_count)
        raw: list[CalibrationBin] = []
        previous = 0.0
        for index in range(bin_count):
            lower = index * width
            upper = 1.0 if index == bin_count - 1 else (index + 1) * width
            selected = [item for item in examples if lower <= item.score <= upper if index == bin_count - 1 or item.score < upper]
            probability = (sum(item.label for item in selected) + 1) / (len(selected) + 2)
            probability = max(previous, probability)
            previous = probability
            raw.append(CalibrationBin(lower, upper, probability, len(selected)))
        return cls(raw)

    def predict(self, score: float) -> float:
        value = max(0.0, min(1.0, score))
        for item in self.bins:
            if item.lower <= value <= item.upper:
                return item.probability
        return self.bins[-1].probability


def leave_one_pair_out(examples: list[CalibrationExample]) -> dict[str, tuple[list[CalibrationExample], list[CalibrationExample]]]:
    pairs = sorted({item.repo_paper_pair_id for item in examples})
    return {
        pair: (
            [item for item in examples if item.repo_paper_pair_id != pair],
            [item for item in examples if item.repo_paper_pair_id == pair],
        )
        for pair in pairs
    }
