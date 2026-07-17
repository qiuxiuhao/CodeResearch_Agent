from __future__ import annotations

from backend.app.domain.entities import CodeEntity
from backend.app.indexing.call_graph_builder import build_call_edges
from backend.app.indexing.import_resolver import resolve_imports, resolve_relative_module
from backend.app.indexing.inheritance_resolver import build_inheritance_edges
from backend.app.indexing.stable_ids import code_entity_id, repository_identity, text_content_hash
from backend.app.indexing.symbol_table_builder import build_symbol_table, select_candidates


REPO_ID = repository_identity("symbols")[0]


def _entity(
    entity_type: str,
    path: str,
    qualified: str,
    *,
    duplicate: int | None = None,
    duplicate_safe: bool = True,
) -> CodeEntity:
    return CodeEntity(
        id=code_entity_id(REPO_ID, entity_type, path, qualified, duplicate),
        repo_id=REPO_ID,
        entity_type=entity_type,
        path=path,
        name=qualified.rsplit(".", 1)[-1],
        qualified_name=qualified,
        module_name=(
            qualified if entity_type == "file"
            else ".".join(qualified.split(".")[:2]) if entity_type in {"method", "class"}
            else qualified.rsplit(".", 1)[0]
        ),
        content_hash=text_content_hash(qualified),
        metadata={
            "duplicate_symbol": duplicate is not None,
            "declaration_ordinal": duplicate,
            "duplicate_resolution_safe": duplicate_safe,
        },
    )


def test_duplicate_symbols_are_candidate_lists_and_last_definition_wins() -> None:
    first = _entity("function", "pkg/a.py", "pkg.a.run", duplicate=1)
    second = _entity("function", "pkg/a.py", "pkg.a.run", duplicate=2)
    table = build_symbol_table([first, second])

    assert [item.entity_id for item in table.resolve("pkg.a.run")] == [first.id, second.id]
    selected, resolution = select_candidates(table.resolve("pkg.a.run"))
    assert selected == table.resolve("pkg.a.run")[-1]
    assert resolution == "duplicate_last_definition"

    unsafe = build_symbol_table([
        _entity("function", "pkg/b.py", "pkg.b.run", duplicate=1, duplicate_safe=False),
        _entity("function", "pkg/b.py", "pkg.b.run", duplicate=2, duplicate_safe=False),
    ])
    selected, resolution = select_candidates(unsafe.resolve("pkg.b.run"))
    assert selected is None
    assert resolution == "ambiguous"


def test_import_alias_from_import_relative_and_unresolved_are_retained() -> None:
    module = _entity("file", "pkg/layers.py", "pkg.layers")
    layer = _entity("class", "pkg/layers.py", "pkg.layers.Layer")
    source = _entity("file", "pkg/model.py", "pkg.model")
    table = build_symbol_table([module, layer, source])
    parsed = [{
        "file_path": "pkg/model.py",
        "imports": [
            {"module": ".layers", "name": "Layer", "alias": "L", "import_type": "from_import", "line_no": 1},
            {"module": "missing", "name": "thing", "alias": None, "import_type": "from_import", "line_no": 2},
        ],
    }]

    bindings, edges, evidence = resolve_imports(
        repo_id=REPO_ID, parsed_files=parsed, table=table, module_roots=["."]
    )

    assert resolve_relative_module("..common", "pkg.sub.mod", False) == "pkg.common"
    assert bindings["pkg/model.py"]["L"].target.entity_id == layer.id
    assert bindings["pkg/model.py"]["L"].resolution_type == "alias"
    assert any(edge.target_id == layer.id for edge in edges)
    unresolved = next(edge for edge in edges if edge.target_id is None)
    assert unresolved.resolution_type == "unresolved"
    assert unresolved.unresolved_symbol == "missing.thing"
    assert evidence


def test_call_graph_resolves_local_self_method_model_forward_and_unresolved() -> None:
    model_file = _entity("file", "pkg/model.py", "pkg.model")
    layer_file = _entity("file", "pkg/layers.py", "pkg.layers")
    model = _entity("class", "pkg/model.py", "pkg.model.Model")
    layer = _entity("class", "pkg/layers.py", "pkg.layers.Layer")
    init = _entity("method", "pkg/model.py", "pkg.model.Model.__init__")
    run = _entity("method", "pkg/model.py", "pkg.model.Model.run")
    helper = _entity("method", "pkg/model.py", "pkg.model.Model.helper")
    forward = _entity("method", "pkg/layers.py", "pkg.layers.Layer.forward")
    local = _entity("function", "pkg/model.py", "pkg.model.local")
    table = build_symbol_table([model_file, layer_file, model, layer, init, run, helper, forward, local])
    parsed = [{
        "file_path": "pkg/model.py",
        "imports": [{"module": ".layers", "name": "Layer", "alias": None, "import_type": "from_import", "line_no": 1}],
    }]
    bindings, _, _ = resolve_imports(repo_id=REPO_ID, parsed_files=parsed, table=table, module_roots=["."])
    functions = [
        {
            "file_path": "pkg/model.py", "class_name": "Model", "function_name": "__init__", "start_line": 3,
            "source_code": "def __init__(self):\n    self.layer = Layer()",
        },
        {
            "file_path": "pkg/model.py", "class_name": "Model", "function_name": "run", "start_line": 6,
            "source_code": (
                "def run(self, x):\n"
                "    self.helper()\n"
                "    local()\n"
                "    self.layer(x)\n"
                "    unknown(x)"
            ),
        },
    ]
    edges, evidence = build_call_edges(
        repo_id=REPO_ID, functions=functions, table=table,
        import_bindings=bindings, module_roots=["."],
    )

    target_types = {(edge.target_id, edge.resolution_type) for edge in edges}
    assert (helper.id, "self_method") in target_types
    assert (local.id, "exact") in target_types
    assert (forward.id, "model_forward") in target_types
    assert any(edge.unresolved_symbol == "unknown" and edge.resolution_type == "unresolved" for edge in edges)
    assert all(edge.evidence_refs for edge in edges)
    assert evidence


def test_circular_imports_and_inheritance_resolve_without_recursive_loading() -> None:
    file_a = _entity("file", "pkg/a.py", "pkg.a")
    file_b = _entity("file", "pkg/b.py", "pkg.b")
    base = _entity("class", "pkg/a.py", "pkg.a.Base")
    child = _entity("class", "pkg/b.py", "pkg.b.Child")
    child.metadata["base_classes"] = ["Base"]
    table = build_symbol_table([file_a, file_b, base, child])
    parsed = [
        {"file_path": "pkg/a.py", "imports": [
            {"module": ".b", "name": "Child", "alias": None, "import_type": "from_import", "line_no": 1}
        ]},
        {"file_path": "pkg/b.py", "imports": [
            {"module": ".a", "name": "Base", "alias": None, "import_type": "from_import", "line_no": 1}
        ]},
    ]
    bindings, import_edges, _ = resolve_imports(
        repo_id=REPO_ID, parsed_files=parsed, table=table, module_roots=["."]
    )
    inherit_edges, _ = build_inheritance_edges(REPO_ID, table, bindings)

    assert {edge.target_id for edge in import_edges} == {base.id, child.id}
    assert any(edge.source_id == child.id and edge.target_id == base.id for edge in inherit_edges)
