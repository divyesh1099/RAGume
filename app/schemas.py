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
    signals: list[str] = Field(default_factory=list)


class ProfileOverviewRead(BaseModel):
    profile_id: str
    profile_name: str
    identity: ProfileIdentityRead
    skills: list[str] = Field(default_factory=list)
    public_profiles: list[ProfileLinkRead] = Field(default_factory=list)
    education: list[ProfileItemRead] = Field(default_factory=list)
    work_experience: list[ProfileItemRead] = Field(default_factory=list)
    projects: list[ProfileItemRead] = Field(default_factory=list)
    certifications: list[ProfileItemRead] = Field(default_factory=list)
    source_documents: list[ProfileSourceDocumentRead] = Field(default_factory=list)
    documents_total: int = 0
    auto_updated_at: str | None = None
    updated_at: dt.datetime | None = None


class ProfileOverviewUpdateRequest(BaseModel):
    identity: ProfileIdentityRead | None = None
    skills: list[str] | None = None
    public_profiles: list[ProfileLinkRead] | None = None


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
