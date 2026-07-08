from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


FileType = Literal[
    "entry",
    "model",
    "training",
    "inference",
    "dataset",
    "config_related",
    "utility",
    "package_init",
    "ordinary_module",
    "unknown",
]

Confidence = Literal["high", "medium", "low"]


class FileAnalysis(BaseModel):
    file_path: str
    file_type: FileType
    purpose: str
    project_position: str

    main_classes: list[str] = Field(default_factory=list)
    main_functions: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)

    class_count: int = 0
    function_count: int = 0

    is_entry_file: bool = False
    is_model_file: bool = False
    is_training_file: bool = False
    is_inference_file: bool = False
    is_dataset_file: bool = False
    is_package_init: bool = False

    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"

