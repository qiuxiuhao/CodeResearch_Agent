from __future__ import annotations

from collections.abc import Iterable

from backend.app.schemas.llm_explanation import EvidenceItem, PaperCodeAlignLLMExplanation


class PaperCodeLinkValidator:
    """Validate suggested Figure-to-code links against task-scoped trusted catalogs."""

    def __init__(
        self,
        *,
        contribution_id: str,
        allowed_figure_ids: Iterable[str],
        code_evidence_catalog: Iterable[EvidenceItem],
    ) -> None:
        self.contribution_id = contribution_id
        self.allowed_figure_ids = {str(value) for value in allowed_figure_ids if value}
        self.code_evidence = {item.evidence_id: item for item in code_evidence_catalog}

    def validate(self, value: PaperCodeAlignLLMExplanation) -> None:
        if value.contribution_id != self.contribution_id:
            raise ValueError("Paper code link contribution identity does not match the current contribution.")

        for link in value.possible_code_links:
            if link.contribution_id != self.contribution_id:
                raise ValueError("Suggested code link references a different contribution.")
            if link.figure_id not in self.allowed_figure_ids:
                raise ValueError("Suggested code link references a Figure not allowed for this contribution.")

            valid_target_count = 0
            for evidence_id in link.code_evidence_refs:
                evidence = self.code_evidence.get(evidence_id)
                if evidence is None:
                    raise ValueError("Suggested code link references evidence outside the code evidence catalog.")
                if evidence.evidence_type != "paper_code_target":
                    raise ValueError("Suggested code link evidence is not a code target.")
                valid_target_count += 1

            if valid_target_count == 0:
                raise ValueError("Suggested code link must reference at least one valid code target.")

