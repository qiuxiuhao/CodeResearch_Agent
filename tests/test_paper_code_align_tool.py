from __future__ import annotations

from backend.app.tools.paper_code_align_tool import align_paper_to_code


def test_align_paper_to_code_matches_model_targets():
    paper_analysis = {
        "paper_provided": True,
        "module_names": ["SimpleNet"],
        "contributions": [
            {
                "id": "C1",
                "title": "simplenet classifier head relu",
                "description": "We propose a SimpleNet classifier head with relu activation.",
                "keywords": ["simplenet", "classifier", "head", "relu"],
            }
        ],
    }

    alignment = align_paper_to_code(
        paper_analysis=paper_analysis,
        repo_index={"python_files": ["models/simple_model.py"]},
        file_analysis=[{"file_path": "models/simple_model.py", "file_type": "model", "purpose": "SimpleNet model"}],
        classes=[{"file_path": "models/simple_model.py", "class_name": "SimpleNet", "start_line": 5, "base_classes": ["nn.Module"]}],
        functions=[],
        function_analysis=[],
        model_analysis=[
            {
                "file_path": "models/simple_model.py",
                "class_name": "SimpleNet",
                "layers": [{"assigned_name": "self.fc1", "layer_type": "torch.nn.Linear", "role": "head", "line_no": 8, "evidence": ["fc1 layer"]}],
                "component_candidates": [{"name": "torch.nn.functional.relu", "role": "activation", "file_path": "models/simple_model.py", "line_no": 12, "evidence": ["relu call"]}],
            }
        ],
        library_calls=[],
    )

    assert alignment.paper_provided is True
    assert alignment.alignment_items[0].status == "matched"
    assert alignment.alignment_items[0].confidence in {"high", "medium"}
    assert alignment.alignment_items[0].matched_targets
    assert alignment.alignment_items[0].matched_targets[0].evidence


def test_align_paper_to_code_marks_unmatched_contributions():
    paper_analysis = {
        "paper_provided": True,
        "module_names": [],
        "contributions": [
            {
                "id": "C9",
                "title": "quantum tokenizer",
                "description": "We propose a quantum tokenizer for unrelated text.",
                "keywords": ["quantum", "tokenizer"],
            }
        ],
    }

    alignment = align_paper_to_code(paper_analysis, {"python_files": ["models/simple_model.py"]}, [], [], [], [], [], [])

    assert alignment.alignment_items[0].status == "unmatched"
    assert alignment.alignment_items[0].confidence == "low"
    assert alignment.unmatched_contributions[0].contribution_id == "C9"
    assert alignment.unmatched_contributions[0].contribution_title == "quantum tokenizer"
    assert alignment.unmatched_contributions[0].reason


def test_align_paper_to_code_does_not_match_generic_terms_only():
    paper_analysis = {
        "paper_provided": True,
        "module_names": [],
        "contributions": [
            {
                "id": "C2",
                "title": "simple model network framework",
                "description": "This paper presents a simple model network framework.",
                "keywords": ["simple", "model", "network", "framework"],
            }
        ],
    }

    alignment = align_paper_to_code(
        paper_analysis=paper_analysis,
        repo_index={"python_files": ["models/simple_model.py"]},
        file_analysis=[{"file_path": "models/simple_model.py", "file_type": "model", "purpose": "SimpleNet model"}],
        classes=[{"file_path": "models/simple_model.py", "class_name": "SimpleNet", "start_line": 5, "base_classes": ["nn.Module"]}],
        functions=[],
        function_analysis=[],
        model_analysis=[],
        library_calls=[],
    )

    assert alignment.alignment_items[0].status == "unmatched"
    assert alignment.alignment_items[0].confidence == "low"
    assert alignment.unmatched_contributions[0].reason


def test_align_paper_to_code_deduplicates_matched_targets():
    paper_analysis = {
        "paper_provided": True,
        "module_names": [],
        "contributions": [
            {
                "id": "C3",
                "title": "linear head",
                "description": "We propose a linear head for classification.",
                "keywords": ["linear", "head"],
            }
        ],
    }

    alignment = align_paper_to_code(
        paper_analysis=paper_analysis,
        repo_index={"python_files": ["models/simple_model.py"]},
        file_analysis=[],
        classes=[],
        functions=[],
        function_analysis=[],
        model_analysis=[
            {
                "file_path": "models/simple_model.py",
                "class_name": "SimpleNet",
                "layers": [
                    {
                        "assigned_name": "self.fc1",
                        "layer_type": "torch.nn.Linear",
                        "role": "head",
                        "line_no": 8,
                        "evidence": ["fc1 layer"],
                    }
                ],
                "component_candidates": [
                    {
                        "name": "self.fc1",
                        "role": "head",
                        "file_path": "models/simple_model.py",
                        "line_no": 8,
                        "evidence": ["fc1 component"],
                    }
                ],
            }
        ],
        library_calls=[],
    )

    matched_targets = alignment.alignment_items[0].matched_targets

    assert alignment.alignment_items[0].status == "matched"
    assert len([
        target
        for target in matched_targets
        if target.target_type == "model_module" and target.name == "self.fc1" and target.line_no == 8
    ]) == 1
