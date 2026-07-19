from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.evaluation.schemas import EvaluationRun


@dataclass(frozen=True, slots=True)
class EvaluationCallerIdentity:
    identity_type: str
    subject: str
    repository_ids: frozenset[str] = field(default_factory=frozenset)


class EvaluationAccessPolicy(Protocol):
    def can_create_run(self, caller: EvaluationCallerIdentity) -> bool: ...
    def can_read_run(self, caller: EvaluationCallerIdentity, run: EvaluationRun) -> bool: ...
    def can_manage_baseline(self, caller: EvaluationCallerIdentity) -> bool: ...
    def can_manage_bad_cases(self, caller: EvaluationCallerIdentity) -> bool: ...
    def can_run_live_experiment(self, caller: EvaluationCallerIdentity) -> bool: ...


class LocalAdminEvaluationAccessPolicy:
    """Fail-closed until the application has a shared authentication system."""

    @staticmethod
    def _admin(caller: EvaluationCallerIdentity) -> bool:
        return caller.identity_type == "local_admin"

    def can_create_run(self, caller: EvaluationCallerIdentity) -> bool:
        return self._admin(caller)

    def can_read_run(self, caller: EvaluationCallerIdentity, run: EvaluationRun) -> bool:
        return self._admin(caller)

    def can_manage_baseline(self, caller: EvaluationCallerIdentity) -> bool:
        return self._admin(caller)

    def can_manage_bad_cases(self, caller: EvaluationCallerIdentity) -> bool:
        return self._admin(caller)

    def can_run_live_experiment(self, caller: EvaluationCallerIdentity) -> bool:
        return self._admin(caller)
