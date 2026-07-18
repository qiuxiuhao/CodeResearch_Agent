from __future__ import annotations

from backend.app.alignment.candidate_generator import ExternalRecallHit, generate_alignment_candidates
from backend.app.alignment.fact_reader import AlignmentFactReader, AlignmentFacts
from backend.app.alignment.feature_extractor import extract_feature_vector
from backend.app.alignment.paper_module_extractor import extract_paper_module_profiles
from backend.app.alignment.schemas import AlignmentModelProfile
from backend.app.alignment.scorer import build_profile_decision, score_feature_vector
from backend.app.alignment.stable_ids import content_hash, model_profile_id
from backend.app.alignment.verifier import (
    ProviderAlignmentVerifier,
    apply_verifier_decision,
    fallback_verification,
)
from backend.app.persistence.alignment_store import AlignmentLease, AlignmentStore, AlignmentStoreError
from backend.app.schemas.paper import PaperAnalysis, PaperContribution
from backend.app.retrieval.schemas import PublicRetrievalFilter, RetrievalSearchRequest
from backend.app.observability.context import start_span_or_root
from backend.app.observability.instrumentation import observe_child_call


DEFAULT_MODEL_PROFILE_CONFIG = {
    "profile_extractor_version": "paper-profile-rules-v1",
    "figure_analysis_version": "legacy-figure-v1",
    "candidate_generator_versions": {"deterministic": "candidate-generator-v1"},
    "graph_policy_version": "alignment-graph-v1",
    "legacy_alignment_version": "legacy-heuristic-v1",
    "feature_schema_version": "alignment-features-v1",
    "scorer_version": "weighted-scorer-v1",
    "weight_config_version": "alignment-weights-v1",
    "calibration_method": "identity",
    "calibration_version": "identity-v1",
    "thresholds": {"accept": 0.72, "review": 0.45, "margin": 0.08},
}


def default_model_profile(
    verifier_provenance: dict[str, str | None] | None = None,
) -> AlignmentModelProfile:
    config = {**DEFAULT_MODEL_PROFILE_CONFIG, **(verifier_provenance or {})}
    identifier, config_hash = model_profile_id(config)
    return AlignmentModelProfile(
        model_profile_id=identifier,
        profile_extractor_version=config["profile_extractor_version"],
        figure_analysis_version=config["figure_analysis_version"],
        candidate_generator_versions=config["candidate_generator_versions"],
        graph_policy_version=config["graph_policy_version"],
        legacy_alignment_version=config["legacy_alignment_version"],
        feature_schema_version=config["feature_schema_version"],
        scorer_version=config["scorer_version"],
        weight_config_version=config["weight_config_version"],
        calibration_method=config["calibration_method"],
        calibration_version=config["calibration_version"],
        thresholds=config["thresholds"],
        verifier_provider=config.get("verifier_provider"),
        verifier_model=config.get("verifier_model"),
        verifier_revision=config.get("verifier_revision"),
        verifier_prompt_version=config.get("verifier_prompt_version"),
        config_hash=config_hash,
    )


class AlignmentService:
    def __init__(
        self,
        *,
        store: AlignmentStore,
        fact_reader: AlignmentFactReader,
        retrieval_service=None,
        verifier: ProviderAlignmentVerifier | None = None,
    ) -> None:
        self.store = store
        self.fact_reader = fact_reader
        self.retrieval_service = retrieval_service
        self.verifier = verifier

    def prepare_run(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        paper_id: str,
        request: dict,
        caller_scope: str,
        idempotency_key: str | None,
        retry_of_run_id: str | None = None,
    ) -> tuple[dict, bool]:
        use_provider_verifier = bool(
            request.get("verifier_enabled")
            and request.get("external_text_consent")
            and self.verifier is not None
        )
        profile = default_model_profile(
            self.verifier.profile_provenance() if use_provider_verifier else None
        )
        requested_profile = request.get("model_profile_id")
        if requested_profile not in {None, "alignment-default-v1", profile.model_profile_id}:
            raise AlignmentStoreError("alignment_model_profile_not_found", str(requested_profile))
        self.store.save_model_profile(profile)
        payload = self.fact_reader.input_payload(
            repo_id=repo_id, index_version_id=index_version_id, paper_id=paper_id
        )
        input_hash = content_hash({"facts": payload, "model_profile": profile.config_hash})
        normalized_request = {**request, "model_profile_id": profile.model_profile_id}
        return self.store.create_run(
            repo_id=repo_id,
            index_version_id=index_version_id,
            paper_id=paper_id,
            input_hash=input_hash,
            model_profile_id=profile.model_profile_id,
            request=normalized_request,
            caller_scope=caller_scope,
            idempotency_key=idempotency_key,
            retry_of_run_id=retry_of_run_id,
        )

    def process_run(self, run_id: str, lease: AlignmentLease | None = None) -> dict:
        run = self.store.get_run(run_id)
        if run["cancel_requested"]:
            return self.store.update_status(run_id, "cancelled", allowed_from=[run["status"]])
        facts = self.fact_reader.read(
            repo_id=run["repo_id"], index_version_id=run["index_version_id"], paper_id=run["paper_id"]
        )
        request = _loads(run["request_json"])
        try:
            self._lease_guard(lease)
            stage = run["status"]
            if stage == "ready":
                self._stage_commit_guard(lease, run_id, "ready")
                return self._persist("activate", lambda: self.store.mark_ready_and_activate(run_id))

            if stage in {"queued", "profiling"}:
                self.store.update_status(run_id, "profiling", allowed_from=[stage])
                profiles = self._observed(
                    "alignment.profile",
                    lambda: extract_paper_module_profiles(
                        alignment_run_id=run_id,
                        repo_id=run["repo_id"],
                        index_version_id=run["index_version_id"],
                        paper_id=run["paper_id"],
                        paper_analysis=_paper_analysis(facts),
                        paper_entities=facts.paper_entities,
                    ),
                )
                self._stage_commit_guard(lease, run_id, "profiling")
                self._persist("save_profiles", lambda: self.store.save_profiles(run_id, profiles))
                stage = "profiling"
            else:
                profiles = self.store.load_profiles(run_id)

            if stage in {"profiling", "recalling"}:
                self.store.update_status(run_id, "recalling", allowed_from=[stage])
                all_candidates = self._observed(
                    "alignment.candidate_recall",
                    lambda: self._generate_candidates(facts, profiles),
                )
                self._stage_commit_guard(lease, run_id, "recalling")
                self._persist(
                    "save_candidates", lambda: self.store.save_candidates(run_id, all_candidates)
                )
                stage = "recalling"
            else:
                all_candidates = self.store.load_candidates(run_id)

            entities = {item.id: item for item in facts.code_entities}
            profile_map = {item.profile_id: item for item in profiles}
            if stage in {"recalling", "featurizing"}:
                self.store.update_status(run_id, "featurizing", allowed_from=[stage])
                vectors = self._observed(
                    "alignment.feature_extract",
                    lambda: [
                        extract_feature_vector(
                            profile=profile_map[item.profile_id],
                            candidate=item,
                            entity=entities[item.code_entity_id],
                            chunks=facts.chunks_by_entity.get(item.code_entity_id, []),
                        )
                        for item in all_candidates
                        if item.code_entity_id in entities
                    ],
                )
                self._stage_commit_guard(lease, run_id, "featurizing")
                self._persist("save_features", lambda: self.store.save_features(run_id, vectors))
                stage = "featurizing"
            else:
                vectors = self.store.load_features(run_id)

            if stage in {"featurizing", "scoring"}:
                self.store.update_status(run_id, "scoring", allowed_from=[stage])
                scores = self._observed(
                    "alignment.score", lambda: [score_feature_vector(item) for item in vectors]
                )
                scores = self._observed("alignment.calibrate", lambda: scores)
                self._stage_commit_guard(lease, run_id, "scoring")
                self._persist("save_scores", lambda: self.store.save_scores(run_id, scores))
            else:
                scores = self.store.load_scores(run_id)
            candidates_by_profile: dict[str, list] = {}
            scores_by_profile: dict[str, list] = {}
            for item in all_candidates:
                candidates_by_profile.setdefault(item.profile_id, []).append(item)
            for item in scores:
                scores_by_profile.setdefault(item.profile_id, []).append(item)
            if stage in {"featurizing", "scoring"}:
                decisions = self._observed(
                    "alignment.set_decision",
                    lambda: [
                        build_profile_decision(
                            profile=profile,
                            candidates=candidates_by_profile.get(profile.profile_id, []),
                            scores=scores_by_profile.get(profile.profile_id, []),
                        )
                        for profile in profiles
                    ],
                )
                self._stage_commit_guard(lease, run_id, "scoring")
                self._persist(
                    "save_decisions", lambda: self.store.save_decisions(run_id, decisions)
                )
                stage = "scoring"
            else:
                decisions = self.store.load_decisions(run_id)

            if request.get("verifier_enabled"):
                self.store.update_status(run_id, "verifying", allowed_from=[stage])
                final_decisions, verifications = self._observed(
                    "alignment.verify",
                    lambda: self._verify(
                        request=request,
                        profiles=profiles,
                        decisions=decisions,
                        candidates_by_profile=candidates_by_profile,
                        scores_by_profile=scores_by_profile,
                        entities=entities,
                    ),
                )
                self._stage_commit_guard(lease, run_id, "verifying")
                self._persist(
                    "save_decisions",
                    lambda: self.store.save_decisions(run_id, final_decisions),
                )
                self._persist(
                    "save_verifications",
                    lambda: self.store.save_verifications(run_id, verifications),
                )
                stage = "verifying"
            self._stage_commit_guard(lease, run_id, stage)
            return self._persist("activate", lambda: self.store.mark_ready_and_activate(run_id))
        except AlignmentStoreError:
            raise
        except Exception as exc:
            current = self.store.get_run(run_id)
            if current["status"] in {"active", "failed", "cancelled", "superseded"}:
                raise
            self.store.update_status(
                run_id,
                "failed",
                allowed_from=[current["status"]],
                error_code="alignment_build_failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            raise

    def _retrieval_hits(self, profile) -> list[ExternalRecallHit]:
        if self.retrieval_service is None:
            return []
        try:
            result = self.retrieval_service.search(
                profile.repo_id,
                RetrievalSearchRequest(
                    text=" ".join(
                        item for item in [profile.canonical_name, profile.description] if item
                    )[:8_000],
                    index_version_id=profile.index_version_id,
                    query_type="paper_alignment",
                    filters=PublicRetrievalFilter(entity_kinds=["code"]),
                    top_k=20,
                    include_graph=False,
                    include_reranker=False,
                ),
            )
        except Exception:
            return []
        hits: list[ExternalRecallHit] = []
        for rank, candidate in enumerate(result.candidates, start=1):
            for source in candidate.sources:
                mapped = {
                    "dense": "retrieval_dense",
                    "sparse": "retrieval_sparse",
                    "graph": "code_graph",
                }[source]
                hits.append(
                    ExternalRecallHit(
                        source=mapped,
                        code_entity_id=candidate.entity_id,
                        rank=rank,
                        score=getattr(candidate.score, source),
                        evidence_ids=tuple(item.evidence_id for item in candidate.evidence),
                        chunk_ids=(candidate.chunk_id,),
                    )
                )
        return hits

    def _generate_candidates(self, facts: AlignmentFacts, profiles: list) -> list:
        candidates = []
        legacy = _legacy_targets(facts, profiles)
        for profile in profiles:
            candidates.extend(
                generate_alignment_candidates(
                    profile=profile,
                    code_entities=facts.code_entities,
                    edges=facts.edges,
                    external_hits=self._retrieval_hits(profile),
                    legacy_entity_ids=legacy.get(profile.profile_id, []),
                )
            )
        return candidates

    def _verify(
        self,
        *,
        request: dict,
        profiles: list,
        decisions: list,
        candidates_by_profile: dict[str, list],
        scores_by_profile: dict[str, list],
        entities: dict,
    ) -> tuple[list, list]:
        decision_by_profile = {item.profile_id: item for item in decisions}
        verifications = []
        final_decisions = []
        for profile in profiles:
            profile_candidates = candidates_by_profile.get(profile.profile_id, [])
            scorer_decision = decision_by_profile[profile.profile_id]
            if request.get("external_text_consent") and self.verifier is not None:
                try:
                    verification, selections = self.verifier.verify(
                        profile=profile,
                        candidates=profile_candidates,
                        candidate_scores=scores_by_profile.get(profile.profile_id, []),
                        scorer_decision=scorer_decision,
                        entities=entities,
                    )
                    final_decisions.append(
                        apply_verifier_decision(scorer_decision, verification, selections)
                    )
                except Exception:
                    verification = fallback_verification(profile, profile_candidates)
                    final_decisions.append(scorer_decision)
            else:
                verification = fallback_verification(profile, profile_candidates)
                final_decisions.append(scorer_decision)
            verifications.append(verification)
        return final_decisions, verifications

    @staticmethod
    def _observed(operation: str, callback):
        handle = start_span_or_root(
            operation=operation,
            trace_type="alignment",
            component="alignment",
        )
        with handle:
            result = callback()
            if isinstance(result, list):
                handle.event(f"{operation}.completed", attributes={"cra.count": len(result)})
            return result

    @staticmethod
    def _persist(operation: str, callback):
        return observe_child_call(
            f"database.alignment.{operation}",
            component="database",
            callback=callback,
            attributes={"cra.database.operation": operation},
        )

    def _cancel_guard(self, run_id: str, stage: str) -> None:
        if self.store.is_cancel_requested(run_id):
            self.store.update_status(run_id, "cancelled", allowed_from=[stage])
            raise AlignmentStoreError("alignment_cancelled", run_id)

    def _lease_guard(self, lease: AlignmentLease | None) -> None:
        if lease is not None:
            self.store.assert_lease(lease)

    def _stage_commit_guard(
        self, lease: AlignmentLease | None, run_id: str, stage: str
    ) -> None:
        self._lease_guard(lease)
        self._cancel_guard(run_id, stage)


def _paper_analysis(facts: AlignmentFacts) -> PaperAnalysis:
    contributions = []
    module_names: list[str] = []
    title = None
    for item in facts.paper_entities:
        title = title or item.title
        module_names.extend(item.module_names)
        if item.entity_type in {"contribution", "method_module"}:
            contributions.append(
                PaperContribution(
                    id=item.id,
                    title=item.title or (item.module_names[0] if item.module_names else item.text[:80]),
                    description=item.text,
                    page_no=item.page_number,
                    keywords=item.keywords,
                    evidence=item.evidence_refs,
                )
            )
    return PaperAnalysis(
        paper_provided=True,
        title=title,
        contributions=contributions,
        module_names=sorted(set(module_names)),
    )


def _legacy_targets(facts: AlignmentFacts, profiles: list) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    profile_sources = {
        profile.profile_id: set(profile.paper_entity_ids + profile.contribution_ids)
        for profile in profiles
    }
    for edge in facts.edges:
        if edge.edge_type != "ALIGNS_WITH" or not edge.target_id:
            continue
        for profile_id_value, source_ids in profile_sources.items():
            if edge.source_id in source_ids:
                output.setdefault(profile_id_value, []).append(edge.target_id)
    return {key: sorted(set(values)) for key, values in output.items()}


def _loads(value: str) -> dict:
    import json

    return json.loads(value)
