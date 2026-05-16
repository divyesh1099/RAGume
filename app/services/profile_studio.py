import datetime as dt
import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Profile, StructuredProfileClaim, User
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
REVIEWABLE_STATUSES = {"accepted", "edited"}


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


def sync_document_structured_profile_claims(session: Session, profile: Profile, document: Document) -> list[StructuredProfileClaim]:
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
    preserved_status = {
        claim.normalized_value: claim.status
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
        value_text = _claim_value_text(section, field_name, value_json)
        if not value_text:
            return
        normalized_value = _claim_normalized_value(section, field_name, value_json)
        claim = StructuredProfileClaim(
            profile_id=profile.id,
            document_id=document.id,
            section=section,
            field_name=field_name,
            value_json=value_json,
            value_text=value_text,
            normalized_value=normalized_value,
            source_text=_claim_source_text(section, value_json),
            source_page=1 if document.mime_type == "application/pdf" else None,
            source_bbox={},
            parser_name=str(parser_name),
            confidence=_claim_confidence(section, field_name, value_json, base_score=base_score),
            status=preserved_status.get(normalized_value, "pending"),
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
        "value_json": dict(claim.value_json or {}),
        "value_text": claim.value_text,
        "normalized_value": claim.normalized_value,
        "source_text": claim.source_text,
        "source_page": claim.source_page,
        "source_bbox": dict(claim.source_bbox or {}),
        "parser_name": claim.parser_name,
        "confidence": claim.confidence,
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
        value_json = dict(claim.value_json or {})
        if claim.section == "identity":
            if claim.field_name in SCALAR_IDENTITY_FIELDS:
                merged_identity = _merge_identity(merged_identity, {claim.field_name: value_json.get("value")})
            elif claim.field_name == "email":
                merged_identity["emails"] = _unique_strings([*merged_identity.get("emails", []), _string_value(value_json.get("value"))])
            elif claim.field_name == "phone":
                merged_identity["phones"] = _unique_strings([*merged_identity.get("phones", []), _string_value(value_json.get("value"))])
        elif claim.section == "skills":
            canonical["skills"] = _unique_strings([*canonical["skills"], _string_value(value_json.get("name"))])
        elif claim.section == "public_profiles":
            canonical["public_profiles"] = _unique_links([*canonical["public_profiles"], value_json])
        elif claim.section == "work_experience":
            work_items.append(value_json)
        elif claim.section == "projects":
            project_items.append(value_json)
        elif claim.section == "education":
            education_items.append(value_json)
        elif claim.section == "certifications":
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
        if claim.section not in entry["signals"]:
            entry["signals"].append(claim.section)
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


def build_structured_profile_review(session: Session, profile: Profile, user: User) -> dict[str, Any]:
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
                "label": section.replace("_", " ").title(),
                "claims": by_section.get(section, []),
            }
            for section in REVIEW_SECTION_ORDER
        ],
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
    if section:
        claim.section = section
    if value_json is not None:
        claim.value_json = value_json
        claim.value_text = _claim_value_text(claim.section, claim.field_name, value_json)
        claim.normalized_value = _claim_normalized_value(claim.section, claim.field_name, value_json)
        claim.source_text = _claim_source_text(claim.section, value_json)
    if status:
        claim.status = status
    elif value_json is not None:
        claim.status = "edited"
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
