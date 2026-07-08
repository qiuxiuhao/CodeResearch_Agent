from __future__ import annotations

from dataclasses import dataclass


KNOWN_ROOTS = {"torch", "numpy", "np", "cv2", "cv", "PIL", "Image", "einops", "os", "pathlib", "json", "math", "random", "typing", "dataclasses"}

PACKAGE_ALIASES = {
    "np": "numpy",
    "cv": "cv2",
}

PACKAGE_CATEGORIES = {
    "torch": "pytorch",
    "numpy": "numpy",
    "cv2": "opencv",
    "PIL": "pil",
    "einops": "einops",
    "os": "python_stdlib",
    "pathlib": "python_stdlib",
    "json": "python_stdlib",
    "math": "python_stdlib",
    "random": "python_stdlib",
    "typing": "python_stdlib",
    "dataclasses": "python_stdlib",
}


@dataclass(frozen=True)
class ResolvedLibraryFunction:
    canonical_name: str
    display_name: str
    package_name: str | None
    category: str
    confidence: str


def resolve_library_function(display_name: str, aliases: dict[str, str]) -> ResolvedLibraryFunction:
    root, suffix = _split_root(display_name)
    if root in aliases:
        canonical_root = aliases[root]
        canonical_name = f"{canonical_root}{suffix}"
        package_name = _package_name(canonical_name)
        return ResolvedLibraryFunction(
            canonical_name=canonical_name,
            display_name=display_name,
            package_name=package_name,
            category=_category_for_package(package_name),
            confidence="high",
        )

    canonical_root = PACKAGE_ALIASES.get(root, root)
    if canonical_root in KNOWN_ROOTS or canonical_root in PACKAGE_CATEGORIES:
        canonical_name = f"{canonical_root}{suffix}"
        package_name = _package_name(canonical_name)
        return ResolvedLibraryFunction(
            canonical_name=canonical_name,
            display_name=display_name,
            package_name=package_name,
            category=_category_for_package(package_name),
            confidence="medium",
        )

    return ResolvedLibraryFunction(
        canonical_name=display_name,
        display_name=display_name,
        package_name=None,
        category="unknown",
        confidence="low",
    )


def _split_root(display_name: str) -> tuple[str, str]:
    if "." not in display_name:
        return display_name, ""
    root, remainder = display_name.split(".", 1)
    return root, f".{remainder}"


def _package_name(canonical_name: str) -> str | None:
    if not canonical_name:
        return None
    root = canonical_name.split(".", 1)[0]
    if root == "PIL":
        parts = canonical_name.split(".")
        return ".".join(parts[:2]) if len(parts) > 1 else "PIL"
    return root


def _category_for_package(package_name: str | None) -> str:
    if package_name is None:
        return "unknown"
    root = package_name.split(".", 1)[0]
    return PACKAGE_CATEGORIES.get(root, "third_party")

