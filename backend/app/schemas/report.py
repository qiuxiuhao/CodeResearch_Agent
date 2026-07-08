from __future__ import annotations

from pydantic import BaseModel


class ReportResult(BaseModel):
    report_md: str
    report_path: str

