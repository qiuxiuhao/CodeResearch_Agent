from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


LibraryCategory = Literal[
    "pytorch",
    "numpy",
    "opencv",
    "pil",
    "einops",
    "python_stdlib",
    "third_party",
    "unknown",
]

Confidence = Literal["high", "medium", "low"]


class LibraryCall(BaseModel):
    file_path: str
    class_name: str | None = None
    function_name: str
    qualified_function_name: str

    canonical_name: str
    display_name: str
    package_name: str | None = None
    category: LibraryCategory = "unknown"

    call_text: str
    line_no: int | None = None
    confidence: Confidence = "medium"
    is_recorded_in_global_library: bool = False

