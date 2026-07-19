from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.observability.schemas import AttributeDefinition, JsonValue


REGISTRY_VERSION = "cra-attributes-v1"
OPERATION_TAXONOMY_VERSION = "cra-operations-v1"


def _definition(
    key: str,
    value_type: str,
    *,
    cardinality: str = "bounded",
    diagnostic: bool = False,
    metric: bool = False,
) -> AttributeDefinition:
    return AttributeDefinition(
        key=key,
        value_type=value_type,
        cardinality=cardinality,
        content_policy="diagnostic_metadata" if diagnostic else "metadata",
        metric_label_allowed=metric,
        introduced_in=REGISTRY_VERSION,
    )


ATTRIBUTE_DEFINITIONS = {
    item.key: item
    for item in (
        _definition("cra.trace.type", "string", metric=True),
        _definition("cra.component", "string", metric=True),
        _definition("cra.operation", "string", metric=True),
        _definition("cra.request.id", "string", cardinality="high"),
        _definition("cra.run.id", "string", cardinality="high"),
        _definition("cra.task.id", "string", cardinality="high"),
        _definition("cra.repo.id", "string", cardinality="high"),
        _definition("cra.index.version_id", "string", cardinality="high"),
        _definition("cra.generation.id", "string", cardinality="high"),
        _definition("cra.profile.hash", "string", cardinality="high"),
        _definition("cra.graph.version", "string"),
        _definition("cra.model.profile", "string", cardinality="high"),
        _definition("cra.scorer.profile", "string", cardinality="high"),
        _definition("cra.status", "string", metric=True),
        _definition("cra.error.code", "string", metric=True),
        _definition("cra.retry.count", "integer"),
        _definition("cra.fallback.reason", "string", metric=True),
        _definition("cra.cancel.requested", "boolean"),
        _definition("cra.count", "integer"),
        _definition("cra.candidate.count", "integer"),
        _definition("cra.context.count", "integer"),
        _definition("cra.evidence.count", "integer"),
        _definition("cra.latency.phase", "string", metric=True),
        _definition("cra.duration.ms", "number"),
        _definition("cra.retrieval.channel", "string", metric=True),
        _definition("cra.retrieval.empty", "boolean", metric=True),
        _definition("cra.provider.name", "string", metric=True),
        _definition("cra.provider.model", "string"),
        _definition("cra.provider.revision", "string"),
        _definition("cra.provider.task_type", "string", metric=True),
        _definition("cra.prompt.version", "string"),
        _definition("cra.token.input", "integer"),
        _definition("cra.token.output", "integer"),
        _definition("cra.token.total", "integer"),
        _definition("cra.cache.hit", "boolean", metric=True),
        _definition("cra.route", "string", metric=True),
        _definition("cra.tool.name", "string", metric=True),
        _definition("cra.tool.reused", "boolean", metric=True),
        _definition("cra.checkpoint.operation", "string", metric=True),
        _definition("cra.database.operation", "string", metric=True),
        _definition("cra.replan.count", "integer"),
        _definition("cra.alignment.status", "string", metric=True),
        _definition("cra.evaluation.component", "string", metric=True),
        _definition("cra.evaluation.mode", "string", metric=True),
        _definition("cra.evaluation.case_count", "integer"),
        _definition("cra.dataset.version", "string", cardinality="high"),
        _definition("cra.subject.id", "string", cardinality="high"),
        _definition("cra.authority.level", "string"),
        _definition("cra.http.method", "string", metric=True),
        _definition("cra.http.route", "string", metric=True),
        _definition("cra.http.status_code", "integer", metric=True),
        _definition("cra.remote_parent.mode", "string", metric=True),
        _definition("cra.telemetry.complete", "boolean", metric=True),
        _definition("cra.warning.code", "string", diagnostic=True),
    )
}


class AttributeRegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AttributeRegistry:
    version: str = REGISTRY_VERSION

    def sanitize(self, attributes: dict[str, Any], *, diagnostics: bool) -> dict[str, JsonValue]:
        output: dict[str, JsonValue] = {}
        for key, value in attributes.items():
            definition = ATTRIBUTE_DEFINITIONS.get(key)
            if definition is None:
                continue
            if definition.removed_in is not None:
                continue
            if definition.content_policy == "diagnostic_metadata" and not diagnostics:
                continue
            if not _matches_type(value, definition.value_type):
                raise AttributeRegistryError(f"invalid value type for {key}")
            output[key] = value
        return output

    def comparison_compatibility(self, other_version: str) -> str:
        if other_version == self.version:
            return "compatible"
        prefix = "cra-attributes-v"
        if self.version.startswith(prefix) and other_version.startswith(prefix):
            try:
                if abs(int(self.version[len(prefix):]) - int(other_version[len(prefix):])) == 1:
                    return "partially_compatible"
            except ValueError:
                pass
        return "incompatible"


def _matches_type(value: object, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False
