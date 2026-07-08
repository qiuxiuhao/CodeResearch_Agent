from __future__ import annotations

from pydantic import BaseModel, Field


class ImportInfo(BaseModel):
    module: str
    name: str | None = None
    alias: str | None = None
    import_type: str
    line_no: int | None = None


class FunctionInfo(BaseModel):
    file_path: str
    function_name: str
    class_name: str | None = None
    args: list[str] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None
    source_code: str | None = None
    raw_call_expressions: list[str] = Field(default_factory=list)


class ClassInfo(BaseModel):
    file_path: str
    class_name: str
    base_classes: list[str] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None
    methods: list[str] = Field(default_factory=list)


class ParsedFile(BaseModel):
    file_path: str
    imports: list[ImportInfo] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)
    classes: list[ClassInfo] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)

