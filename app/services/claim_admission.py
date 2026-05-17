from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalValue, Profile, StructuredProfileClaim
from app.services.correction_resolver import DEGREE_ALIASES, SKILL_ALIASES


LOWER_WORD_PATTERN = re.compile(r"[^a-z0-9+#./ -]+")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
SUMMARY_BULLET_PATTERN = re.compile(
    r"^(?:built|developed|designed|implemented|led|managed|created|refactored|migrated|optimized)\b",
    flags=re.IGNORECASE,
)
DATE_HEAVY_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
SUMMARY_MISCLASSIFIED_PATTERN = re.compile(
    r"^(?:worked on|created|implemented|built|developed|designed|refactored|migrated|led)\b",
    flags=re.IGNORECASE,
)
KNOWN_SKILL_WHITELIST = {
    "C#",
    "C++",
    "CSS",
    "SQL",
    "Git",
    "AWS",
    "GCP",
    "MVC",
    "NLP",
    "OCR",
    "RAG",
    "LLM",
    "BERT",
    "T5",
    "NSQ",
    "Helm",
    "Flask",
    "Kafka",
    "Redis",
    "MLflow",
    "FastAPI",
    "PyTorch",
    "TensorFlow",
    "Docker",
    "LangChain",
    "LlamaIndex",
    "React",
    "Angular",
    "Django",
    "ASP.NET",
    "ASP.NET Core",
    "NumPy",
    "Pandas",
    "RoBERTa",
    "Terraform",
    "MongoDB",
    "RabbitMQ",
    "XGBoost",
    "Sass",
    "WebGL",
    "Bootstrap",
    "HTML",
    "jQuery",
    "Shopify",
    "Azure",
    "gRPC",
    "Weights & Biases",
    "Adobe XD",
    "Figma",
}
SKILL_SHORT_ALLOWLIST = {
    "c#",
    "c++",
    "css",
    "sql",
    "git",
    "aws",
    "gcp",
    "mvc",
    "nlp",
    "ocr",
    "rag",
    "llm",
    "bert",
    "t5",
    "nsq",
}
SKILL_NOISE_BLACKLIST = {
    "/cd",
    "ify",
    "peline",
    "lang",
    "langg",
    "tor",
    "zure",
    "moti",
    "fire",
    "ang",
    "men",
    "ima",
    "tern",
}
SKILL_HEADING_BLACKLIST = {
    "languages",
    "language",
    "tools",
    "technical skills",
    "soft skills",
    "cloud",
    "data",
    "skills",
    "programming",
    "technical",
    "frameworks",
    "technologies",
    "backend",
    "frontend",
    "front end",
}
PROJECT_NOISE_BLACKLIST = {
    "app that auto",
    "tech-fest budget",
    "volunteers. freelance",
    "python nsq",
    "student rep",
    "leadership mentor",
}
PERSONAL_LINK_TYPES = {
    "linkedin",
    "github_profile",
    "leetcode",
    "hackerrank",
    "personal_portfolio",
}
PROJECT_DEMO_SUFFIXES = ("web.app", "vercel.app", "netlify.app", "pages.dev", "onrender.com", "streamlit.app")
COMMUNITY_HOST_HINTS = {"anitab", "chaoss", "community", "meetup", "womenwhocode", "fossasia"}
CLIENT_HOST_HINTS = {"shopify", "wix", "studio", "digital", "agency"}
ORGANIZATION_HOST_HINTS = {"university", "college", "academy", "foundation", "society", "council", "org", "association"}
SKILL_TAXONOMY = {
    "programming_languages": {"python", "javascript", "typescript", "c#", "c++", "sql", "html", "css", "sass"},
    "frameworks": {"angular", "react", "django", "flask", "fastapi", "asp.net", "asp.net core", "bootstrap", "jquery", "webgl"},
    "ml_ai": {
        "bert",
        "roberta",
        "t5",
        "ocr",
        "rag",
        "llm",
        "nlp",
        "pytorch",
        "tensorflow",
        "numpy",
        "pandas",
        "xgboost",
        "langchain",
        "llamaindex",
        "langgraph",
        "autogen",
        "crewai",
        "mlflow",
        "weights biases",
    },
    "databases": {"mongodb", "redis", "postgresql", "rabbitmq"},
    "cloud_devops": {"terraform", "docker", "helm", "github actions", "aws", "azure", "gcp", "nsq", "kafka", "grpc"},
}


@dataclass(slots=True)
class AdmissionDecision:
    status: str
    reason: str
    score: float


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", LOWER_WORD_PATTERN.sub(" ", value.lower())).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _decision(status: str, reason: str, score: float) -> AdmissionDecision:
    return AdmissionDecision(status=status, reason=reason, score=_clamp_score(score))


def _preview_section(claim: StructuredProfileClaim) -> str:
    return str(claim.suggested_section or claim.section or "")


def _canonical_entries(
    session: Session,
    profile: Profile,
    *,
    value_type: str,
) -> list[CanonicalValue]:
    return list(
        session.scalars(
            select(CanonicalValue).where(
                CanonicalValue.profile_id == profile.id,
                CanonicalValue.value_type == value_type,
            )
        ).all()
    )


def _matches_canonical_value(
    session: Session,
    profile: Profile,
    *,
    value_type: str,
    value: str,
) -> bool:
    normalized = _normalize_lookup(value)
    if not normalized:
        return False
    for entry in _canonical_entries(session, profile, value_type=value_type):
        values = [entry.canonical_value, *(entry.aliases_json or [])]
        if any(_normalize_lookup(candidate) == normalized for candidate in values if candidate):
            return True
    return False


def _claim_document_count(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    matcher,
    peer_claims: Iterable[StructuredProfileClaim] | None = None,
) -> int:
    document_ids = {claim.document_id}
    existing_claims = session.scalars(
        select(StructuredProfileClaim).where(
            StructuredProfileClaim.profile_id == profile.id,
            StructuredProfileClaim.id != claim.id,
        )
    ).all()
    for other in existing_claims:
        if matcher(other):
            document_ids.add(other.document_id)
    if peer_claims:
        for other in peer_claims:
            if other is claim:
                continue
            if matcher(other):
                document_ids.add(other.document_id)
    return len(document_ids)


def _link_type(url: str, label: str = "") -> str:
    cleaned = _clean_text(url)
    if not cleaned:
        return "invalid"
    if cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower().removeprefix("www.")
    segments = [segment for segment in parsed.path.split("/") if segment]
    lowered_label = _normalize_lookup(label)
    host_core = host.split(".", 1)[0]
    if host == "linkedin.com":
        return "linkedin"
    if host == "github.com":
        return "project_repo" if len(segments) >= 2 else "github_profile"
    if "leetcode.com" in host:
        return "leetcode"
    if "hackerrank.com" in host:
        return "hackerrank"
    if host.endswith(PROJECT_DEMO_SUFFIXES):
        return "project_demo"
    if any(token in host for token in COMMUNITY_HOST_HINTS):
        return "community_site"
    if any(token in host for token in CLIENT_HOST_HINTS):
        return "client_site"
    if any(token in host for token in ORGANIZATION_HOST_HINTS):
        return "organization_site"
    if lowered_label in {"portfolio", "personal website", "website"}:
        return "personal_portfolio"
    if host.endswith(".org"):
        return "community_site"
    if segments:
        return "client_site"
    if any(token in host_core for token in ("divyesh", "vishwakarma")):
        return "personal_portfolio"
    return "website"


def _is_skill_noise(raw_value: str) -> bool:
    normalized = _normalize_lookup(raw_value)
    if not normalized:
        return True
    if _has_skill_alias(raw_value) or _is_skill_taxonomy_match(raw_value):
        return False
    if raw_value in KNOWN_SKILL_WHITELIST or normalized in SKILL_SHORT_ALLOWLIST:
        return False
    if normalized in SKILL_HEADING_BLACKLIST or normalized in SKILL_NOISE_BLACKLIST:
        return True
    compact = normalized.replace(" ", "")
    if compact in SKILL_SHORT_ALLOWLIST:
        return False
    if len(compact) <= 2 and compact not in SKILL_SHORT_ALLOWLIST:
        return True
    if len(compact) <= 4 and compact.isalpha() and compact not in SKILL_SHORT_ALLOWLIST:
        return True
    return False


def _is_skill_taxonomy_match(raw_value: str) -> bool:
    normalized = _normalize_lookup(raw_value)
    if not normalized:
        return False
    return any(normalized in values for values in SKILL_TAXONOMY.values())


def _has_skill_alias(raw_value: str) -> bool:
    normalized = _normalize_lookup(raw_value)
    if raw_value in KNOWN_SKILL_WHITELIST:
        return True
    for canonical, aliases in SKILL_ALIASES.items():
        if _normalize_lookup(canonical) == normalized:
            return True
        if any(_normalize_lookup(alias) == normalized for alias in aliases):
            return True
    return False


def _skill_admission(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    peer_claims: Iterable[StructuredProfileClaim] | None = None,
) -> AdmissionDecision:
    raw_name = _clean_text((claim.value_json or {}).get("name") or (claim.raw_value_json or {}).get("name"))
    normalized = _normalize_lookup(raw_name)
    if _is_skill_noise(raw_name):
        return _decision("reject_noise", "skill_noise_fragment", 0.02)
    if _has_skill_alias(raw_name):
        return _decision("admit", "known_skill_dictionary", 0.99)
    if _is_skill_taxonomy_match(raw_name):
        return _decision("admit", "skill_taxonomy_match", 0.95)
    if _matches_canonical_value(session, profile, value_type="skill", value=raw_name):
        return _decision("admit", "accepted_before", 0.96)

    docs_count = _claim_document_count(
        session,
        profile,
        claim,
        matcher=lambda other: _preview_section(other) == "skills"
        and _normalize_lookup((other.value_json or {}).get("name") or (other.raw_value_json or {}).get("name") or "")
        == normalized,
        peer_claims=peer_claims,
    )
    if docs_count >= 2 and normalized not in SKILL_HEADING_BLACKLIST:
        return _decision("admit", "seen_in_multiple_documents", 0.88)

    in_skills_section = _preview_section(claim) == "skills"
    resolver_confidence = float(claim.resolver_confidence or claim.confidence or 0.0)
    if in_skills_section and resolver_confidence >= 0.72:
        return _decision("admit", "skills_section_quality", 0.84)
    if in_skills_section and resolver_confidence >= 0.55:
        return _decision("needs_review", "low_confidence_skill", 0.64)
    return _decision("reject_noise", "unverified_skill_fragment", 0.1)


def _project_signal_count(claim: StructuredProfileClaim, payload: dict[str, Any]) -> int:
    score = 0
    name = _clean_text(payload.get("name"))
    summary = _clean_text(payload.get("summary"))
    technologies = [_clean_text(item) for item in payload.get("technologies", []) if _clean_text(item)]
    links = [_clean_text(item) for item in payload.get("links", []) if _clean_text(item)]
    date_or_org = any(
        _clean_text(payload.get(field))
        for field in ("start_date", "end_date", "organization", "issuer", "client", "location")
    )
    if name and len(name) >= 3 and not name.endswith("."):
        score += 1
    if summary and len(summary.split()) >= 5:
        score += 1
    if technologies:
        score += 1
    if links:
        score += 1
    if date_or_org:
        score += 1
    if _preview_section(claim) == "projects":
        score += 1
    return score


def _looks_like_project_fragment(payload: dict[str, Any]) -> bool:
    name = _clean_text(payload.get("name"))
    summary = _clean_text(payload.get("summary"))
    record_type = _clean_text(payload.get("record_type"))
    combined = _normalize_lookup(" ".join(part for part in (name, summary) if part))
    if not combined:
        return True
    if record_type and record_type != "project":
        return True
    if combined in PROJECT_NOISE_BLACKLIST:
        return True
    if name and name[:1].islower() and not any(char.isupper() for char in name[1:]):
        return True
    if len(name) and len(name.split()) > 5 and not summary:
        return True
    if summary and len(summary.split()) < 4 and not payload.get("technologies") and not payload.get("links"):
        return True
    return False


def _project_admission(claim: StructuredProfileClaim) -> AdmissionDecision:
    payload = dict(claim.value_json or claim.raw_value_json or {})
    if _looks_like_project_fragment(payload):
        return _decision("reject_noise", "project_fragment", 0.04)
    signal_count = _project_signal_count(claim, payload)
    if signal_count >= 3:
        return _decision("admit", "project_has_structure", 0.92)
    if signal_count == 2:
        return _decision("admit", "project_has_enough_signals", 0.82)
    if signal_count == 1:
        return _decision("reject_noise", "weak_project_claim", 0.18)
    return _decision("reject_noise", "project_fragment", 0.08)


def _experience_admission(claim: StructuredProfileClaim) -> AdmissionDecision:
    payload = dict(claim.value_json or claim.raw_value_json or {})
    title = _clean_text(payload.get("title"))
    organization = _clean_text(payload.get("organization"))
    start_date = _clean_text(payload.get("start_date"))
    end_date = _clean_text(payload.get("end_date"))
    summary = _clean_text(payload.get("summary"))
    if not title and not organization and not summary:
        return _decision("reject_noise", "empty_experience_claim", 0.02)
    if title and organization and (start_date or end_date):
        return _decision("admit", "dated_role_with_organization", 0.95)
    if title and organization:
        return _decision("admit", "role_with_organization", 0.82)
    if title and not organization:
        return _decision("needs_review", "missing_organization", 0.48)
    if organization and summary:
        return _decision("needs_review", "organization_without_title", 0.42)
    return _decision("quarantine", "weak_experience_claim", 0.18)


def _summary_admission(claim: StructuredProfileClaim) -> AdmissionDecision:
    value = _clean_text((claim.value_json or {}).get("value") or (claim.raw_value_json or {}).get("value"))
    if not value:
        return _decision("reject_noise", "empty_summary", 0.0)
    char_count = len(value)
    word_count = len(value.split())
    if SUMMARY_MISCLASSIFIED_PATTERN.search(value):
        return _decision("reject_noise", "summary_misclassified_experience", 0.06)
    if char_count < 80:
        return _decision("reject_noise", "summary_too_short", 0.08)
    if char_count > 900:
        return _decision("needs_review", "summary_too_long", 0.36)
    if SUMMARY_BULLET_PATTERN.search(value) and word_count < 28:
        return _decision("needs_review", "looks_like_experience_bullet", 0.42)
    if DATE_HEAVY_PATTERN.search(value[:120]):
        return _decision("reject_noise", "summary_date_heavy", 0.08)
    if "|" in value and word_count < 32:
        return _decision("reject_noise", "summary_looks_like_header", 0.06)
    return _decision("admit", "summary_like_text", 0.92)


def _identity_admission(claim: StructuredProfileClaim) -> AdmissionDecision:
    field_name = str(claim.field_name or "")
    value = _clean_text((claim.value_json or {}).get("value") or (claim.raw_value_json or {}).get("value"))
    if field_name == "summary":
        return _summary_admission(claim)
    if field_name == "email":
        return _decision("admit", "valid_email", 0.98 if EMAIL_PATTERN.search(value) else 0.28)
    if field_name == "phone":
        digits = re.sub(r"\D+", "", value)
        if len(digits) >= 10:
            return _decision("admit", "phone_like_value", 0.9)
        return _decision("reject_noise", "invalid_phone", 0.04)
    if field_name == "full_name":
        if len(value.split()) >= 2:
            return _decision("admit", "full_name_like_value", 0.94)
        return _decision("needs_review", "weak_name_claim", 0.42)
    if field_name == "headline":
        if len(value.split()) >= 2:
            return _decision("admit", "headline_like_value", 0.84)
        return _decision("needs_review", "weak_headline_claim", 0.48)
    if field_name == "location":
        return _decision("admit", "location_like_value", 0.78 if value else 0.0)
    return _decision("needs_review", "generic_identity_claim", 0.5)


def _link_admission(claim: StructuredProfileClaim) -> AdmissionDecision:
    payload = dict(claim.value_json or claim.raw_value_json or {})
    url = _clean_text(payload.get("url"))
    label = _clean_text(payload.get("label"))
    if not url:
        return _decision("reject_noise", "missing_url", 0.0)
    link_type = _link_type(url, label=label)
    if link_type in PERSONAL_LINK_TYPES:
        return _decision("admit", f"{link_type}_link", 0.94)
    if link_type in {"project_repo", "project_demo", "client_site", "organization_site", "community_site"}:
        return _decision("quarantine", f"{link_type}_not_personal_profile", 0.24)
    return _decision("needs_review", "unknown_link_type", 0.5)


def _education_admission(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
) -> AdmissionDecision:
    payload = dict(claim.value_json or claim.raw_value_json or {})
    degree = _clean_text(payload.get("degree"))
    institution = _clean_text(payload.get("institution"))
    if not degree and not institution:
        return _decision("reject_noise", "empty_education_claim", 0.0)
    normalized_degree = _normalize_lookup(degree)
    if normalized_degree and any(
        _normalize_lookup(canonical) == normalized_degree
        or normalized_degree in {_normalize_lookup(alias) for alias in aliases}
        for canonical, aliases in DEGREE_ALIASES.items()
    ):
        return _decision("admit", "known_degree_alias", 0.94)
    if _matches_canonical_value(session, profile, value_type="degree", value=degree):
        return _decision("admit", "accepted_degree_before", 0.92)
    if degree and institution:
        return _decision("admit", "degree_with_institution", 0.86)
    return _decision("needs_review", "partial_education_claim", 0.56)


def evaluate_claim_admission(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    peer_claims: Iterable[StructuredProfileClaim] | None = None,
) -> AdmissionDecision:
    if claim.status == "rejected":
        return _decision("reject_noise", "manually_rejected", 0.0)
    if claim.status == "duplicate" or claim.resolver_action == "duplicate":
        return _decision("reject_noise", "duplicate_value", 0.0)
    if (
        claim.status == "edited"
        or claim.resolver_action == "manual"
        or (claim.status == "accepted" and claim.admission_status == "admit" and claim.admission_reason == "user_accepted")
    ):
        return _decision("admit", "manual_override", 1.0)

    preview_section = _preview_section(claim)
    if preview_section == "skills":
        return _skill_admission(session, profile, claim, peer_claims=peer_claims)
    if preview_section == "projects":
        return _project_admission(claim)
    if preview_section == "work_experience":
        return _experience_admission(claim)
    if preview_section == "public_profiles":
        return _link_admission(claim)
    if preview_section == "education":
        return _education_admission(session, profile, claim)
    if preview_section == "identity":
        return _identity_admission(claim)
    if preview_section == "certifications":
        payload = dict(claim.value_json or claim.raw_value_json or {})
        if _clean_text(payload.get("name")) and _clean_text(payload.get("issuer")):
            return _decision("admit", "certification_with_issuer", 0.82)
        return _decision("needs_review", "partial_certification_claim", 0.5)
    return _decision("needs_review", "untyped_claim", 0.45)


def apply_claim_admission(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    peer_claims: Iterable[StructuredProfileClaim] | None = None,
) -> AdmissionDecision:
    decision = evaluate_claim_admission(session, profile, claim, peer_claims=peer_claims)
    claim.admission_status = decision.status
    claim.admission_reason = decision.reason
    claim.admission_score = decision.score
    return decision
