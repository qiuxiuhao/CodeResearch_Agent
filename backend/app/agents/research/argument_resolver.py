from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from backend.app.agents.research.schemas import PlanStep, ToolObservation
from backend.app.agents.research.tool_registry import ToolRegistry


class ArgumentResolutionError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ResolvedStepArguments:
    model: BaseModel
    canonical_json: str
    arguments_hash: str


class StepArgumentResolver:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        step: PlanStep,
        observations: list[ToolObservation],
        *,
        plan_version: str | None = None,
    ) -> ResolvedStepArguments:
        values = dict(step.literal_arguments)
        by_step = {
            item.step_id: item
            for item in observations
            if item.status in {"success", "empty"}
            and (plan_version is None or item.plan_version == plan_version)
        }
        for binding in step.argument_bindings:
            reference = binding.from_step
            observation = by_step.get(reference.step_id)
            candidates = list(getattr(observation, reference.field)) if observation else []
            selected = _select(candidates, reference.selection, reference.index)
            if selected is None or selected == []:
                if reference.required:
                    raise ArgumentResolutionError(
                        "required_step_output_missing",
                        f"Required output {reference.step_id}.{reference.field} is missing.",
                    )
                continue
            values[binding.argument_name] = selected
        spec = self.registry.get(step.tool_name)
        try:
            model = spec.input_model.model_validate(values)
        except ValidationError as exc:
            raise ArgumentResolutionError("invalid_tool_arguments", str(exc)) from exc
        canonical = canonical_arguments(model.model_dump(mode="json"))
        return ResolvedStepArguments(model, canonical, _sha(canonical))


def step_execution_id(run_id: str, plan_version: str, step_id: str) -> str:
    return _sha(f"{run_id}\0{plan_version}\0{step_id}")


def semantic_tool_call_key(
    *, run_id: str, repo_id: str, index_version_id: str, tool_name: str, canonical_arguments_json: str
) -> str:
    return _sha(
        "\0".join([run_id, repo_id, index_version_id, tool_name, canonical_arguments_json])
    )


def canonical_arguments(value: object) -> str:
    normalized = _normalize(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _select(values: list[str], selection: str, index: int | None):
    if index is not None:
        return values[index] if index < len(values) else None
    if selection == "first":
        return values[0] if values else None
    if selection == "unique":
        return list(dict.fromkeys(values))
    return values


def _normalize(value: object):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
