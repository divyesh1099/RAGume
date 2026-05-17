import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CorrectionEmbedding, Document, Profile, StructuredProfileClaim, User
from app.services.correction_resolver import (
    correction_arbiter_available,
    resolve_structured_profile_claims,
    sync_canonical_values_from_overview,
)
from app.services.embeddings import correction_embedding_available, correction_embedding_model_name, correction_embedding_provider
from app.services.profile_memory import (
    _default_identity,
    _default_overview_data,
    _merge_identity,
    _merge_item_collection,
    _normalize_identity,
    _normalize_overview_data,
    _normalize_profile_container,
    _unique_links,
    _unique_strings,
    profile_overview_payload,
)


SCALAR_IDENTITY_FIELDS = ("full_name", "headline", "summary", "location")
COMPLEX_SECTION_ORDER = ("work_experience", "projects", "education", "certifications")
REVIEW_SECTION_ORDER = (
    "identity",
    "skills",
    "work_experience",
    "projects",
    "education",
    "certifications",
    "public_profiles",
)
REVIEW_SECTION_LABELS = {
    "identity": "Personal",
    "skills": "Skills",
    "work_experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
    "public_profiles": "Links",
}
REVIEWABLE_STATUSES = {"accepted", "edited"}
STRUCTURED_PROFILE_RESOLVER_VERSION = "correction-v3"


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _claim_value_text(section: str, field_name: str, value_json: dict[str, Any]) -> str:
    if section == "identity":
        return _string_value(value_json.get("value"))
    if section == "skills":
        return _string_value(value_json.get("name"))
    if section == "public_profiles":
        label = _string_value(value_json.get("label"))
        url = _string_value(value_json.get("url"))
        return " · ".join(part for part in (label, url) if part) or url
    if section == "work_experience":
        parts = [
            _string_value(value_json.get("title")),
            _string_value(value_json.get("organization")),
            " - ".join(part for part in (_string_value(value_json.get("start_date")), _string_value(value_json.get("end_date"))) if part),
        ]
        return " · ".join(part for part in parts if part)
    if section == "education":
        parts = [
            _string_value(value_json.get("degree")),
            _string_value(value_json.get("institution")),
            _string_value(value_json.get("field_of_study")),
        ]
        return " · ".join(part for part in parts if part)
    if section == "projects":
        parts = [
            _string_value(value_json.get("name")),
            _string_value(value_json.get("summary")),
        ]
        return " · ".join(part for part in parts if part)
    if section == "certifications":
        parts = [
            _string_value(value_json.get("name")),
            _string_value(value_json.get("issuer")),
            _string_value(value_json.get("credential_id")),
        ]
        return " · ".join(part for part in parts if part)
    return _string_value(value_json)


def _claim_source_text(section: str, value_json: dict[str, Any]) -> str | None:
    if section in {"identity", "skills"}:
        return _string_value(value_json.get("value") or value_json.get("name")) or None
    if section == "public_profiles":
        return _string_value(value_json.get("url")) or None
    if section in {"work_experience", "projects", "education", "certifications"}:
        parts = []
        if value_json.get("summary"):
            parts.append(_string_value(value_json["summary"]))
        highlights = [_string_value(item) for item in value_json.get("highlights", []) if _string_value(item)]
        if highlights:
            parts.extend(highlights[:2])
        return " ".join(part for part in parts if part) or None
    return None


def _claim_normalized_value(section: str, field_name: str, value_json: dict[str, Any]) -> str:
    normalized_json = json.dumps(value_json, sort_keys=True, ensure_ascii=True).lower()
    return f"{section}|{field_name}|{normalized_json}"[:512]


def _claim_confidence(section: str, field_name: str, value_json: dict[str, Any], *, base_score: int) -> float:
    completion_bonus = 0.0
    if section == "identity":
        completion_bonus = 0.08 if _string_value(value_json.get("value")) else 0.0
    elif section == "skills":
        completion_bonus = 0.06
    elif section == "public_profiles":
        completion_bonus = 0.08 if _string_value(value_json.get("url")) else 0.02
    else:
        important_keys = {
            "work_experience": ("title", "organization", "summary"),
            "projects": ("name", "summary"),
            "education": ("degree", "institution"),
            "certifications": ("name", "issuer"),
        }.get(section, ())
        completion_bonus = min(
            0.18,
            sum(0.06 for key in important_keys if _string_value(value_json.get(key))),
        )
        if field_name == "entry" and value_json.get("highlights"):
            completion_bonus += 0.04

    base = max(0.4, min(0.92, base_score / 100))
    return round(min(0.98, base + completion_bonus), 3)


def structured_profile_claim_sync_key(document: Document) -> str:
    parse_metadata = dict(document.parse_metadata or {})
    payload = {
        "profile_insights": parse_metadata.get("profile_insights") or {},
        "profile_parser_backend": parse_metadata.get("profile_parser_backend"),
        "profile_extraction_mode": parse_metadata.get("profile_extraction_mode"),
        "profile_validation": parse_metadata.get("profile_validation") or {},
        "resolver_version": STRUCTURED_PROFILE_RESOLVER_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def document_structured_claims_need_sync(session: Session, profile: Profile, document: Document) -> bool:
    parse_metadata = dict(document.parse_metadata or {})
    stored_key = parse_metadata.get("structured_profile_claims_sync_key")
    current_key = structured_profile_claim_sync_key(document)
    if stored_key != current_key:
        return True

    existing_claim = session.scalar(
        select(StructuredProfileClaim.id)
        .where(
            StructuredProfileClaim.profile_id == profile.id,
            StructuredProfileClaim.document_id == document.id,
        )
        .limit(1)
    )
    return existing_claim is None


def _identity_claims(identity: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    claims: list[tuple[str, dict[str, Any]]] = []
    for field_name in SCALAR_IDENTITY_FIELDS:
        value = _string_value(identity.get(field_name))
        if value:
            claims.append((field_name, {"value": value}))
    for email in identity.get("emails", []):
        value = _string_value(email)
        if value:
            claims.append(("email", {"value": value}))
    for phone in identity.get("phones", []):
        value = _string_value(phone)
        if value:
            claims.append(("phone", {"value": value}))
    return claims


def _simple_claims(section: str, values: list[Any], *, key_name: str) -> list[tuple[str, dict[str, Any]]]:
    claims: list[tuple[str, dict[str, Any]]] = []
    for value in values:
        if isinstance(value, dict):
            payload = {key_name: _string_value(value.get(key_name))}
        else:
            payload = {key_name: _string_value(value)}
        if payload[key_name]:
            claims.append((key_name.rstrip("s"), payload))
    return claims


def _claim_raw_signature(field_name: str, value_json: dict[str, Any]) -> str:
    normalized_json = json.dumps(value_json, sort_keys=True, ensure_ascii=True).lower()
    return f"{field_name}|raw|{normalized_json}"[:512]


def _refresh_claim_derived_fields(claim: StructuredProfileClaim) -> None:
    value_json = dict(claim.value_json or {})
    claim.value_text = _claim_value_text(claim.section, claim.field_name, value_json)
    claim.normalized_value = _claim_normalized_value(claim.section, claim.field_name, value_json)
    claim.source_text = _claim_source_text(claim.section, value_json)


def sync_document_structured_profile_claims(
    session: Session,
    profile: Profile,
    document: Document,
    settings: Settings | None = None,
) -> list[StructuredProfileClaim]:
    parse_metadata = dict(document.parse_metadata or {})
    insights = _normalize_overview_data(parse_metadata.get("profile_insights") or {})
    validation = parse_metadata.get("profile_validation") or {}
    parser_name = (
        parse_metadata.get("profile_parser_backend")
        or parse_metadata.get("profile_parser_label")
        or parse_metadata.get("parser")
        or "parser"
    )
    base_score = int(validation.get("score") or 68)

    existing_claims = list(
        session.scalars(
            select(StructuredProfileClaim).where(
                StructuredProfileClaim.profile_id == profile.id,
                StructuredProfileClaim.document_id == document.id,
            )
        ).all()
    )
    preserved_claims = {
        _claim_raw_signature(claim.field_name, dict(claim.raw_value_json or claim.value_json or {})): {
            "section": claim.section,
            "value_json": dict(claim.value_json or {}),
            "status": claim.status,
            "resolver_action": claim.resolver_action,
            "resolver_confidence": claim.resolver_confidence,
            "resolver_evidence": list(claim.resolver_evidence or []),
            "suggested_section": claim.suggested_section,
        }
        for claim in existing_claims
        if claim.status in {"accepted", "edited", "rejected", "duplicate"}
    }
    for claim in existing_claims:
        session.delete(claim)
    session.flush()

    created: list[StructuredProfileClaim] = []
    position = 0

    def add_claim(section: str, field_name: str, value_json: dict[str, Any]) -> None:
        nonlocal position
        raw_value_json = dict(value_json)
        preserved = preserved_claims.get(_claim_raw_signature(field_name, raw_value_json))
        stored_section = str(preserved["section"]) if preserved else section
        stored_value_json = (
            dict(preserved["value_json"])
            if preserved and preserved["status"] in {"accepted", "edited"}
            else raw_value_json
        )
        value_text = _claim_value_text(stored_section, field_name, stored_value_json)
        if not value_text:
            return
        normalized_value = _claim_normalized_value(stored_section, field_name, stored_value_json)
        claim = StructuredProfileClaim(
            profile_id=profile.id,
            document_id=document.id,
            section=stored_section,
            field_name=field_name,
            raw_value_json=raw_value_json,
            value_json=stored_value_json,
            value_text=value_text,
            normalized_value=normalized_value,
            source_text=_claim_source_text(stored_section, stored_value_json),
            source_page=1 if document.mime_type == "application/pdf" else None,
            source_bbox={},
            parser_name=str(parser_name),
            confidence=_claim_confidence(section, field_name, raw_value_json, base_score=base_score),
            resolver_confidence=float(preserved["resolver_confidence"]) if preserved else 0.0,
            resolver_action=str(preserved["resolver_action"]) if preserved else "keep",
            resolver_evidence=list(preserved["resolver_evidence"]) if preserved else [],
            suggested_section=str(preserved["suggested_section"]) if preserved and preserved["suggested_section"] else None,
            status=str(preserved["status"]) if preserved else "pending",
            position=position,
        )
        position += 1
        session.add(claim)
        created.append(claim)

    for field_name, value_json in _identity_claims(insights.get("identity", {})):
        add_claim("identity", field_name, value_json)

    for skill in insights.get("skills", []):
        add_claim("skills", "skill", {"name": _string_value(skill)})

    for link in insights.get("public_profiles", []):
        add_claim(
            "public_profiles",
            "link",
            {"label": _string_value(link.get("label") or "Link"), "url": _string_value(link.get("url"))},
        )

    for section in COMPLEX_SECTION_ORDER:
        for item in insights.get(section, []):
            add_claim(section, "entry", dict(item))

    resolve_structured_profile_claims(session, profile, created, settings=settings)
    for claim in created:
        _refresh_claim_derived_fields(claim)

    parse_metadata["structured_profile_claims_sync_key"] = structured_profile_claim_sync_key(document)
    document.parse_metadata = parse_metadata
    session.flush()
    return created


def serialize_structured_profile_claim(claim: StructuredProfileClaim, document: Document | None = None) -> dict[str, Any]:
    return {
        "id": claim.id,
        "profile_id": claim.profile_id,
        "document_id": claim.document_id,
        "document_filename": document.filename if document else None,
        "section": claim.section,
        "field_name": claim.field_name,
        "raw_value_json": dict(claim.raw_value_json or {}),
        "value_json": dict(claim.value_json or {}),
        "value_text": claim.value_text,
        "normalized_value": claim.normalized_value,
        "source_text": claim.source_text,
        "source_page": claim.source_page,
        "source_bbox": dict(claim.source_bbox or {}),
        "parser_name": claim.parser_name,
        "confidence": claim.confidence,
        "resolver_confidence": claim.resolver_confidence,
        "resolver_action": claim.resolver_action,
        "resolver_evidence": list(claim.resolver_evidence or []),
        "suggested_section": claim.suggested_section,
        "status": claim.status,
        "position": claim.position,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


def _claims_for_profile(session: Session, profile: Profile) -> list[StructuredProfileClaim]:
    return list(
        session.scalars(
            select(StructuredProfileClaim)
            .where(StructuredProfileClaim.profile_id == profile.id)
            .order_by(
                StructuredProfileClaim.section.asc(),
                StructuredProfileClaim.position.asc(),
                StructuredProfileClaim.created_at.asc(),
            )
        ).all()
    )


def _build_profile_data_from_structured_claims(
    session: Session,
    profile: Profile,
    user: User | None = None,
    *,
    include_statuses: set[str] | None = None,
    exclude_statuses: set[str] | None = None,
) -> dict[str, Any]:
    all_claims = _claims_for_profile(session, profile)
    claims = [
        claim
        for claim in all_claims
        if (include_statuses is None or claim.status in include_statuses)
        and (exclude_statuses is None or claim.status not in exclude_statuses)
    ]

    canonical = _default_overview_data()
    merged_identity = _default_identity()
    work_items: list[dict[str, Any]] = []
    project_items: list[dict[str, Any]] = []
    education_items: list[dict[str, Any]] = []
    certification_items: list[dict[str, Any]] = []

    for claim in claims:
        preview_section = claim.suggested_section or claim.section
        value_json = dict(claim.value_json or {})
        if preview_section == "identity":
            if claim.field_name in SCALAR_IDENTITY_FIELDS:
                merged_identity = _merge_identity(merged_identity, {claim.field_name: value_json.get("value")})
            elif claim.field_name == "email":
                merged_identity["emails"] = _unique_strings([*merged_identity.get("emails", []), _string_value(value_json.get("value"))])
            elif claim.field_name == "phone":
                merged_identity["phones"] = _unique_strings([*merged_identity.get("phones", []), _string_value(value_json.get("value"))])
        elif preview_section == "skills":
            canonical["skills"] = _unique_strings([*canonical["skills"], _string_value(value_json.get("name"))])
        elif preview_section == "public_profiles":
            canonical["public_profiles"] = _unique_links([*canonical["public_profiles"], value_json])
        elif preview_section == "work_experience":
            work_items.append(value_json)
        elif preview_section == "projects":
            project_items.append(value_json)
        elif preview_section == "education":
            education_items.append(value_json)
        elif preview_section == "certifications":
            certification_items.append(value_json)

    merged_identity = _normalize_identity(merged_identity)
    if user is not None and not merged_identity.get("full_name"):
        merged_identity["full_name"] = user.full_name

    canonical["identity"] = merged_identity
    canonical["work_experience"] = _merge_item_collection(work_items, "work_experience")
    canonical["projects"] = _merge_item_collection(project_items, "projects")
    canonical["education"] = _merge_item_collection(education_items, "education")
    canonical["certifications"] = _merge_item_collection(certification_items, "certifications")

    documents = {
        document.id: document
        for document in session.scalars(
            select(Document).where(Document.profile_id == profile.id)
        ).all()
    }
    source_documents_map: dict[str, dict[str, Any]] = {}
    for claim in claims:
        preview_section = claim.suggested_section or claim.section
        document = documents.get(claim.document_id)
        if document is None:
            continue
        entry = source_documents_map.setdefault(
            document.id,
            {
                "document_id": document.id,
                "filename": document.filename,
                "created_at": document.created_at.isoformat() if document.created_at else None,
                "signals": [],
            },
        )
        if preview_section not in entry["signals"]:
            entry["signals"].append(preview_section)
    canonical["source_documents"] = list(source_documents_map.values())
    canonical["auto_updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    return _normalize_overview_data(canonical)


def build_review_preview_profile_from_structured_claims(session: Session, profile: Profile, user: User | None = None) -> dict[str, Any]:
    review_data = _build_profile_data_from_structured_claims(
        session,
        profile,
        user,
        exclude_statuses={"rejected", "duplicate"},
    )
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "profile_mode": "review",
        "identity": review_data["identity"],
        "skills": review_data["skills"],
        "public_profiles": review_data["public_profiles"],
        "education": review_data["education"],
        "work_experience": review_data["work_experience"],
        "projects": review_data["projects"],
        "certifications": review_data["certifications"],
        "source_documents": review_data["source_documents"],
        "documents_total": len(review_data["source_documents"]),
        "auto_updated_at": review_data["auto_updated_at"],
        "updated_at": profile.updated_at,
    }


def _build_profile_studio_diagnostics(
    session: Session,
    profile: Profile,
    claims: list[StructuredProfileClaim],
    documents: dict[str, Document],
    settings: Settings | None = None,
) -> dict[str, Any]:
    reason_counts: dict[str, int] = defaultdict(int)
    action_counts: dict[str, int] = defaultdict(int)
    cache_hits = 0
    cache_misses = 0
    semantic_matches = 0
    llm_arbiter_decisions = 0
    section_suggestions = 0

    for claim in claims:
        action_counts[claim.resolver_action or "keep"] += 1
        if claim.suggested_section and claim.suggested_section != claim.section:
            section_suggestions += 1
        for reason in claim.resolver_evidence or []:
            reason_counts[reason] += 1
            if reason == "embedding_similarity":
                semantic_matches += 1
            elif reason == "embedding_cache_hit":
                cache_hits += 1
            elif reason == "embedding_cache_miss":
                cache_misses += 1
            elif str(reason).startswith("llm_arbiter:"):
                llm_arbiter_decisions += 1

    correction_cache_total = len(
        session.scalars(select(CorrectionEmbedding).where(CorrectionEmbedding.profile_id == profile.id)).all()
    )

    parser_sources = []
    for document in documents.values():
        parse_metadata = dict(document.parse_metadata or {})
        diagnostics = parse_metadata.get("profile_parser_diagnostics") or {}
        validation = parse_metadata.get("profile_validation") or {}
        layout = diagnostics.get("layout") or {}
        parser_sources.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "parser_backend": parse_metadata.get("profile_parser_backend"),
                "extraction_mode": parse_metadata.get("profile_extraction_mode"),
                "validation_status": validation.get("status"),
                "validation_score": validation.get("score"),
                "warning_count": len(validation.get("warnings") or []),
                "page_count": int(layout.get("page_count") or parse_metadata.get("page_count") or 0),
                "block_count": int(layout.get("block_count") or parse_metadata.get("block_count") or 0),
                "section_counts": dict((diagnostics.get("validation") or {}).get("detected_sections") or {}),
                "embedding_status": parse_metadata.get("embedding_status"),
            }
        )

    parser_sources.sort(key=lambda item: (item["filename"].lower(), item["document_id"]))
    top_reason_codes = dict(sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:8])
    return {
        "correction": {
            "embedding_retrieval_enabled": bool(settings and correction_embedding_available(settings)),
            "correction_embedding_provider": correction_embedding_provider(settings) if settings and correction_embedding_available(settings) else "openai",
            "correction_embedding_model": correction_embedding_model_name(settings) if settings and correction_embedding_available(settings) else None,
            "correction_embedding_cache_entries": correction_cache_total,
            "correction_embedding_cache_hits": cache_hits,
            "correction_embedding_cache_misses": cache_misses,
            "llm_arbiter_enabled": correction_arbiter_available(settings),
            "llm_arbiter_provider": (settings.correction_arbiter_provider if settings else "openai"),
            "llm_arbiter_model": (
                (settings.ollama_arbiter_model if (settings and settings.correction_arbiter_provider == "ollama") else settings.correction_arbiter_model or settings.openai_model)
                if settings and correction_arbiter_available(settings)
                else None
            ),
            "llm_arbiter_decisions": llm_arbiter_decisions,
            "semantic_matches": semantic_matches,
            "section_suggestions": section_suggestions,
            "action_counts": dict(sorted(action_counts.items())),
            "top_reason_codes": top_reason_codes,
        },
        "parser_sources": parser_sources,
    }


def build_structured_profile_review(
    session: Session,
    profile: Profile,
    user: User,
    settings: Settings | None = None,
) -> dict[str, Any]:
    claims = _claims_for_profile(session, profile)
    documents = {
        document.id: document
        for document in session.scalars(select(Document).where(Document.profile_id == profile.id)).all()
    }

    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        by_section[claim.section].append(serialize_structured_profile_claim(claim, documents.get(claim.document_id)))

    extracted_profile = profile_overview_payload(profile, user, source="auto")
    review_preview_profile = build_review_preview_profile_from_structured_claims(session, profile, user)
    canonical_profile = profile_overview_payload(profile, user, source="canonical")
    correction_summary = {
        "auto_corrected": sum(1 for claim in claims if claim.resolver_action == "auto_correct" and claim.status != "duplicate"),
        "suggested": sum(1 for claim in claims if claim.resolver_action == "suggest"),
        "needs_review": sum(1 for claim in claims if claim.status == "pending" and claim.resolver_action in {"needs_review", "suggest"}),
        "ready": sum(
            1
            for claim in claims
            if claim.status not in {"rejected", "duplicate"}
            and (
                claim.status in {"accepted", "edited"}
                or claim.resolver_action in {"auto_correct", "keep", "accepted_suggestion", "manual"}
            )
        ),
        "duplicates": sum(1 for claim in claims if claim.status == "duplicate" or claim.resolver_action == "duplicate"),
        "manual": sum(1 for claim in claims if claim.resolver_action == "manual" or claim.status == "edited"),
        "rejected": sum(1 for claim in claims if claim.status == "rejected"),
    }
    diagnostics = _build_profile_studio_diagnostics(session, profile, claims, documents, settings=settings)
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "documents_total": len(documents),
        "claims_total": len(claims),
        "pending_total": sum(1 for claim in claims if claim.status == "pending"),
        "accepted_total": sum(1 for claim in claims if claim.status == "accepted"),
        "edited_total": sum(1 for claim in claims if claim.status == "edited"),
        "rejected_total": sum(1 for claim in claims if claim.status == "rejected"),
        "sections": [
            {
                "section": section,
                "label": REVIEW_SECTION_LABELS.get(section, section.replace("_", " ").title()),
                "claims": by_section.get(section, []),
            }
            for section in REVIEW_SECTION_ORDER
        ],
        "correction_summary": correction_summary,
        "diagnostics": diagnostics,
        "extracted_profile": extracted_profile,
        "review_preview_profile": review_preview_profile,
        "canonical_profile": canonical_profile,
    }


def resolve_structured_profile_claim(
    session: Session,
    *,
    profile: Profile,
    claim_id: str,
) -> StructuredProfileClaim:
    claim = session.get(StructuredProfileClaim, claim_id)
    if claim is None or claim.profile_id != profile.id:
        raise ValueError("Structured profile claim not found in the selected profile.")
    return claim


def update_structured_profile_claim(
    session: Session,
    *,
    claim: StructuredProfileClaim,
    status: str | None = None,
    section: str | None = None,
    value_json: dict[str, Any] | None = None,
) -> StructuredProfileClaim:
    previous_value_json = dict(claim.value_json or {})
    previous_section = claim.section
    previous_suggested_section = claim.suggested_section

    if section:
        claim.section = section
    section_changed = claim.section != previous_section
    accepted_suggestion = bool(section_changed and previous_suggested_section and claim.section == previous_suggested_section)
    manual_section_override = bool(section_changed and not accepted_suggestion)
    if value_json is not None:
        claim.value_json = value_json
    value_changed = value_json is not None and dict(claim.value_json or {}) != previous_value_json
    if section_changed or value_json is not None:
        _refresh_claim_derived_fields(claim)
    if accepted_suggestion:
        claim.suggested_section = None
        claim.resolver_evidence = list(dict.fromkeys([*(claim.resolver_evidence or []), "accepted_suggestion"]))
        if claim.resolver_action == "suggest":
            claim.resolver_action = "accepted_suggestion"
            claim.resolver_confidence = max(float(claim.resolver_confidence or 0.0), float(claim.confidence or 0.0))
    elif manual_section_override or value_changed:
        claim.suggested_section = None
        claim.resolver_action = "manual"
        claim.resolver_confidence = 1.0
        claim.resolver_evidence = ["manual_edit"]
    if status:
        claim.status = status
    elif value_changed or manual_section_override:
        claim.status = "edited"
    elif accepted_suggestion and claim.status == "pending":
        claim.status = "accepted"
    claim.updated_at = dt.datetime.now(dt.UTC)
    session.flush()
    return claim


def accept_all_structured_profile_claims(
    session: Session,
    *,
    profile: Profile,
    document_id: str | None = None,
) -> int:
    claims = _claims_for_profile(session, profile)
    updated = 0
    for claim in claims:
        if document_id and claim.document_id != document_id:
            continue
        if claim.status in {"rejected", "duplicate"}:
            continue
        if claim.status != "accepted":
            claim.status = "accepted"
            claim.updated_at = dt.datetime.now(dt.UTC)
            updated += 1
    session.flush()
    return updated


def build_canonical_profile_from_structured_claims(session: Session, profile: Profile, user: User | None = None) -> dict[str, Any]:
    canonical = _build_profile_data_from_structured_claims(
        session,
        profile,
        user,
        exclude_statuses={"rejected", "duplicate"},
    )
    for claim in _claims_for_profile(session, profile):
        if claim.status not in {"rejected", "duplicate"} and claim.status == "pending":
            claim.status = "accepted"
            claim.updated_at = dt.datetime.now(dt.UTC)
    return canonical


def save_canonical_profile_from_structured_claims(session: Session, profile: Profile, user: User | None = None) -> dict[str, Any]:
    container = _normalize_profile_container(profile.profile_data)
    container["canonical"] = build_canonical_profile_from_structured_claims(session, profile, user)
    sync_canonical_values_from_overview(session, profile, container["canonical"])
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.flush()
    return profile_overview_payload(profile, user, source="canonical")


def clear_canonical_profile(session: Session, profile: Profile) -> dict[str, Any]:
    container = _normalize_profile_container(profile.profile_data)
    container["canonical"] = None
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.flush()
    return container
