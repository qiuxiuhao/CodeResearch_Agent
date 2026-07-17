from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.domain.entities import CodeEntity


@dataclass(frozen=True)
class SymbolCandidate:
    entity_id: str
    qualified_name: str
    module_name: str
    name: str
    entity_type: str
    path: str
    declaration_ordinal: int | None
    duplicate_symbol: bool
    duplicate_resolution_safe: bool


@dataclass
class SymbolTable:
    by_qualified_name: dict[str, list[SymbolCandidate]] = field(default_factory=dict)
    by_short_name: dict[str, list[SymbolCandidate]] = field(default_factory=dict)
    modules: dict[str, list[SymbolCandidate]] = field(default_factory=dict)
    entities_by_id: dict[str, CodeEntity] = field(default_factory=dict)

    def resolve(self, qualified_name: str) -> list[SymbolCandidate]:
        return list(self.by_qualified_name.get(qualified_name, []))


def build_symbol_table(entities: list[CodeEntity]) -> SymbolTable:
    table = SymbolTable(entities_by_id={entity.id: entity for entity in entities})
    for entity in entities:
        candidate = SymbolCandidate(
            entity_id=entity.id,
            qualified_name=entity.qualified_name,
            module_name=entity.module_name or "",
            name=entity.name,
            entity_type=entity.entity_type,
            path=entity.path,
            declaration_ordinal=_int_or_none(entity.metadata.get("declaration_ordinal")),
            duplicate_symbol=bool(entity.metadata.get("duplicate_symbol", False)),
            duplicate_resolution_safe=bool(entity.metadata.get("duplicate_resolution_safe", True)),
        )
        table.by_qualified_name.setdefault(entity.qualified_name, []).append(candidate)
        table.by_short_name.setdefault(entity.name, []).append(candidate)
        if entity.entity_type in {"file", "config", "training_entry", "inference_entry", "dataset"}:
            table.modules.setdefault(entity.qualified_name, []).append(candidate)
    for mapping in (table.by_qualified_name, table.by_short_name, table.modules):
        for candidates in mapping.values():
            candidates.sort(key=lambda item: (item.declaration_ordinal or 0, item.path, item.entity_id))
    return table


def select_candidates(candidates: list[SymbolCandidate]) -> tuple[SymbolCandidate | None, str]:
    if not candidates:
        return None, "unresolved"
    if len(candidates) == 1:
        return candidates[0], "exact"
    if all(item.duplicate_symbol and item.duplicate_resolution_safe for item in candidates):
        return candidates[-1], "duplicate_last_definition"
    return None, "ambiguous"


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
