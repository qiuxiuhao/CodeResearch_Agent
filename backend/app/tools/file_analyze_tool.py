from __future__ import annotations

from pathlib import Path

from backend.app.schemas.file_analysis import FileAnalysis


ENTRY_NAMES = {"main.py", "app.py", "run.py", "cli.py", "__main__.py"}
INFERENCE_KEYWORDS = ("infer", "predict", "demo", "eval")
DATASET_KEYWORDS = ("data/", "dataset", "datasets", "loader", "dataloader")
UTILITY_KEYWORDS = ("utils", "helper", "common", "misc")


def analyze_files(
    repo_index: dict,
    parsed_files: list[dict],
    classes: list[dict],
    functions: list[dict],
) -> list[FileAnalysis]:
    parsed_by_path = {item.get("file_path"): item for item in parsed_files}
    classes_by_path = _group_by_file(classes)
    functions_by_path = _group_by_file(functions)

    analyses: list[FileAnalysis] = []
    for file_path in repo_index.get("python_files", []):
        parsed_file = parsed_by_path.get(file_path, {"file_path": file_path, "imports": [], "errors": []})
        file_classes = classes_by_path.get(file_path, parsed_file.get("classes", []))
        file_functions = functions_by_path.get(file_path, parsed_file.get("functions", []))
        analyses.append(_analyze_single_file(repo_index, parsed_file, file_classes, file_functions))
    return analyses


def _analyze_single_file(
    repo_index: dict,
    parsed_file: dict,
    file_classes: list[dict],
    file_functions: list[dict],
) -> FileAnalysis:
    file_path = parsed_file.get("file_path", "")
    name = Path(file_path).name.lower()
    lowered = file_path.lower()
    evidence: list[str] = []

    imports = _import_names(parsed_file.get("imports", []))
    main_classes = [item.get("class_name", "") for item in file_classes if item.get("class_name")]
    main_functions = [_function_display_name(item) for item in file_functions if item.get("function_name")]

    is_entry = file_path in repo_index.get("entry_file_candidates", []) or name in ENTRY_NAMES
    is_package_init = name == "__init__.py"
    is_model = _is_model_file(file_path, file_classes, repo_index, evidence)
    is_training = file_path in repo_index.get("train_file_candidates", []) or "train" in name or name in {"trainer.py", "fit.py"}
    is_inference = file_path in repo_index.get("infer_file_candidates", []) or any(keyword in name for keyword in INFERENCE_KEYWORDS)
    is_dataset = any(keyword in lowered for keyword in DATASET_KEYWORDS) or any(
        "dataset" in class_name.lower() or "dataloader" in class_name.lower()
        for class_name in main_classes
    )

    file_type = "unknown"
    confidence = "low"

    if is_package_init:
        file_type = "package_init"
        confidence = "high"
        evidence.append("文件名为 __init__.py，用于包初始化或模块导出")
        is_model = False
    elif is_entry:
        file_type = "entry"
        confidence = "high"
        evidence.append("文件位于 entry_file_candidates 或命中入口文件名规则")
    elif is_model:
        file_type = "model"
        confidence = "high"
    elif is_training:
        file_type = "training"
        confidence = "high"
        evidence.append("文件位于 train_file_candidates 或命中训练文件名规则")
    elif is_inference:
        file_type = "inference"
        confidence = "high"
        evidence.append("文件位于 infer_file_candidates 或命中推理文件名规则")
    elif is_dataset:
        file_type = "dataset"
        confidence = "medium"
        evidence.append("路径或类名命中数据集相关规则")
    elif _is_config_related(name):
        file_type = "config_related"
        confidence = "medium"
        evidence.append("文件名命中配置相关规则")
    elif any(keyword in lowered for keyword in UTILITY_KEYWORDS):
        file_type = "utility"
        confidence = "medium"
        evidence.append("路径或文件名命中工具模块规则")
    elif main_classes or main_functions:
        file_type = "ordinary_module"
        confidence = "medium"
        evidence.append("文件包含类或函数，但未命中更具体的类型规则")
    else:
        evidence.append("未发现类、函数或明确类型线索")

    if parsed_file.get("errors"):
        evidence.append("该文件存在 AST 解析错误，分析基于可用路径信息")

    return FileAnalysis(
        file_path=file_path,
        file_type=file_type,
        purpose=_purpose_for(file_type),
        project_position=_project_position_for(file_path, file_type),
        main_classes=main_classes,
        main_functions=main_functions,
        imports=imports,
        class_count=len(main_classes),
        function_count=len(main_functions),
        is_entry_file=file_type == "entry",
        is_model_file=file_type == "model",
        is_training_file=file_type == "training",
        is_inference_file=file_type == "inference",
        is_dataset_file=file_type == "dataset",
        is_package_init=file_type == "package_init",
        evidence=evidence,
        confidence=confidence,
    )


def _is_model_file(file_path: str, file_classes: list[dict], repo_index: dict, evidence: list[str]) -> bool:
    name = Path(file_path).name.lower()
    if name == "__init__.py":
        return False
    is_model = False
    if file_path in repo_index.get("model_file_candidates", []):
        evidence.append("文件位于 model_file_candidates 中")
        is_model = True
    for class_info in file_classes:
        bases = class_info.get("base_classes", [])
        if any(base in {"nn.Module", "torch.nn.Module"} or base.endswith(".Module") for base in bases):
            class_name = class_info.get("class_name", "")
            evidence.append(f"类 {class_name} 继承 nn.Module 或 torch.nn.Module")
            is_model = True
    lowered = file_path.lower()
    if any(keyword in lowered for keyword in ("model", "network", "backbone")):
        evidence.append("路径或文件名命中模型相关关键词")
        is_model = True
    return is_model


def _group_by_file(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item.get("file_path", ""), []).append(item)
    return grouped


def _import_names(imports: list[dict]) -> list[str]:
    names: list[str] = []
    for item in imports:
        module = item.get("module")
        name = item.get("name")
        if module and name:
            names.append(f"{module}.{name}")
        elif module:
            names.append(module)
    return names


def _function_display_name(function: dict) -> str:
    class_name = function.get("class_name")
    function_name = function.get("function_name", "")
    return f"{class_name}.{function_name}" if class_name else function_name


def _is_config_related(name: str) -> bool:
    return any(keyword in name for keyword in ("config", "settings", "argparse"))


def _purpose_for(file_type: str) -> str:
    purposes = {
        "entry": "作为项目运行入口，负责启动或串联主要流程。",
        "model": "定义模型或神经网络相关结构。",
        "training": "组织训练流程或训练相关逻辑。",
        "inference": "组织推理、预测、评估或演示流程。",
        "dataset": "定义数据集、数据读取或数据加载相关结构。",
        "config_related": "管理配置、参数或设置相关逻辑。",
        "utility": "提供项目内部可复用的辅助工具。",
        "package_init": "初始化 Python 包或导出模块成员。",
        "ordinary_module": "提供项目中的普通 Python 模块逻辑。",
        "unknown": "暂未从结构化信息中识别出明确文件职责。",
    }
    return purposes[file_type]


def _project_position_for(file_path: str, file_type: str) -> str:
    parent = Path(file_path).parent.as_posix()
    if parent == ".":
        location = "位于项目根目录"
    else:
        location = f"位于 {parent} 目录"
    type_text = {
        "entry": "通常处在项目启动流程附近。",
        "model": "属于模型相关代码的一部分。",
        "training": "属于训练流程相关代码的一部分。",
        "inference": "属于推理或评估流程相关代码的一部分。",
        "dataset": "属于数据读取或数据集定义相关代码的一部分。",
        "config_related": "属于配置或参数管理相关代码的一部分。",
        "utility": "属于辅助工具代码的一部分。",
        "package_init": "用于所在目录的包初始化或导出。",
        "ordinary_module": "属于项目普通模块代码。",
        "unknown": "当前位置暂不能确定明确职责。",
    }
    return f"{location}，{type_text[file_type]}"
