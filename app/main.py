import datetime as dt
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session_async, init_db, init_engine, session_scope
from app.models import Claim, Document, Profile, ProfileClaim, ProfileGraphEdge, ProfileGraphNode, StructuredProfileClaim, User
from app.schemas import (
    AuthSessionRead,
    BenchmarkDatasetRead,
    BenchmarkRunRead,
    BenchmarkRunRequest,
    ClaimDetailRead,
    ClaimEntityRead,
    ClaimExtractionRequest,
    ClaimExtractionResponse,
    ChunkSearchHit,
    DashboardSummary,
    DocumentBatchFailureRead,
    DocumentBatchIngestResponse,
    DocumentIngestResponse,
    DocumentReparseResponse,
    DocumentRead,
    EvidenceAssessmentRead,
    EvidenceChunkRead,
    JobDescriptionParseResponse,
    LoginRequest,
    ProfileClaimRead,
    ProfileCreateRequest,
    ProfileGraphEdgeRead,
    ProfileGraphNodeRead,
    ProfileGraphRead,
    ProfileOverviewRead,
    ProfileOverviewUpdateRequest,
    ProfileRead,
    ProfileUpdateRequest,
    ProfileWikiRead,
    RegisterRequest,
    ResumeParserBackendRead,
    ResumeParserComparisonRunRead,
    ResumeParserComparisonResponse,
    ReviewClaimRequest,
    SearchRequest,
    SearchResponse,
    StructuredProfileClaimRead,
    StructuredProfileClaimUpdateRequest,
    StructuredProfileReviewRead,
    UserRead,
)
from app.services.benchmarking import benchmark_dataset_summary, load_latest_benchmark_report, run_resume_benchmark
from app.services.auth import (
    SESSION_COOKIE_NAME,
    authenticate_user,
    create_user,
    create_user_session,
    get_current_user_from_request,
    revoke_session,
)
from app.services.claim_extractor import extract_claims_for_document, fetch_chunk_evidence
from app.services.claim_utils import assess_claim_evidence, extract_claim_entities
from app.services.correction_resolver import maybe_record_correction_rule
from app.services.documents import cleanup_document_storage, delete_document_evidence, ingest_uploaded_document
from app.services.embeddings import embedding_available
from app.services.job_descriptions import parse_uploaded_job_description
from app.services.parser_backends import (
    compare_resume_parser_backends,
    resolve_resume_parser_backend,
    resume_parser_backends,
    validate_resume_parser_choice,
)
from app.services.profile_memory import (
    annotate_document_profile_metadata,
    extract_document_profile_insights,
    profile_overview_payload,
    rebuild_profile_overview,
    reset_manual_profile_overrides,
    update_manual_profile_overrides,
)
from app.services.profile_studio import (
    accept_all_structured_profile_claims,
    build_structured_profile_review,
    clear_canonical_profile,
    document_structured_claims_need_sync,
    rollback_profile_after_evidence_delete,
    resolve_structured_profile_claim,
    save_canonical_profile_from_structured_claims,
    serialize_structured_profile_claim,
    sync_document_structured_profile_claims,
    update_structured_profile_claim,
)
from app.services.profile_graph import sync_profile_graph
from app.services.profiles import (
    build_profile_summaries_for_user,
    create_profile,
    delete_profile,
    rename_profile,
    resolve_profile,
)
from app.services.retrieval import search_chunks
from app.services.wiki import build_profile_wiki


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
LOGGER = logging.getLogger("ragume.app")
UPLOAD_LIMITED_PATHS = {
    "/documents/upload",
    "/documents/upload-batch",
    "/job-description/parse",
}


async def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def llm_available(settings: Settings) -> bool:
    return settings.enable_llm_extractor and bool(settings.openai_api_key)


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root_logger.setLevel(level)


def ensure_runtime_directories(settings: Settings) -> None:
    for path_value in (
        settings.uploads_dir,
        settings.benchmark_reports_dir,
        settings.resume_ner_cache_dir,
        settings.correction_local_embedding_cache_dir,
    ):
        if not path_value:
            continue
        Path(path_value).mkdir(parents=True, exist_ok=True)


def runtime_status_payload(settings: Settings) -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.app_env,
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "public_base_url": settings.public_base_url,
        "session_cookie_secure": settings.session_cookie_secure_effective,
        "session_cookie_samesite": settings.session_cookie_samesite,
        "allowed_hosts": settings.allowed_host_list,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "parser_backend": resolve_resume_parser_backend(settings),
        "llm_extractor_enabled": llm_available(settings),
        "openai_model": settings.openai_model if llm_available(settings) else None,
        "embedding_retrieval_enabled": embedding_available(settings),
        "openai_embedding_model": settings.openai_embedding_model if embedding_available(settings) else None,
    }


def readiness_payload(settings: Settings) -> dict[str, Any]:
    checks: dict[str, str] = {}
    status = "ready"

    try:
        with session_scope() as session:
            session.execute(select(1))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - defensive guard for runtime health only
        checks["database"] = f"error:{exc.__class__.__name__}"
        status = "degraded"

    for label, path_value in (
        ("uploads_dir", settings.uploads_dir),
        ("benchmark_reports_dir", settings.benchmark_reports_dir),
    ):
        try:
            Path(path_value).mkdir(parents=True, exist_ok=True)
            checks[label] = "ok"
        except OSError as exc:
            checks[label] = f"error:{exc.__class__.__name__}"
            status = "degraded"

    return {
        **runtime_status_payload(settings),
        "status": status,
        "checks": checks,
    }


def request_exceeds_upload_limit(request: Request, settings: Settings) -> bool:
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return False
    if request.url.path not in UPLOAD_LIMITED_PATHS:
        return False
    content_length = request.headers.get("content-length")
    if not content_length:
        return False
    try:
        return int(content_length) > settings.max_upload_size_bytes
    except ValueError:
        return False


async def get_current_user(
    request: Request,
    session: Session = Depends(get_session_async),
) -> User:
    return get_current_user_from_request(session, request)


def ensure_document_in_profile(document: Document | None, profile: Profile) -> Document:
    if document is None or document.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Document not found in the selected profile.")
    return document


def ensure_claim_in_profile(session: Session, claim: Claim | None, profile: Profile) -> Claim:
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    document = session.get(Document, claim.document_id)
    ensure_document_in_profile(document, profile)
    return claim


def ensure_structured_claim_in_profile(
    session: Session,
    claim_id: str,
    profile: Profile,
) -> StructuredProfileClaim:
    try:
        return resolve_structured_profile_claim(session, profile=profile, claim_id=claim_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def serialize_user(user: User) -> UserRead:
    return UserRead.model_validate(user)


def serialize_claim_detail(session: Session, claim: Claim) -> ClaimDetailRead:
    document = session.get(Document, claim.document_id)
    supporting_chunk_dicts = fetch_chunk_evidence(session, claim.support_chunk_ids)
    supporting_chunks = [EvidenceChunkRead(**item) for item in supporting_chunk_dicts]
    entities = [
        ClaimEntityRead(**item)
        for item in extract_claim_entities(claim.text, claim.skills, claim.category)
    ]
    evidence_assessment = EvidenceAssessmentRead(
        **assess_claim_evidence(
            claim_text=claim.text,
            supporting_chunks=supporting_chunk_dicts,
            confidence=claim.confidence,
            skills=claim.skills,
        )
    )
    return ClaimDetailRead(
        id=claim.id,
        document_id=claim.document_id,
        profile_id=document.profile_id if document else None,
        document_filename=document.filename if document else "Unknown document",
        text=claim.text,
        category=claim.category,
        skills=claim.skills,
        confidence=claim.confidence,
        status=claim.status,
        support_chunk_ids=claim.support_chunk_ids,
        supporting_chunks=supporting_chunks,
        entities=entities,
        evidence_assessment=evidence_assessment,
        rationale=claim.rationale,
        review_note=claim.review_note,
        created_at=claim.created_at,
        reviewed_at=claim.reviewed_at,
    )


def serialize_profile_claim(session: Session, profile_claim: ProfileClaim) -> ProfileClaimRead:
    document = session.get(Document, profile_claim.document_id)
    evidence = dict(profile_claim.evidence or {})
    if document:
        evidence.setdefault("document_filename", document.filename)
    evidence_chunks = evidence.get("chunks", [])
    entities = [
        ClaimEntityRead(**item)
        for item in extract_claim_entities(profile_claim.text, profile_claim.skills, profile_claim.category)
    ]
    evidence_assessment = EvidenceAssessmentRead(
        **assess_claim_evidence(
            claim_text=profile_claim.text,
            supporting_chunks=evidence_chunks,
            confidence=profile_claim.confidence,
            skills=profile_claim.skills,
        )
    )
    return ProfileClaimRead(
        id=profile_claim.id,
        claim_id=profile_claim.claim_id,
        document_id=profile_claim.document_id,
        profile_id=document.profile_id if document else None,
        text=profile_claim.text,
        category=profile_claim.category,
        skills=profile_claim.skills,
        confidence=profile_claim.confidence,
        evidence=evidence,
        entities=entities,
        evidence_assessment=evidence_assessment,
        created_at=profile_claim.created_at,
    )


def build_profile_claim_evidence(session: Session, claim: Claim) -> dict:
    document = session.get(Document, claim.document_id)
    evidence = {
        "document_id": claim.document_id,
        "document_filename": document.filename if document else None,
        "chunks": fetch_chunk_evidence(session, claim.support_chunk_ids),
    }
    evidence["assessment"] = assess_claim_evidence(
        claim_text=claim.text,
        supporting_chunks=evidence["chunks"],
        confidence=claim.confidence,
        skills=claim.skills,
    )
    evidence["entities"] = extract_claim_entities(claim.text, claim.skills, claim.category)
    return evidence


def apply_claim_review(
    session: Session,
    claim: Claim,
    *,
    status: str,
    note: str | None = None,
) -> None:
    claim.status = status
    claim.review_note = note
    claim.reviewed_at = dt.datetime.now(dt.UTC)

    profile_claim = session.scalar(select(ProfileClaim).where(ProfileClaim.claim_id == claim.id))
    if status == "approved":
        evidence = build_profile_claim_evidence(session, claim)
        if profile_claim is None:
            session.add(
                ProfileClaim(
                    claim_id=claim.id,
                    document_id=claim.document_id,
                    text=claim.text,
                    category=claim.category,
                    skills=claim.skills,
                    confidence=claim.confidence,
                    evidence=evidence,
                )
            )
        else:
            profile_claim.text = claim.text
            profile_claim.category = claim.category
            profile_claim.skills = claim.skills
            profile_claim.confidence = claim.confidence
            profile_claim.evidence = evidence
    elif profile_claim is not None:
        session.delete(profile_claim)


def auto_process_document(
    session: Session,
    *,
    document: Document,
    profile: Profile,
    settings: Settings,
    parser_backend: str | None = None,
) -> tuple[int, list[str], list[str]]:
    parse_metadata = dict(document.parse_metadata or {})
    insights, profile_mode, profile_warnings, diagnostics = extract_document_profile_insights(
        document,
        settings,
        parser_backend=parser_backend,
    )
    parse_metadata["profile_insights"] = insights
    parse_metadata["profile_extraction_mode"] = profile_mode
    parse_metadata["profile_extraction_warnings"] = profile_warnings
    parse_metadata["profile_validation"] = diagnostics.get("validation", {})
    parse_metadata["profile_parser_diagnostics"] = diagnostics
    parse_metadata["profile_parser_backend"] = diagnostics.get("parser_backend")
    parse_metadata["profile_parser_label"] = diagnostics.get("parser_backend_label")
    parse_metadata.update(annotate_document_profile_metadata(document, insights))
    document.parse_metadata = parse_metadata
    session.flush()
    sync_document_structured_profile_claims(session, profile, document, settings=settings)

    focus_areas = insights.get("skills", [])[:8]
    _, claims, _, claim_warnings = extract_claims_for_document(
        session,
        document=document,
        settings=settings,
        focus_areas=focus_areas,
        max_claims=min(settings.max_claims_per_run, 8),
    )
    for claim in claims:
        apply_claim_review(
            session,
            claim,
            status="approved",
            note="Auto-approved from uploaded evidence.",
        )

    sync_profile_graph(session)
    rebuild_profile_overview(session, profile, settings)
    session.commit()
    session.refresh(document)

    auto_sections = [
        key
        for key in ("identity", "skills", "education", "work_experience", "projects", "certifications")
        if (
            key == "identity"
            and any(insights.get("identity", {}).get(field) for field in ("full_name", "headline", "summary", "emails", "phones"))
        ) or (key != "identity" and insights.get(key))
    ]
    warnings = [*profile_warnings, *claim_warnings]
    return len(claims), auto_sections, warnings


def ingest_and_process_uploaded_document(
    session: Session,
    *,
    upload_file: UploadFile,
    profile: Profile,
    settings: Settings,
    parser_choice: str | None,
) -> DocumentIngestResponse:
    document, chunks_created = ingest_uploaded_document(session, upload_file, settings, profile)
    auto_approved_claims, auto_profile_sections, warnings = auto_process_document(
        session,
        document=document,
        profile=profile,
        settings=settings,
        parser_backend=parser_choice,
    )
    return DocumentIngestResponse(
        document=document,
        chunks_created=chunks_created,
        auto_approved_claims=auto_approved_claims,
        auto_profile_sections=auto_profile_sections,
        warnings=warnings,
    )


def refresh_document_profile(
    session: Session,
    *,
    document: Document,
    profile: Profile,
    settings: Settings,
    parser_backend: str | None = None,
) -> tuple[list[str], list[str]]:
    parse_metadata = dict(document.parse_metadata or {})
    insights, profile_mode, profile_warnings, diagnostics = extract_document_profile_insights(
        document,
        settings,
        parser_backend=parser_backend,
    )
    parse_metadata["profile_insights"] = insights
    parse_metadata["profile_extraction_mode"] = profile_mode
    parse_metadata["profile_extraction_warnings"] = profile_warnings
    parse_metadata["profile_validation"] = diagnostics.get("validation", {})
    parse_metadata["profile_parser_diagnostics"] = diagnostics
    parse_metadata["profile_parser_backend"] = diagnostics.get("parser_backend")
    parse_metadata["profile_parser_label"] = diagnostics.get("parser_backend_label")
    parse_metadata.update(annotate_document_profile_metadata(document, insights))
    document.parse_metadata = parse_metadata
    session.flush()
    sync_document_structured_profile_claims(session, profile, document, settings=settings)

    rebuild_profile_overview(session, profile, settings)
    session.commit()
    session.refresh(document)

    auto_sections = [
        key
        for key in ("identity", "skills", "education", "work_experience", "projects", "certifications")
        if (
            key == "identity"
            and any(insights.get("identity", {}).get(field) for field in ("full_name", "headline", "summary", "emails", "phones"))
        ) or (key != "identity" and insights.get(key))
    ]
    return auto_sections, profile_warnings


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite=settings.session_cookie_samesite,
        secure=settings.session_cookie_secure_effective,
        max_age=60 * 60 * 24 * 30,
        path="/",
        domain=settings.session_cookie_domain,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        domain=settings.session_cookie_domain,
        secure=settings.session_cookie_secure_effective,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    ensure_runtime_directories(resolved_settings)
    init_engine(resolved_settings.database_url)
    init_db()
    with session_scope() as session:
        sync_profile_graph(session)
        session.commit()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description="Evidence-backed profile claim engine for resume RAG.",
    )
    app.state.settings = resolved_settings
    app.add_middleware(GZipMiddleware, minimum_size=resolved_settings.gzip_minimum_size)
    if resolved_settings.allowed_host_list != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_host_list)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()

        if request_exceeds_upload_limit(request, resolved_settings):
            LOGGER.warning(
                "request_rejected request_id=%s method=%s path=%s reason=content_length_exceeded",
                request_id,
                request.method,
                request.url.path,
            )
            response = JSONResponse(
                status_code=413,
                content={
                    "detail": (
                        f"Request body exceeds the {resolved_settings.max_upload_size_mb} MB upload limit."
                    ),
                    "request_id": request_id,
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            LOGGER.exception(
                "request_failed request_id=%s method=%s path=%s duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request_complete request_id=%s method=%s path=%s status_code=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    LOGGER.info(
        "startup_complete environment=%s version=%s public_base_url=%s secure_cookies=%s",
        resolved_settings.app_env,
        resolved_settings.app_version,
        resolved_settings.public_base_url or "local-only",
        resolved_settings.session_cookie_secure_effective,
    )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/job", include_in_schema=False)
    async def job_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "job.html")

    @app.get("/wiki", include_in_schema=False)
    async def wiki_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "wiki.html")

    @app.get("/benchmarks", include_in_schema=False)
    async def benchmarks_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "benchmarks.html")

    @app.get("/profile", include_in_schema=False)
    async def profile_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "profile.html")

    @app.get("/login", include_in_schema=False)
    async def login_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/register", include_in_schema=False)
    async def register_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "register.html")

    @app.get("/profiles/select", include_in_schema=False)
    async def profile_select_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "profiles.html")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            **runtime_status_payload(resolved_settings),
            "status": "ok",
            "ready_status": readiness_payload(resolved_settings)["status"],
        }

    @app.get("/health/live")
    async def health_live() -> dict[str, Any]:
        return {
            "status": "ok",
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "app_version": resolved_settings.app_version,
            "environment": resolved_settings.app_env,
        }

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        return readiness_payload(resolved_settings)

    @app.post("/auth/register", response_model=AuthSessionRead)
    async def register(
        payload: RegisterRequest,
        response: Response,
        session: Session = Depends(get_session_async),
    ) -> AuthSessionRead:
        user = create_user(session, payload.full_name, payload.email, payload.password)
        _, raw_token = create_user_session(session, user)
        set_session_cookie(response, raw_token, resolved_settings)
        return AuthSessionRead(user=serialize_user(user))

    @app.post("/auth/login", response_model=AuthSessionRead)
    async def login(
        payload: LoginRequest,
        response: Response,
        session: Session = Depends(get_session_async),
    ) -> AuthSessionRead:
        user = authenticate_user(session, payload.email, payload.password)
        _, raw_token = create_user_session(session, user)
        set_session_cookie(response, raw_token, resolved_settings)
        return AuthSessionRead(user=serialize_user(user))

    @app.post("/auth/logout")
    async def logout(
        request: Request,
        response: Response,
        session: Session = Depends(get_session_async),
    ) -> dict[str, str]:
        revoke_session(session, request.cookies.get(SESSION_COOKIE_NAME))
        clear_session_cookie(response, resolved_settings)
        return {"status": "logged_out"}

    @app.get("/auth/session", response_model=AuthSessionRead)
    async def auth_session(current_user: User = Depends(get_current_user)) -> AuthSessionRead:
        return AuthSessionRead(user=serialize_user(current_user))

    @app.post("/job-description/parse", response_model=JobDescriptionParseResponse)
    async def parse_job_description(
        file: UploadFile,
        current_user: User = Depends(get_current_user),
        app_settings: Settings = Depends(get_app_settings),
    ) -> JobDescriptionParseResponse:
        del current_user
        text, parse_metadata, filename = parse_uploaded_job_description(file, app_settings)
        return JobDescriptionParseResponse(
            filename=filename,
            text=text,
            parse_metadata=parse_metadata,
        )

    @app.get("/resume-parsers", response_model=list[ResumeParserBackendRead])
    async def list_resume_parsers(
        current_user: User = Depends(get_current_user),
    ) -> list[ResumeParserBackendRead]:
        del current_user
        return [ResumeParserBackendRead(**item) for item in resume_parser_backends(resolved_settings)]

    @app.get("/benchmark/dataset", response_model=BenchmarkDatasetRead)
    async def get_benchmark_dataset(
        current_user: User = Depends(get_current_user),
        app_settings: Settings = Depends(get_app_settings),
    ) -> BenchmarkDatasetRead:
        del current_user
        return BenchmarkDatasetRead(**benchmark_dataset_summary(app_settings))

    @app.get("/benchmark/latest", response_model=BenchmarkRunRead)
    async def get_latest_benchmark_report(
        current_user: User = Depends(get_current_user),
        app_settings: Settings = Depends(get_app_settings),
    ) -> BenchmarkRunRead:
        del current_user
        latest = load_latest_benchmark_report(app_settings)
        if not latest:
            raise HTTPException(status_code=404, detail="No saved benchmark report yet.")
        return BenchmarkRunRead(**latest)

    @app.post("/benchmark/run", response_model=BenchmarkRunRead)
    async def run_benchmark(
        payload: BenchmarkRunRequest,
        current_user: User = Depends(get_current_user),
        app_settings: Settings = Depends(get_app_settings),
    ) -> BenchmarkRunRead:
        del current_user
        try:
            parser_choice = validate_resume_parser_choice(app_settings, payload.parser_backend)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        report = run_resume_benchmark(
            app_settings,
            parser_backend=parser_choice or "auto",
            limit=payload.limit,
            categories=payload.categories,
            resume_ids=payload.resume_ids,
            allow_remote_models=payload.allow_remote_models,
        )
        return BenchmarkRunRead(**report)

    @app.get("/profiles", response_model=list[ProfileRead])
    async def list_profiles(
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> list[ProfileRead]:
        return [ProfileRead(**item) for item in build_profile_summaries_for_user(session, current_user)]

    @app.post("/profiles", response_model=ProfileRead)
    async def create_profile_route(
        payload: ProfileCreateRequest,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileRead:
        profile = create_profile(session, current_user, payload.name)
        profile_row = next(item for item in build_profile_summaries_for_user(session, current_user) if item["id"] == profile.id)
        return ProfileRead(**profile_row)

    @app.patch("/profiles/{profile_id}", response_model=ProfileRead)
    async def rename_profile_route(
        profile_id: str,
        payload: ProfileUpdateRequest,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileRead:
        profile = resolve_profile(session, current_user, profile_id)
        updated = rename_profile(session, current_user, profile, payload.name)
        profile_row = next(item for item in build_profile_summaries_for_user(session, current_user) if item["id"] == updated.id)
        return ProfileRead(**profile_row)

    @app.delete("/profiles/{profile_id}")
    async def delete_profile_route(
        profile_id: str,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> dict[str, str]:
        profile = resolve_profile(session, current_user, profile_id)
        deleted_name = profile.name
        upload_dir = delete_profile(session, current_user, profile, app_settings.uploads_dir)
        sync_profile_graph(session)
        session.commit()
        shutil.rmtree(upload_dir, ignore_errors=True)
        return {"status": "deleted", "profile_id": profile_id, "profile_name": deleted_name}

    @app.get("/dashboard/summary", response_model=DashboardSummary)
    async def dashboard_summary(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> DashboardSummary:
        profile = resolve_profile(session, current_user, profile_id)
        documents_total = session.scalar(
            select(func.count(Document.id)).where(Document.profile_id == profile.id)
        ) or 0
        pending_claims_total = session.scalar(
            select(func.count(Claim.id))
            .join(Document, Claim.document_id == Document.id)
            .where(Document.profile_id == profile.id, Claim.status == "pending")
        ) or 0
        approved_claims_total = session.scalar(
            select(func.count(ProfileClaim.id))
            .join(Document, ProfileClaim.document_id == Document.id)
            .where(Document.profile_id == profile.id)
        ) or 0
        rejected_claims_total = session.scalar(
            select(func.count(Claim.id))
            .join(Document, Claim.document_id == Document.id)
            .where(Document.profile_id == profile.id, Claim.status == "rejected")
        ) or 0
        graph_nodes_total = session.scalar(
            select(func.count(ProfileGraphNode.id)).where(ProfileGraphNode.profile_id == profile.id)
        ) or 0
        graph_edges_total = session.scalar(
            select(func.count(ProfileGraphEdge.id)).where(ProfileGraphEdge.profile_id == profile.id)
        ) or 0
        overview = profile_overview_payload(profile, current_user)
        parser_backend = resolve_resume_parser_backend(resolved_settings)
        if resolved_settings.enable_resume_gpt_formatter and resolved_settings.openai_api_key:
            extractor_mode = "docling_ner_gpt" if parser_backend == "docling_structured" else "openresume_ner_gpt"
        elif resolved_settings.enable_resume_ner:
            extractor_mode = "docling_ner_local" if parser_backend == "docling_structured" else "openresume_ner_local"
        elif llm_available(resolved_settings):
            extractor_mode = "llm"
        else:
            extractor_mode = "heuristic"
        return DashboardSummary(
            profile_id=profile.id,
            profile_name=profile.name,
            documents_total=documents_total,
            pending_claims_total=pending_claims_total,
            approved_claims_total=approved_claims_total,
            rejected_claims_total=rejected_claims_total,
            graph_nodes_total=graph_nodes_total,
            graph_edges_total=graph_edges_total,
            skills_total=len(overview["skills"]),
            work_experience_total=len(overview["work_experience"]),
            education_total=len(overview["education"]),
            projects_total=len(overview["projects"]),
            llm_available=llm_available(resolved_settings),
            embedding_retrieval_available=embedding_available(resolved_settings),
            parser_backend=parser_backend,
            extractor_mode=extractor_mode,
            openai_model=resolved_settings.openai_model if llm_available(resolved_settings) else None,
            openai_embedding_model=resolved_settings.openai_embedding_model if embedding_available(resolved_settings) else None,
        )

    @app.get("/profile/overview", response_model=ProfileOverviewRead)
    async def get_profile_overview(
        profile_id: str | None = None,
        view: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> ProfileOverviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        if not profile.profile_data:
            rebuild_profile_overview(session, profile, app_settings)
            session.commit()
            session.refresh(profile)
        return ProfileOverviewRead(**profile_overview_payload(profile, current_user, view=view))

    @app.patch("/profile/overview", response_model=ProfileOverviewRead)
    async def update_profile_overview(
        payload: ProfileOverviewUpdateRequest,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileOverviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        overview = update_manual_profile_overrides(
            session,
            profile,
            identity=payload.identity.model_dump() if payload.identity is not None else None,
            skills=payload.skills,
            public_profiles=[item.model_dump() for item in payload.public_profiles] if payload.public_profiles is not None else None,
        )
        return ProfileOverviewRead(**overview)

    @app.delete("/profile/overview/manual", response_model=ProfileOverviewRead)
    async def reset_profile_overrides(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileOverviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        overview = reset_manual_profile_overrides(session, profile)
        return ProfileOverviewRead(**overview)

    @app.get("/profile/studio/review", response_model=StructuredProfileReviewRead)
    async def get_profile_studio_review(
        profile_id: str | None = None,
        view: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> StructuredProfileReviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        if not profile.profile_data:
            rebuild_profile_overview(session, profile, app_settings)
            session.commit()
            session.refresh(profile)

        documents = list(
            session.scalars(
                select(Document).where(Document.profile_id == profile.id)
            ).all()
        )
        for document in documents:
            if not document.parse_metadata.get("profile_insights"):
                refresh_document_profile(
                    session,
                    document=document,
                    profile=profile,
                    settings=app_settings,
                )
            if document_structured_claims_need_sync(session, profile, document):
                sync_document_structured_profile_claims(session, profile, document, settings=app_settings)
        session.commit()
        session.refresh(profile)
        payload = build_structured_profile_review(session, profile, current_user, view=view, settings=app_settings)
        session.commit()
        session.refresh(profile)
        return StructuredProfileReviewRead(**payload)

    @app.patch("/profile/studio/claims/{claim_id}", response_model=StructuredProfileClaimRead)
    async def update_profile_studio_claim_route(
        claim_id: str,
        payload: StructuredProfileClaimUpdateRequest,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> StructuredProfileClaimRead:
        profile = resolve_profile(session, current_user, profile_id)
        claim = ensure_structured_claim_in_profile(session, claim_id, profile)
        update_structured_profile_claim(
            session,
            claim=claim,
            status=payload.status,
            section=payload.section,
            value_json=payload.value_json,
        )
        if claim.status in {"accepted", "edited"}:
            maybe_record_correction_rule(session, profile, claim)
        session.commit()
        session.refresh(claim)
        document = session.get(Document, claim.document_id)
        return StructuredProfileClaimRead(**serialize_structured_profile_claim(claim, document))

    @app.post("/profile/studio/claims/accept-all")
    async def accept_all_profile_studio_claims_route(
        profile_id: str | None = None,
        document_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> dict[str, Any]:
        profile = resolve_profile(session, current_user, profile_id)
        updated = accept_all_structured_profile_claims(
            session,
            profile=profile,
            document_id=document_id,
        )
        session.commit()
        return {"status": "ok", "updated": updated}

    @app.post("/profile/studio/save", response_model=ProfileOverviewRead)
    async def save_profile_studio_route(
        profile_id: str | None = None,
        view: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> ProfileOverviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        overview = save_canonical_profile_from_structured_claims(session, profile, current_user, view=view, settings=app_settings)
        session.commit()
        session.refresh(profile)
        return ProfileOverviewRead(**overview)

    @app.delete("/profile/studio/canonical", response_model=ProfileOverviewRead)
    async def clear_profile_studio_canonical_route(
        profile_id: str | None = None,
        view: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileOverviewRead:
        profile = resolve_profile(session, current_user, profile_id)
        clear_canonical_profile(session, profile)
        session.commit()
        session.refresh(profile)
        return ProfileOverviewRead(**profile_overview_payload(profile, current_user, source="auto", view=view))

    @app.post("/documents/upload", response_model=DocumentIngestResponse)
    async def upload_document(
        file: UploadFile,
        profile_id: str | None = Form(None),
        parser_backend: str | None = Form(None),
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> DocumentIngestResponse:
        profile = resolve_profile(session, current_user, profile_id)
        try:
            parser_choice = validate_resume_parser_choice(app_settings, parser_backend)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ingest_and_process_uploaded_document(
            session,
            upload_file=file,
            profile=profile,
            settings=app_settings,
            parser_choice=parser_choice,
        )

    @app.post("/documents/upload-batch", response_model=DocumentBatchIngestResponse)
    async def upload_documents_batch(
        files: list[UploadFile] = File(...),
        profile_id: str | None = Form(None),
        parser_backend: str | None = Form(None),
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> DocumentBatchIngestResponse:
        profile = resolve_profile(session, current_user, profile_id)
        try:
            parser_choice = validate_resume_parser_choice(app_settings, parser_backend)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        uploads: list[DocumentIngestResponse] = []
        failures: list[DocumentBatchFailureRead] = []
        auto_profile_sections: set[str] = set()
        warnings: list[str] = []
        chunks_created = 0
        auto_approved_claims = 0

        for upload_file in files:
            try:
                item = ingest_and_process_uploaded_document(
                    session,
                    upload_file=upload_file,
                    profile=profile,
                    settings=app_settings,
                    parser_choice=parser_choice,
                )
            except HTTPException as exc:
                session.rollback()
                failures.append(
                    DocumentBatchFailureRead(
                        filename=upload_file.filename or "document",
                        detail=str(exc.detail),
                    )
                )
                continue
            except Exception as exc:
                session.rollback()
                failures.append(
                    DocumentBatchFailureRead(
                        filename=upload_file.filename or "document",
                        detail=f"{exc.__class__.__name__}: {exc}",
                    )
                )
                continue

            uploads.append(item)
            chunks_created += item.chunks_created
            auto_approved_claims += item.auto_approved_claims
            auto_profile_sections.update(item.auto_profile_sections)
            warnings.extend(item.warnings)

        return DocumentBatchIngestResponse(
            uploads=uploads,
            failures=failures,
            documents_created=len(uploads),
            chunks_created=chunks_created,
            auto_approved_claims=auto_approved_claims,
            auto_profile_sections=sorted(auto_profile_sections),
            warnings=warnings,
        )

    @app.get("/documents", response_model=list[DocumentRead])
    async def list_documents(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> list[Document]:
        profile = resolve_profile(session, current_user, profile_id)
        return list(
            session.scalars(
                select(Document)
                .where(Document.profile_id == profile.id)
                .order_by(Document.created_at.desc())
            ).all()
        )

    @app.post("/documents/{document_id}/reparse", response_model=DocumentReparseResponse)
    async def reparse_document_route(
        document_id: str,
        profile_id: str | None = None,
        parser_backend: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> DocumentReparseResponse:
        profile = resolve_profile(session, current_user, profile_id)
        document = ensure_document_in_profile(session.get(Document, document_id), profile)
        try:
            parser_choice = validate_resume_parser_choice(app_settings, parser_backend)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        auto_profile_sections, warnings = refresh_document_profile(
            session,
            document=document,
            profile=profile,
            settings=app_settings,
            parser_backend=parser_choice,
        )
        return DocumentReparseResponse(
            document=document,
            auto_profile_sections=auto_profile_sections,
            warnings=warnings,
        )

    @app.get("/documents/{document_id}/parser-comparisons", response_model=ResumeParserComparisonResponse)
    async def compare_document_parsers(
        document_id: str,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> ResumeParserComparisonResponse:
        profile = resolve_profile(session, current_user, profile_id)
        document = ensure_document_in_profile(session.get(Document, document_id), profile)
        payload = compare_resume_parser_backends(document, app_settings)
        return ResumeParserComparisonResponse(
            document_id=document.id,
            active_backend=payload["active_backend"],
            available_backends=[ResumeParserBackendRead(**item) for item in payload["available_backends"]],
            comparisons=[ResumeParserComparisonRunRead(**item) for item in payload["comparisons"]],
        )

    @app.delete("/documents/{document_id}")
    async def delete_document_route(
        document_id: str,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> dict[str, str]:
        profile = resolve_profile(session, current_user, profile_id)
        document = ensure_document_in_profile(session.get(Document, document_id), profile)
        filename = document.filename
        storage_path = delete_document_evidence(session, document)
        rollback_profile_after_evidence_delete(session, profile, current_user, settings=app_settings)
        sync_profile_graph(session)
        session.commit()
        cleanup_document_storage(storage_path)
        return {"status": "deleted", "document_id": document_id, "filename": filename}

    @app.post("/documents/{document_id}/extract-claims", response_model=ClaimExtractionResponse)
    async def extract_claims(
        document_id: str,
        payload: ClaimExtractionRequest,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> ClaimExtractionResponse:
        profile = resolve_profile(session, current_user, profile_id)
        document = ensure_document_in_profile(session.get(Document, document_id), profile)

        retrieved_chunks, claims, extractor_mode, warnings = extract_claims_for_document(
            session,
            document=document,
            settings=app_settings,
            focus_areas=payload.focus_areas,
            max_claims=payload.max_claims,
        )

        return ClaimExtractionResponse(
            document_id=document_id,
            extractor_mode=extractor_mode,
            warnings=warnings,
            retrieved_chunks=[
                ChunkSearchHit(
                    chunk_id=item.chunk.id,
                    document_id=item.document.id,
                    filename=item.document.filename,
                    score=round(item.score, 4),
                    score_components=item.score_components,
                    text=item.chunk.text,
                    start_char=item.chunk.start_char,
                    end_char=item.chunk.end_char,
                )
                for item in retrieved_chunks
            ],
            claims=[serialize_claim_detail(session, claim) for claim in claims],
        )

    @app.get("/documents/{document_id}/claims", response_model=list[ClaimDetailRead])
    async def list_document_claims(
        document_id: str,
        status: str | None = None,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> list[ClaimDetailRead]:
        profile = resolve_profile(session, current_user, profile_id)
        ensure_document_in_profile(session.get(Document, document_id), profile)
        statement = select(Claim).where(Claim.document_id == document_id)
        if status:
            statement = statement.where(Claim.status == status)
        claims = list(session.scalars(statement.order_by(Claim.created_at.desc())).all())
        return [serialize_claim_detail(session, claim) for claim in claims]

    @app.get("/claims/{claim_id}", response_model=ClaimDetailRead)
    async def get_claim(
        claim_id: str,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ClaimDetailRead:
        profile = resolve_profile(session, current_user, profile_id)
        claim = ensure_claim_in_profile(session, session.get(Claim, claim_id), profile)
        return serialize_claim_detail(session, claim)

    @app.post("/claims/{claim_id}/review", response_model=ClaimDetailRead)
    async def review_claim(
        claim_id: str,
        payload: ReviewClaimRequest,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ClaimDetailRead:
        profile = resolve_profile(session, current_user, profile_id)
        claim = ensure_claim_in_profile(session, session.get(Claim, claim_id), profile)

        apply_claim_review(session, claim, status=payload.status, note=payload.note)
        sync_profile_graph(session)
        session.commit()
        session.refresh(claim)
        return serialize_claim_detail(session, claim)

    @app.get("/claims", response_model=list[ClaimDetailRead])
    async def list_claims(
        status: str | None = None,
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> list[ClaimDetailRead]:
        profile = resolve_profile(session, current_user, profile_id)
        statement = (
            select(Claim)
            .join(Document, Claim.document_id == Document.id)
            .where(Document.profile_id == profile.id)
            .order_by(Claim.created_at.desc())
        )
        if status:
            statement = statement.where(Claim.status == status)
        claims = list(session.scalars(statement).all())
        return [serialize_claim_detail(session, claim) for claim in claims]

    @app.get("/profile/claims", response_model=list[ProfileClaimRead])
    async def list_profile_claims(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> list[ProfileClaimRead]:
        profile = resolve_profile(session, current_user, profile_id)
        profile_claims = list(
            session.scalars(
                select(ProfileClaim)
                .join(Document, ProfileClaim.document_id == Document.id)
                .where(Document.profile_id == profile.id)
                .order_by(ProfileClaim.created_at.desc())
            ).all()
        )
        return [serialize_profile_claim(session, profile_claim) for profile_claim in profile_claims]

    @app.get("/profile/graph", response_model=ProfileGraphRead)
    async def get_profile_graph(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileGraphRead:
        profile = resolve_profile(session, current_user, profile_id)
        nodes = list(
            session.scalars(
                select(ProfileGraphNode)
                .where(ProfileGraphNode.profile_id == profile.id)
                .order_by(ProfileGraphNode.node_type.asc(), ProfileGraphNode.weight.desc())
            ).all()
        )
        edges = list(
            session.scalars(
                select(ProfileGraphEdge)
                .where(ProfileGraphEdge.profile_id == profile.id)
                .order_by(ProfileGraphEdge.weight.desc(), ProfileGraphEdge.relation_type.asc())
            ).all()
        )
        return ProfileGraphRead(
            nodes=[ProfileGraphNodeRead.model_validate(node) for node in nodes],
            edges=[ProfileGraphEdgeRead.model_validate(edge) for edge in edges],
        )

    @app.get("/profile/wiki", response_model=ProfileWikiRead)
    async def get_profile_wiki(
        profile_id: str | None = None,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
    ) -> ProfileWikiRead:
        profile = resolve_profile(session, current_user, profile_id)
        return ProfileWikiRead(**build_profile_wiki(session, profile.id))

    @app.post("/search", response_model=SearchResponse)
    async def search(
        payload: SearchRequest,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session_async),
        app_settings: Settings = Depends(get_app_settings),
    ) -> SearchResponse:
        profile = resolve_profile(session, current_user, payload.profile_id)
        hits = search_chunks(
            session,
            query=payload.query,
            top_k=payload.top_k,
            document_id=payload.document_id,
            profile_id=profile.id,
            settings=app_settings,
        )
        return SearchResponse(
            query=payload.query,
            hits=[
                ChunkSearchHit(
                    chunk_id=item.chunk.id,
                    document_id=item.document.id,
                    filename=item.document.filename,
                    score=round(item.score, 4),
                    score_components=item.score_components,
                    text=item.chunk.text,
                    start_char=item.chunk.start_char,
                    end_char=item.chunk.end_char,
                )
                for item in hits
            ],
        )

    return app
