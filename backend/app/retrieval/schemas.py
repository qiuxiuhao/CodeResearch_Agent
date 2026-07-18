from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


QueryType = Literal[
    "symbol_lookup",
    "implementation_explanation",
    "call_chain",
    "architecture",
    "tensor_shape",
    "configuration",
    "training_process",
    "inference_process",
    "paper_alignment",
    "general_repository",
]
RetrievalSource = Literal["dense", "sparse", "graph"]
TokenCountMethod = Literal[
    "provider_tokenizer",
    "model_tokenizer",
    "conservative_code_estimate",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicRetrievalFilter(StrictModel):
    entity_types: list[str] = Field(default_factory=list)
    entity_kinds: list[Literal["code", "paper"]] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    qualified_names: list[str] = Field(default_factory=list)
    chunk_types: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)


class RetrievalSearchRequest(StrictModel):
    text: str = Field(min_length=1, max_length=8_000)
    index_version_id: str | None = None
    query_type: QueryType | None = None
    filters: PublicRetrievalFilter = Field(default_factory=PublicRetrievalFilter)
    top_k: int | None = Field(default=None, ge=1, le=100)
    include_graph: bool | None = None
    include_reranker: bool | None = None


class ResearchQueryRequest(RetrievalSearchRequest):
    answer_enabled: bool = True
    external_text_consent: bool = False


class RetrievalFilter(PublicRetrievalFilter):
    repo_id: str
    index_version_id: str


class RetrievalQuery(StrictModel):
    query_id: str
    text: str = Field(min_length=1, max_length=8_000)
    query_type: QueryType | None = None
    filters: RetrievalFilter
    top_k: int | None = Field(default=None, ge=1, le=100)
    include_graph: bool | None = None
    include_reranker: bool | None = None


class RawRetrievalHit(StrictModel):
    source: RetrievalSource
    chunk_id: str
    entity_id: str
    source_score: float
    source_rank: int = Field(ge=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class FusedRetrievalCandidate(StrictModel):
    chunk_id: str
    entity_id: str
    hits: list[RawRetrievalHit]
    preliminary_rrf: float | None = None
    final_rrf: float | None = None
    graph_path_edge_ids: list[str] = Field(default_factory=list)
    contributions: dict[str, float] = Field(default_factory=dict)


class FinalRetrievalCandidate(StrictModel):
    candidate: FusedRetrievalCandidate
    reranker_score: float | None = None
    reranker_normalized: float | None = None
    final_score: float
    contributions: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_final_rrf(self) -> "FinalRetrievalCandidate":
        if self.candidate.final_rrf is None:
            raise ValueError("FinalRetrievalCandidate requires candidate.final_rrf.")
        return self


class RetrievalScore(StrictModel):
    dense: float | None = None
    sparse: float | None = None
    graph: float | None = None
    preliminary_rrf: float | None = None
    final_rrf: float
    reranker: float | None = None
    reranker_normalized: float | None = None
    final: float
    source_ranks: dict[str, int] = Field(default_factory=dict)
    contributions: dict[str, float] = Field(default_factory=dict)


class RetrievalEvidence(StrictModel):
    evidence_id: str
    source_type: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None
    figure_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class RetrievalDocument(StrictModel):
    chunk_id: str
    entity_id: str
    repo_id: str
    index_version_id: str
    entity_kind: Literal["code", "paper"]
    entity_type: str
    chunk_type: str
    path: str | None = None
    qualified_name: str | None = None
    parent_entity_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    page_number: int | None = None
    ordinal: int = 0
    text: str
    content_hash: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RetrievalCandidate(RetrievalDocument):
    score: RetrievalScore
    sources: list[RetrievalSource]
    matched_terms: list[str] = Field(default_factory=list)
    graph_path_edge_ids: list[str] = Field(default_factory=list)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)


class RetrievalConfig(StrictModel):
    profile: QueryType
    dense_enabled: bool = False
    sparse_enabled: bool = True
    graph_enabled: bool = True
    reranker_enabled: bool = False
    dense_top_k: int = Field(default=30, ge=0, le=200)
    sparse_top_k: int = Field(default=30, ge=0, le=200)
    fusion_top_k: int = Field(default=40, ge=1, le=200)
    graph_seed_k: int = Field(default=8, ge=0, le=50)
    graph_max_hops: int = Field(default=1, ge=0, le=2)
    graph_max_candidates: int = Field(default=30, ge=0, le=100)
    final_top_k: int = Field(default=10, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1)
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {"dense": 1.0, "sparse": 1.0, "graph": 0.8}
    )
    graph_edge_weights: dict[str, float] = Field(default_factory=dict)
    hybrid_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    reranker_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    dense_model_id: str | None = None
    dense_model_revision: str | None = None
    sparse_model_id: str | None = "fts5-unicode61-v1"
    reranker_model_id: str | None = None
    token_budget: int = Field(default=6_000, ge=256)
    max_entities: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def validate_final_weights(self) -> "RetrievalConfig":
        if abs((self.hybrid_weight + self.reranker_weight) - 1.0) > 1e-9:
            raise ValueError("hybrid_weight and reranker_weight must sum to 1.0.")
        if not self.reranker_enabled and (self.hybrid_weight, self.reranker_weight) != (1.0, 0.0):
            raise ValueError("Disabled reranker requires hybrid/reranker weights 1.0/0.0.")
        return self


class RetrievalResult(StrictModel):
    query: RetrievalQuery
    effective_config: RetrievalConfig
    candidates: list[RetrievalCandidate]
    total_candidates: int = Field(ge=0)
    active_index_version_id: str
    vector_index_generation: str | None = None
    latency_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ContextItem(StrictModel):
    context_id: str
    entity_id: str
    chunk_ids: list[str]
    title: str
    text: str
    token_count: int = Field(ge=0)
    truncated: bool
    rank: int = Field(ge=1)
    relationship_notes: list[str] = Field(default_factory=list)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)


class ContextBundle(StrictModel):
    repo_id: str
    index_version_id: str
    query_id: str
    items: list[ContextItem]
    estimated_tokens: int = Field(ge=0)
    provider_validated_tokens: int | None = Field(default=None, ge=0)
    token_count_method: TokenCountMethod
    token_budget: int = Field(ge=0)
    omitted_candidate_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnswerCitation(StrictModel):
    citation_id: str
    context_id: str
    evidence_id: str
    entity_id: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    paper_id: str | None = None
    page_number: int | None = None


class AnswerClaim(StrictModel):
    claim_id: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    supported: bool


class ResearchAnswer(StrictModel):
    answer: str
    claims: list[AnswerClaim]
    citations: list[AnswerCitation]
    unsupported_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ResearchResponse(StrictModel):
    retrieval: RetrievalResult
    context: ContextBundle
    answer: ResearchAnswer | None = None
    evidence_only: bool = False
    warnings: list[str] = Field(default_factory=list)
