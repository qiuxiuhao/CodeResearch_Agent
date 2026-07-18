from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel

from backend.app.agents.research.budget import AgentBudget
from backend.app.agents.research.schemas import ResearchPlan
from backend.app.agents.research.tool_registry import ToolRegistry


class PlanValidationError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class PlanValidator:
    def __init__(self, registry: ToolRegistry, budget: AgentBudget | None = None) -> None:
        self.registry = registry
        self.budget = budget or AgentBudget()

    def validate(self, plan: ResearchPlan) -> ResearchPlan:
        self.budget.validate_plan_size(len(plan.steps))
        ordered = sorted(plan.steps, key=lambda item: item.ordinal)
        if [step.ordinal for step in ordered] != list(range(len(ordered))):
            raise PlanValidationError("plan_invalid", "Plan ordinals must be contiguous from zero.")
        by_id = {step.step_id: step for step in ordered}
        if len(by_id) != len(ordered):
            raise PlanValidationError("plan_invalid", "Plan step IDs must be unique.")
        for step in ordered:
            if not self.registry.has(step.tool_name):
                raise PlanValidationError("tool_not_allowed", f"Unknown tool {step.tool_name}.")
            spec = self.registry.get(step.tool_name)
            properties = spec.input_model.model_fields
            unknown_literals = set(step.literal_arguments).difference(properties)
            if unknown_literals:
                raise PlanValidationError("invalid_tool_arguments", str(sorted(unknown_literals)))
            for dependency in step.dependencies:
                self._require_prior(step.ordinal, dependency, by_id)
            for binding in step.argument_bindings:
                source = self._require_prior(step.ordinal, binding.from_step.step_id, by_id)
                if source.step_id not in step.dependencies:
                    raise PlanValidationError(
                        "step_binding_invalid", "A bound source step must also be a dependency."
                    )
                source_spec = self.registry.get(source.tool_name)
                if binding.from_step.field not in source_spec.output_fields:
                    raise PlanValidationError("step_binding_invalid", "Unknown tool output field.")
                if binding.argument_name not in properties:
                    raise PlanValidationError("invalid_tool_arguments", binding.argument_name)
                multi = binding.from_step.selection in {"all", "unique"}
                if multi != _expects_collection(properties[binding.argument_name].annotation):
                    raise PlanValidationError("step_binding_cardinality", binding.argument_name)
            self._validate_partial_literals(spec.input_model, step.literal_arguments)
        return plan.model_copy(update={"steps": ordered})

    @staticmethod
    def _require_prior(ordinal: int, step_id: str, by_id: dict):
        source = by_id.get(step_id)
        if source is None or source.ordinal >= ordinal:
            raise PlanValidationError("step_reference_invalid", f"Step {step_id} is not a prior step.")
        return source

    @staticmethod
    def _validate_partial_literals(model: type[BaseModel], values: dict) -> None:
        for name, value in values.items():
            field = model.model_fields[name]
            from pydantic import TypeAdapter

            try:
                TypeAdapter(field.annotation).validate_python(value)
            except Exception as exc:
                raise PlanValidationError("invalid_tool_arguments", name) from exc


def _expects_collection(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin in {list, set, tuple}:
        return True
    return any(_expects_collection(item) for item in get_args(annotation))
