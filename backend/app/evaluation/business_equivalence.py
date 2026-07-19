from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from backend.app.evaluation.schemas import BusinessEquivalenceContract
from backend.app.evaluation.stable_ids import canonical_json


class BusinessEquivalenceResult:
    def __init__(self, equivalent: bool, differences: list[str]) -> None:
        self.equivalent = equivalent
        self.differences = differences


def compare_business_outputs(
    left: dict[str, Any], right: dict[str, Any], contract: BusinessEquivalenceContract
) -> BusinessEquivalenceResult:
    left_value = _normalize(deepcopy(left), contract)
    right_value = _normalize(deepcopy(right), contract)
    differences: list[str] = []
    for path in contract.required_equal_fields:
        _compare(_get(left_value, path), _get(right_value, path), path, contract, differences)
    return BusinessEquivalenceResult(not differences, differences)


def _normalize(value: dict[str, Any], contract: BusinessEquivalenceContract) -> dict[str, Any]:
    for path in contract.ignored_fields:
        _delete(value, path)
    for path in contract.order_insensitive_fields:
        item = _get(value, path)
        if isinstance(item, list):
            item.sort(key=canonical_json)
    return value


def _compare(
    left: Any,
    right: Any,
    path: str,
    contract: BusinessEquivalenceContract,
    differences: list[str],
) -> None:
    tolerance = contract.float_tolerances.get(path)
    if tolerance is not None and isinstance(left, (float, int)) and isinstance(right, (float, int)):
        if not math.isclose(float(left), float(right), abs_tol=tolerance, rel_tol=0):
            differences.append(path)
    elif left != right:
        differences.append(path)


def _get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _delete(value: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current: Any = value
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if isinstance(current, dict):
        current.pop(parts[-1], None)
