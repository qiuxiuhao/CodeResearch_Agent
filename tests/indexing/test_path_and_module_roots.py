from __future__ import annotations

import unicodedata

import pytest

from backend.app.indexing.module_roots import discover_module_roots, module_name_for_path
from backend.app.indexing.path_normalizer import normalize_index_path


def test_path_normalization_is_cross_platform_and_case_preserving() -> None:
    composed = "caf\N{LATIN SMALL LETTER E WITH ACUTE}.py"
    decomposed = unicodedata.normalize("NFD", composed)

    assert normalize_index_path("./Pkg\\module.py") == "Pkg/module.py"
    assert normalize_index_path(decomposed) == composed
    assert normalize_index_path("Pkg/A.py") != normalize_index_path("pkg/a.py")
    for invalid in ("/tmp/a.py", "C:\\repo\\a.py", "C:a.py", "//server/share/a.py", "../a.py", "a/../b.py"):
        with pytest.raises(ValueError):
            normalize_index_path(invalid)


def test_module_roots_prefer_explicit_then_src_then_repository(tmp_path) -> None:
    (tmp_path / "lib" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "other").mkdir(parents=True)
    (tmp_path / "root_pkg").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[tool.setuptools.packages.find]\nwhere = ['lib']\n", encoding="utf-8"
    )

    roots = discover_module_roots(tmp_path)
    assert roots == ["lib", "src", "."]
    assert module_name_for_path("lib/pkg/model.py", roots) == ("pkg.model", ["pkg.model"])
    assert module_name_for_path("src/other/tool.py", roots) == ("other.tool", ["other.tool"])
    assert module_name_for_path("root_pkg/main.py", roots) == ("root_pkg.main", ["root_pkg.main"])


def test_repository_root_requires_classic_packages_but_src_allows_namespace(tmp_path) -> None:
    (tmp_path / "classic" / "nested").mkdir(parents=True)
    (tmp_path / "classic" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "classic" / "nested" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "classic" / "nested" / "ok.py").write_text("", encoding="utf-8")
    (tmp_path / "loose").mkdir()
    (tmp_path / "loose" / "unknown.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "namespace").mkdir(parents=True)
    (tmp_path / "src" / "namespace" / "ok.py").write_text("", encoding="utf-8")

    roots = discover_module_roots(tmp_path)
    assert module_name_for_path("classic/nested/ok.py", roots, tmp_path) == (
        "classic.nested.ok", ["classic.nested.ok"]
    )
    assert module_name_for_path("src/namespace/ok.py", roots, tmp_path) == ("namespace.ok", ["namespace.ok"])
    assert module_name_for_path("loose/unknown.py", roots, tmp_path) == ("loose.unknown", [])
