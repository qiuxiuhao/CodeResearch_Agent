from __future__ import annotations

from backend.app.alignment.review_service import AlignmentReviewService
from backend.app.alignment.schemas import AlignmentToolItem
from backend.app.persistence.alignment_store import AlignmentStore


class AlignmentReadService:
    def __init__(self, store: AlignmentStore, *, deployment_name: str = "default") -> None:
        self.store = store
        self.deployment_name = deployment_name

    def get_for_entity(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        entity_id: str,
        max_results: int = 20,
    ) -> list[AlignmentToolItem]:
        output: list[AlignmentToolItem] = []
        for deployment in self.store.list_deployments(
            repo_id=repo_id,
            index_version_id=index_version_id,
            deployment_name=self.deployment_name,
        ):
            candidate_entities = self.store.candidate_entities(deployment.active_run_id)
            profiles = {
                item.profile_id: item for item in self.store.load_profiles(deployment.active_run_id)
            }
            for decision in self.store.list_decisions(deployment.active_run_id):
                effective = AlignmentReviewService(self.store).effective_decision(decision.decision_id)
                profile = profiles.get(decision.profile_id)
                paper_entity_ids = (
                    set(profile.paper_entity_ids + profile.contribution_ids) if profile else set()
                )
                for selection in effective.selections:
                    code_entity_id = candidate_entities.get(selection.candidate_id)
                    if entity_id in paper_entity_ids:
                        output_entity_id = code_entity_id
                    elif code_entity_id == entity_id:
                        output_entity_id = next(iter(sorted(paper_entity_ids)), entity_id)
                    else:
                        continue
                    if output_entity_id is None:
                        continue
                    role = "alignment_hypothesis" if effective.status == "needs_review" else "alignment_decision"
                    output.append(
                        AlignmentToolItem(
                            entity_id=output_entity_id,
                            profile_id=decision.profile_id,
                            decision_id=decision.decision_id,
                            source=(
                                "human_review"
                                if effective.authority_level == "human_reviewed"
                                else "v1.7_verifier"
                                if effective.authority_level == "verified_model"
                                else "v1.7_scorer"
                            ),
                            authority_level=effective.authority_level,
                            evidence_role=role,
                            run_id=deployment.active_run_id,
                            model_profile_id=deployment.model_profile_id,
                            deployment_id=deployment.deployment_id,
                            evidence_ids=sorted(
                                set(selection.paper_evidence_ids + selection.code_evidence_ids)
                            ),
                            summary=f"{selection.relation_type} ({effective.status})",
                        )
                    )
            if len(output) >= max_results:
                break
        unique: dict[tuple[str, str | None, str | None], AlignmentToolItem] = {}
        for item in output:
            unique[(item.entity_id, item.profile_id, item.decision_id)] = item
        return list(unique.values())[:max_results]
