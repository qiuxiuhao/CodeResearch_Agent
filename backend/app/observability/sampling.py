from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.app.observability.schemas import RecordingDecision, TraceType


@dataclass(frozen=True, slots=True)
class DeterministicSampler:
    metadata_enabled: bool = True
    diagnostic_rate: float = 0.0
    otlp_rate: float = 0.0
    seed: str = "cra-observability-v1"

    def decide(self, trace_id: str, trace_type: TraceType) -> RecordingDecision:
        value = _fraction(f"{self.seed}:{trace_type}:{trace_id}")
        diagnostics = self.metadata_enabled and value < max(0.0, min(1.0, self.diagnostic_rate))
        otlp = value < max(0.0, min(1.0, self.otlp_rate))
        reasons = ["metadata_enabled" if self.metadata_enabled else "metadata_disabled"]
        if diagnostics:
            reasons.append("diagnostic_head_sample")
        if otlp:
            reasons.append("otlp_head_sample")
        return RecordingDecision(
            record_metadata=self.metadata_enabled,
            record_diagnostics=diagnostics,
            export_otlp=otlp,
            reason_codes=reasons,
        )


def _fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)
