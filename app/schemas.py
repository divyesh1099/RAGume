import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class UserRead(BaseModel):
    id: str
    full_name: str
    email: str
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class AuthSessionRead(BaseModel):
    user: UserRead


class DocumentRead(BaseModel):
    id: str
    profile_id: str
    filename: str
    source_type: str
    mime_type: str | None
    checksum: str
    parse_metadata: dict
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ChunkSearchHit(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    score: float
    score_components: dict[str, float] = Field(default_factory=dict)
    text: str
    start_char: int
    end_char: int


class DocumentIngestResponse(BaseModel):
    document: DocumentRead
    chunks_created: int
    auto_approved_claims: int = 0
    auto_profile_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentBatchFailureRead(BaseModel):
    filename: str
    detail: str


class DocumentBatchIngestResponse(BaseModel):
    uploads: list[DocumentIngestResponse] = Field(default_factory=list)
    failures: list[DocumentBatchFailureRead] = Field(default_factory=list)
    documents_created: int = 0
    chunks_created: int = 0
    auto_approved_claims: int = 0
    auto_profile_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentReparseResponse(BaseModel):
    document: DocumentRead
    auto_profile_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimRead(BaseModel):
    id: str
    document_id: str
    profile_id: str | None = None
    text: str
    category: str
    skills: list[str]
    confidence: float
    status: str
    support_chunk_ids: list[str]
    rationale: str | None
    review_note: str | None
    created_at: dt.datetime
    reviewed_at: dt.datetime | None

    model_config = {"from_attributes": True}


class EvidenceChunkRead(BaseModel):
    chunk_id: str
    text: str
    start_char: int
    end_char: int


class ClaimEntityRead(BaseModel):
    type: str
    name: str
    normalized: str


class EvidenceAssessmentRead(BaseModel):
    score: float
    label: str
    overclaim_risk: str
    support_chunk_count: int
    support_characters: int
    quantified: bool
    metric_entities: list[str] = Field(default_factory=list)
    action_signal: bool
    skill_signal_count: int


class ClaimDetailRead(ClaimRead):
    document_filename: str
    supporting_chunks: list[EvidenceChunkRead] = Field(default_factory=list)
    entities: list[ClaimEntityRead] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessmentRead


class ClaimExtractionRequest(BaseModel):
    focus_areas: list[str] = Field(default_factory=list)
    max_claims: int = Field(default=8, ge=1, le=25)


class ClaimExtractionResponse(BaseModel):
    document_id: str
    extractor_mode: str
    warnings: list[str] = Field(default_factory=list)
    retrieved_chunks: list[ChunkSearchHit]
    claims: list[ClaimDetailRead]


class ReviewClaimRequest(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = None


class ProfileClaimRead(BaseModel):
    id: str
    claim_id: str
    document_id: str
    profile_id: str | None = None
    text: str
    category: str
    skills: list[str]
    confidence: float
    evidence: dict
    entities: list[ClaimEntityRead] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessmentRead
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: str | None = None
    profile_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[ChunkSearchHit]


class JobDescriptionParseResponse(BaseModel):
    filename: str
    text: str
    parse_metadata: dict


class ResumeParserBackendRead(BaseModel):
    id: str
    label: str
    description: str
    available: bool
    is_default: bool = False


class ResumeParserComparisonRunRead(BaseModel):
    backend: str
    label: str
    description: str
    mode: str | None = None
    warnings: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    insights: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)
    error: str | None = None


class ResumeParserComparisonResponse(BaseModel):
    document_id: str
    active_backend: str
    available_backends: list[ResumeParserBackendRead] = Field(default_factory=list)
    comparisons: list[ResumeParserComparisonRunRead] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    profile_id: str
    profile_name: str
    documents_total: int
    pending_claims_total: int
    approved_claims_total: int
    rejected_claims_total: int
    graph_nodes_total: int
    graph_edges_total: int
    skills_total: int = 0
    work_experience_total: int = 0
    education_total: int = 0
    projects_total: int = 0
    llm_available: bool
    embedding_retrieval_available: bool
    parser_backend: str
    extractor_mode: str
    openai_model: str | None = None
    openai_embedding_model: str | None = None


class ProfileGraphNodeRead(BaseModel):
    id: str
    node_key: str
    node_type: str
    label: str
    weight: float
    node_metadata: dict

    model_config = {"from_attributes": True}


class ProfileGraphEdgeRead(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    weight: float
    edge_metadata: dict

    model_config = {"from_attributes": True}


class ProfileGraphRead(BaseModel):
    nodes: list[ProfileGraphNodeRead]
    edges: list[ProfileGraphEdgeRead]


class ProfileRead(BaseModel):
    id: str
    name: str
    headline: str | None = None
    document_count: int = 0
    pending_claim_count: int = 0
    approved_claim_count: int = 0
    skills_total: int = 0
    work_experience_total: int = 0
    education_total: int = 0
    projects_total: int = 0
    sections_ready: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = {"from_attributes": True}


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProfileLinkRead(BaseModel):
    label: str
    url: str


class ProfileIdentityRead(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    summary: str | None = None
    current_position: str | None = None
    target_headline: str | None = None
    location: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)


class ProfileItemRead(BaseModel):
    title: str | None = None
    organization: str | None = None
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    name: str | None = None
    issuer: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    summary: str | None = None
    credential_id: str | None = None
    technologies: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)


class ProfileSourceDocumentRead(BaseModel):
    document_id: str
    filename: str
    created_at: str | None = None
    document_role: str | None = None
    profile_focus: str | None = None
    source_quality: float | None = None
    signals: list[str] = Field(default_factory=list)


class ProfileOverviewRead(BaseModel):
    profile_id: str
    profile_name: str
    profile_mode: str = "auto"
    profile_focus: str | None = None
    profile_view: str | None = None
    identity: ProfileIdentityRead
    skills: list[str] = Field(default_factory=list)
    public_profiles: list[ProfileLinkRead] = Field(default_factory=list)
    education: list[ProfileItemRead] = Field(default_factory=list)
    work_experience: list[ProfileItemRead] = Field(default_factory=list)
    projects: list[ProfileItemRead] = Field(default_factory=list)
    certifications: list[ProfileItemRead] = Field(default_factory=list)
    available_views: list[str] = Field(default_factory=list)
    mode_summaries: dict[str, str] = Field(default_factory=dict)
    source_documents: list[ProfileSourceDocumentRead] = Field(default_factory=list)
    documents_total: int = 0
    auto_updated_at: str | None = None
    updated_at: dt.datetime | None = None


class ProfileOverviewUpdateRequest(BaseModel):
    identity: ProfileIdentityRead | None = None
    skills: list[str] | None = None
    public_profiles: list[ProfileLinkRead] | None = None


class StructuredProfileClaimRead(BaseModel):
    id: str
    profile_id: str
    document_id: str
    document_filename: str | None = None
    section: str
    field_name: str
    raw_value_json: dict = Field(default_factory=dict)
    value_json: dict = Field(default_factory=dict)
    value_text: str
    normalized_value: str
    source_text: str | None = None
    source_page: int | None = None
    source_bbox: dict = Field(default_factory=dict)
    parser_name: str
    confidence: float
    resolver_confidence: float = 0.0
    resolver_action: str = "keep"
    resolver_evidence: list[str] = Field(default_factory=list)
    admission_status: str = "needs_review"
    admission_reason: str | None = None
    admission_score: float = 0.0
    suggested_section: str | None = None
    status: str
    position: int
    created_at: dt.datetime
    updated_at: dt.datetime


class StructuredProfileClaimUpdateRequest(BaseModel):
    status: Literal["pending", "accepted", "edited", "rejected", "duplicate"] | None = None
    section: str | None = None
    value_json: dict | None = None


class StructuredProfileReviewSectionRead(BaseModel):
    section: str
    label: str
    claims: list[StructuredProfileClaimRead] = Field(default_factory=list)


class ProfileStudioCorrectionDiagnosticsRead(BaseModel):
    embedding_retrieval_enabled: bool = False
    correction_embedding_provider: str = "openai"
    correction_embedding_model: str | None = None
    correction_embedding_cache_entries: int = 0
    correction_embedding_cache_hits: int = 0
    correction_embedding_cache_misses: int = 0
    llm_arbiter_enabled: bool = False
    llm_arbiter_provider: str = "openai"
    llm_arbiter_model: str | None = None
    llm_arbiter_decisions: int = 0
    semantic_matches: int = 0
    section_suggestions: int = 0
    action_counts: dict[str, int] = Field(default_factory=dict)
    top_reason_codes: dict[str, int] = Field(default_factory=dict)


class ProfileStudioParserDiagnosticRead(BaseModel):
    document_id: str
    filename: str
    parser_backend: str | None = None
    extraction_mode: str | None = None
    document_role: str | None = None
    profile_focus: str | None = None
    source_quality: float | None = None
    validation_status: str | None = None
    validation_score: int | None = None
    warning_count: int = 0
    page_count: int = 0
    block_count: int = 0
    section_counts: dict[str, int] = Field(default_factory=dict)
    embedding_status: str | None = None


class ProfileStudioDiagnosticsRead(BaseModel):
    correction: ProfileStudioCorrectionDiagnosticsRead
    parser_sources: list[ProfileStudioParserDiagnosticRead] = Field(default_factory=list)
    record_frames: list[dict] = Field(default_factory=list)


class ClaimGroupRead(BaseModel):
    id: str
    profile_id: str
    group_type: str
    canonical_key: str
    canonical_value: str
    canonical_value_json: dict = Field(default_factory=dict)
    confidence: float = 0.0
    merge_action: str = "merge"
    review_reason: str | None = None
    status: str = "merged"
    claim_ids: list[str] = Field(default_factory=list)
    group_metadata: dict = Field(default_factory=dict)
    created_at: dt.datetime
    updated_at: dt.datetime


class ProfileAnomalyRead(BaseModel):
    id: str
    profile_id: str
    claim_group_id: str | None = None
    anomaly_type: str
    severity: str
    message: str
    candidate_values_json: list[dict] = Field(default_factory=list)
    recommended_action: str
    status: str
    created_at: dt.datetime
    updated_at: dt.datetime


class ProfileFusionRead(BaseModel):
    generated_at: dt.datetime
    summary: dict[str, int] = Field(default_factory=dict)
    merged_groups: list[ClaimGroupRead] = Field(default_factory=list)
    review_groups: list[ClaimGroupRead] = Field(default_factory=list)
    critical_review_groups: list[ClaimGroupRead] = Field(default_factory=list)
    optional_review_groups: list[ClaimGroupRead] = Field(default_factory=list)
    ignored_groups: list[ClaimGroupRead] = Field(default_factory=list)
    anomalies: list[ProfileAnomalyRead] = Field(default_factory=list)
    preview_profile: ProfileOverviewRead


class StructuredProfileReviewRead(BaseModel):
    profile_id: str
    profile_name: str
    documents_total: int
    claims_total: int
    pending_total: int
    accepted_total: int
    edited_total: int
    rejected_total: int
    sections: list[StructuredProfileReviewSectionRead] = Field(default_factory=list)
    correction_summary: dict[str, int] = Field(default_factory=dict)
    diagnostics: ProfileStudioDiagnosticsRead
    extracted_profile: ProfileOverviewRead
    review_preview_profile: ProfileOverviewRead
    canonical_profile: ProfileOverviewRead
    fusion: ProfileFusionRead


class ProfileFusionResponseRead(ProfileFusionRead):
    profile_id: str
    profile_name: str


class WikiReferenceRead(BaseModel):
    id: str
    label: str
    title: str
    document: str
    excerpt: str
    kind: str


class WikiBulletItemRead(BaseModel):
    text: str
    reference_ids: list[str] = Field(default_factory=list)


class WikiRelatedArticleRead(BaseModel):
    slug: str
    title: str
    description: str | None = None


class WikiSectionRead(BaseModel):
    id: str
    title: str
    paragraphs: list[str] = Field(default_factory=list)
    bullet_items: list[WikiBulletItemRead] = Field(default_factory=list)


class WikiArticleRead(BaseModel):
    slug: str
    title: str
    lede: str
    infobox: dict[str, str] = Field(default_factory=dict)
    sections: list[WikiSectionRead] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)
    references: list[WikiReferenceRead] = Field(default_factory=list)
    related_articles: list[WikiRelatedArticleRead] = Field(default_factory=list)


class ProfileWikiRead(BaseModel):
    generated_at: dt.datetime
    articles: list[WikiArticleRead] = Field(default_factory=list)


class BenchmarkRunRequest(BaseModel):
    parser_backend: str = "auto"
    limit: int | None = Field(default=None, ge=1, le=500)
    categories: list[str] = Field(default_factory=list)
    resume_ids: list[str] = Field(default_factory=list)
    allow_remote_models: bool = False


class BenchmarkDatasetRead(BaseModel):
    dataset_dir: str | None = None
    available: bool
    gold_template_path: str | None = None
    manifest_path: str | None = None
    total_cases: int = 0
    categories: list[str] = Field(default_factory=list)
    review_status_counts: dict[str, int] = Field(default_factory=dict)
    field_coverage: dict[str, int] = Field(default_factory=dict)
    latest_report_generated_at: dt.datetime | None = None
    latest_report_parser_backend: str | None = None
    latest_report_overall_score: float | None = None
    latest_report_path: str | None = None


class BenchmarkFieldMetricRead(BaseModel):
    field: str
    label: str
    scored_cases: int = 0
    skipped_cases: int = 0
    average_score: float | None = None
    match_cases: int = 0
    close_cases: int = 0
    miss_cases: int = 0


class BenchmarkFieldScoreRead(BaseModel):
    field: str
    label: str
    status: str
    score: float | None = None
    gold_count: int = 0
    extracted_count: int = 0
    matched_count: int = 0
    missing_count: int = 0
    unexpected_count: int = 0
    gold_preview: list[str] = Field(default_factory=list)
    extracted_preview: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BenchmarkCaseResultRead(BaseModel):
    resume_id: str
    category: str
    filename: str
    file_path: str
    parser_backend: str
    extraction_mode: str | None = None
    status: str
    overall_score: float | None = None
    gold_fields_available: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    diagnostics: dict = Field(default_factory=dict)
    extracted_snapshot: dict = Field(default_factory=dict)
    field_scores: list[BenchmarkFieldScoreRead] = Field(default_factory=list)


class BenchmarkRunRead(BaseModel):
    generated_at: dt.datetime
    dataset_dir: str
    parser_backend: str
    allow_remote_models: bool = False
    limit: int | None = None
    categories: list[str] = Field(default_factory=list)
    resume_ids: list[str] = Field(default_factory=list)
    total_cases: int = 0
    processed_cases: int = 0
    success_cases: int = 0
    failed_cases: int = 0
    overall_score: float | None = None
    duration_seconds: float = 0.0
    saved_report_path: str | None = None
    field_metrics: list[BenchmarkFieldMetricRead] = Field(default_factory=list)
    cases: list[BenchmarkCaseResultRead] = Field(default_factory=list)
