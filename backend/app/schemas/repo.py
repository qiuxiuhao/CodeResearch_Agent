from __future__ import annotations

from pydantic import BaseModel, Field


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["FileTreeNode"] = Field(default_factory=list)


class RepoIndex(BaseModel):
    task_id: str | None = None
    repo_path: str
    file_tree: dict
    python_files: list[str] = Field(default_factory=list)
    entry_file_candidates: list[str] = Field(default_factory=list)
    model_file_candidates: list[str] = Field(default_factory=list)
    train_file_candidates: list[str] = Field(default_factory=list)
    infer_file_candidates: list[str] = Field(default_factory=list)
    config_file_candidates: list[str] = Field(default_factory=list)
    skipped_files: list[dict] = Field(default_factory=list)


class UnzipResult(BaseModel):
    success: bool
    task_id: str
    zip_path: str
    output_dir: str
    repo_path: str | None = None
    extracted_file_count: int = 0
    skipped_files: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)

