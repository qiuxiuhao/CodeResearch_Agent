import pytest
from pydantic import ValidationError

from backend.app.llm.evidence import make_evidence, validate_evidence_refs
from backend.app.schemas.llm_explanation import FileLLMExplanation


def test_evidence_refs_must_exist_in_catalog():
    catalog = [make_evidence("file:main.py", "file_rule", "入口", file_path="main.py", start_line=1)]
    assert validate_evidence_refs(["file:main.py"], catalog)
    assert not validate_evidence_refs(["file:missing.py"], catalog)


def test_llm_schema_forbids_uncontrolled_extra_fields():
    with pytest.raises(ValidationError):
        FileLLMExplanation.model_validate({
            "file_path": "main.py", "summary": "入口", "architecture_role": "启动",
            "reading_guide": [], "key_relationships": [], "uncertainties": [], "evidence_refs": [],
            "free_markdown": "```danger```",
        })
