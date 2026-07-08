from __future__ import annotations

from backend.app.tools.mermaid_tool import generate_diagrams


def _sample_inputs(paper_provided: bool = True) -> dict:
    paper_analysis = {
        "paper_provided": paper_provided,
        "contributions": [
            {
                "id": "C1",
                "title": "SimpleNet classifier head",
                "description": "We propose a SimpleNet classifier head.",
                "evidence": ["abstract sentence"],
                "confidence": "high",
            }
        ] if paper_provided else [],
    }
    paper_code_alignment = {
        "paper_provided": paper_provided,
        "alignment_items": [
            {
                "contribution_id": "C1",
                "contribution_title": "SimpleNet classifier head",
                "status": "matched",
                "confidence": "high",
                "reason": "论文贡献文本精确包含代码目标名称。",
                "evidence": ["alignment evidence"],
                "matched_targets": [
                    {
                        "target_type": "class",
                        "name": "SimpleNet",
                        "file_path": "models/simple_model.py",
                        "qualified_name": "SimpleNet",
                        "line_no": 4,
                        "evidence": ["class target"],
                    }
                ],
            }
        ] if paper_provided else [],
        "unmatched_contributions": [],
    }
    return {
        "repo_index": {"python_files": ["main.py", "models/simple_model.py", "train.py"]},
        "file_analysis": [
            {
                "file_path": "main.py",
                "file_type": "entry",
                "purpose": "入口文件",
                "main_classes": [],
                "main_functions": ["main"],
                "evidence": ["入口候选"],
            },
            {
                "file_path": "models/simple_model.py",
                "file_type": "model",
                "purpose": "模型文件",
                "main_classes": ["SimpleNet"],
                "main_functions": [],
                "evidence": ["模型候选"],
            },
            {
                "file_path": "train.py",
                "file_type": "training",
                "purpose": "训练文件",
                "main_classes": [],
                "main_functions": ["train_one_epoch"],
                "evidence": ["训练候选"],
            },
        ],
        "function_analysis": [
            {
                "file_path": "models/simple_model.py",
                "qualified_name": "SimpleNet.forward",
                "function_name": "forward",
                "start_line": 10,
                "implementation_logic": ["调用模型层处理输入", "返回输出"],
                "called_internal_functions": [],
                "library_calls": [
                    {
                        "canonical_name": "torch.nn.functional.relu",
                        "file_path": "models/simple_model.py",
                        "qualified_function_name": "SimpleNet.forward",
                        "line_no": 11,
                        "call_text": "F.relu(x)",
                    }
                ],
                "outputs": ["logits"],
                "is_core_function": True,
                "evidence": ["forward 是核心函数"],
            },
            {
                "file_path": "train.py",
                "qualified_name": "train_one_epoch",
                "function_name": "train_one_epoch",
                "start_line": 8,
                "implementation_logic": ["构造输入", "调用模型"],
                "called_internal_functions": [],
                "library_calls": [],
                "outputs": ["loss"],
                "is_core_function": True,
                "evidence": ["训练函数"],
            },
            {
                "file_path": "main.py",
                "qualified_name": "main",
                "function_name": "main",
                "start_line": 3,
                "implementation_logic": ["加载配置", "启动训练"],
                "called_internal_functions": ["train_one_epoch"],
                "library_calls": [],
                "outputs": ["None"],
                "is_core_function": True,
                "evidence": ["入口函数"],
            },
        ],
        "model_analysis": [
            {
                "file_path": "models/simple_model.py",
                "class_name": "SimpleNet",
                "start_line": 4,
                "is_nn_module": True,
                "is_main_model_candidate": True,
                "model_inputs": ["x"],
                "model_outputs": ["self.fc2(hidden)"],
                "layers": [
                    {
                        "name": "fc1",
                        "assigned_name": "self.fc1",
                        "layer_type": "torch.nn.Linear",
                        "role": "head",
                        "line_no": 7,
                        "evidence": ["fc1 layer"],
                    },
                    {
                        "name": "fc2",
                        "assigned_name": "self.fc2",
                        "layer_type": "torch.nn.Linear",
                        "role": "head",
                        "line_no": 8,
                        "evidence": ["fc2 layer"],
                    },
                ],
                "forward_steps": [
                    {
                        "order": 1,
                        "calls": ["self.fc1", "torch.nn.functional.relu"],
                        "uses_layers": ["self.fc1"],
                        "line_no": 11,
                        "explanation": "调用 self.fc1 和 relu。",
                        "evidence": ["forward step 1"],
                    },
                    {
                        "order": 2,
                        "calls": ["self.fc2"],
                        "uses_layers": ["self.fc2"],
                        "line_no": 12,
                        "explanation": "调用 self.fc2。",
                        "evidence": ["forward step 2"],
                    },
                ],
                "component_candidates": [
                    {
                        "name": "self.fc1",
                        "role": "head",
                        "file_path": "models/simple_model.py",
                        "class_name": "SimpleNet",
                        "line_no": 7,
                        "evidence": ["head component"],
                        "confidence": "medium",
                    }
                ],
            }
        ],
        "paper_analysis": paper_analysis,
        "paper_code_alignment": paper_code_alignment,
        "library_calls": [],
    }


def test_generate_diagrams_builds_expected_diagram_types():
    inputs = _sample_inputs()

    result = generate_diagrams(**inputs)
    diagrams_by_type = {diagram.diagram_type: diagram for diagram in result.diagrams}

    assert "project_structure" in diagrams_by_type
    assert "model_flow" in diagrams_by_type
    assert "core_modules" in diagrams_by_type
    assert "paper_code_alignment" in diagrams_by_type
    assert any(diagram.diagram_type == "function_logic" for diagram in result.diagrams)
    assert "Project" in diagrams_by_type["project_structure"].mermaid
    assert "models/simple_model.py" in diagrams_by_type["project_structure"].mermaid
    assert "self.fc1" in diagrams_by_type["model_flow"].mermaid
    assert "self.fc2" in diagrams_by_type["model_flow"].mermaid
    assert "torch.nn.functional.relu" in diagrams_by_type["model_flow"].mermaid
    assert "C1" in diagrams_by_type["paper_code_alignment"].mermaid
    assert "SimpleNet" in diagrams_by_type["paper_code_alignment"].mermaid


def test_model_flow_connects_layer_and_activation_in_step_order():
    result = generate_diagrams(**_sample_inputs())
    model_flow = next(diagram for diagram in result.diagrams if diagram.id == "model_flow")
    edges = {(edge.source, edge.target) for edge in model_flow.edges}

    assert ("Input_x", "Layer_self_fc1") in edges
    assert ("Layer_self_fc1", "Call_N_1_torch_nn_functional_relu") in edges
    assert ("Call_N_1_torch_nn_functional_relu", "Layer_self_fc2") in edges
    assert any(edge.source == "Layer_self_fc2" and edge.target.startswith("Output_") for edge in model_flow.edges)
    assert not any(node.id == "Layer_self_fc1" and not any(edge.source == node.id or edge.target == node.id for edge in model_flow.edges) for node in model_flow.nodes)


def test_generate_diagrams_without_paper_skips_paper_diagram_and_warns():
    inputs = _sample_inputs(paper_provided=False)

    result = generate_diagrams(**inputs)

    assert len(result.diagrams) == 6
    assert all(diagram.diagram_type != "paper_code_alignment" for diagram in result.diagrams)
    assert any("未提供论文 PDF" in warning for warning in result.warnings)


def test_generate_diagrams_with_paper_keeps_paper_alignment_diagram():
    result = generate_diagrams(**_sample_inputs(paper_provided=True))

    assert len(result.diagrams) == 7
    assert any(diagram.diagram_type == "paper_code_alignment" for diagram in result.diagrams)


def test_generated_nodes_have_source_refs_except_group_nodes():
    result = generate_diagrams(**_sample_inputs())

    for diagram in result.diagrams:
        for node in diagram.nodes:
            if node.id.startswith(("Project", "Group_", "Paper_Unmatched")):
                continue
            assert node.source_refs, f"{diagram.id}:{node.id} missing source refs"


def test_mermaid_labels_are_escaped_and_edges_are_deduped():
    inputs = _sample_inputs()
    inputs["file_analysis"][0]["main_functions"] = ['main["bad"]']

    result = generate_diagrams(**inputs)
    project = next(diagram for diagram in result.diagrams if diagram.id == "project_structure")
    edge_keys = {(edge.source, edge.target, edge.label) for edge in project.edges}

    assert len(edge_keys) == len(project.edges)
    assert '\\"' not in project.mermaid
    assert "main('bad')" in project.mermaid


def test_function_logic_repeated_library_calls_do_not_create_self_loop():
    inputs = _sample_inputs(paper_provided=False)
    inputs["function_analysis"] = [
        {
            "file_path": "models/simple_model.py",
            "qualified_name": "SimpleNet.__init__",
            "function_name": "__init__",
            "start_line": 5,
            "implementation_logic": [],
            "called_internal_functions": [],
            "library_calls": [
                {
                    "canonical_name": "torch.nn.Linear",
                    "category": "torch",
                    "confidence": "high",
                    "file_path": "models/simple_model.py",
                    "qualified_function_name": "SimpleNet.__init__",
                    "line_no": 7,
                    "call_text": "nn.Linear(4, 8)",
                },
                {
                    "canonical_name": "torch.nn.Linear",
                    "category": "torch",
                    "confidence": "high",
                    "file_path": "models/simple_model.py",
                    "qualified_function_name": "SimpleNet.__init__",
                    "line_no": 8,
                    "call_text": "nn.Linear(8, 2)",
                },
            ],
            "outputs": [],
            "is_core_function": True,
            "evidence": ["构造模型层"],
        }
    ]

    result = generate_diagrams(**inputs)
    function_diagram = next(diagram for diagram in result.diagrams if diagram.diagram_type == "function_logic")

    assert all(edge.source != edge.target for edge in function_diagram.edges)
    assert "Function_SimpleNet_init_Lib_torch_nn_Linear_7" in function_diagram.mermaid
    assert "Function_SimpleNet_init_Lib_torch_nn_Linear_8" in function_diagram.mermaid


def test_function_logic_skips_low_confidence_unknown_calls():
    inputs = _sample_inputs(paper_provided=False)
    inputs["function_analysis"] = [
        {
            "file_path": "train.py",
            "qualified_name": "train_one_epoch",
            "function_name": "train_one_epoch",
            "start_line": 10,
            "implementation_logic": ["计算输出均值"],
            "called_internal_functions": [],
            "library_calls": [
                {
                    "canonical_name": "output.mean",
                    "category": "unknown",
                    "confidence": "low",
                    "file_path": "train.py",
                    "qualified_function_name": "train_one_epoch",
                    "line_no": 20,
                    "call_text": "output.mean()",
                }
            ],
            "outputs": ["loss"],
            "is_core_function": True,
            "evidence": ["训练函数"],
        }
    ]

    result = generate_diagrams(**inputs)
    function_diagram = next(diagram for diagram in result.diagrams if diagram.diagram_type == "function_logic")

    assert "output.mean" not in function_diagram.mermaid
    assert any("跳过低置信度 unknown 调用" in warning for warning in function_diagram.warnings)
