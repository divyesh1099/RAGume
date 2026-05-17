from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ClaimGroup, Document, Profile, ProfileAnomaly, StructuredProfileClaim, User
from app.services.claim_utils import extract_skills
from app.services.profile_compiler import compile_profile_views
from app.services.correction_resolver import DEGREE_ALIASES, ROLE_ALIASES, SKILL_ALIASES, sync_canonical_values_from_overview
from app.services.embeddings import correction_embedding_available, cosine_similarity, ensure_correction_embeddings
from app.services.profile_memory import (
    _default_identity,
    _default_overview_data,
    _merge_item_dict,
    _normalize_identity,
    _normalize_overview_data,
    _normalize_profile_container,
    _unique_links,
    _unique_strings,
    infer_profile_focus,
    source_priority_for_role,
)

try:
    import phonenumbers
except Exception:  # pragma: no cover - optional runtime dependency
    phonenumbers = None

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional runtime dependency
    fuzz = None


LOWER_WORD_PATTERN = re.compile(r"[^a-z0-9+#./ -]+")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
GPA_PATTERN = re.compile(r"\b(?:gpa|cgpa)\s*[:=]?\s*(\d(?:\.\d{1,2})?)\b|\b(\d(?:\.\d{1,2})?)\s*gpa\b", flags=re.IGNORECASE)
PRESENT_PATTERN = re.compile(r"\b(?:present|current|now)\b", flags=re.IGNORECASE)
LINK_TYPE_LABELS = {
    "linkedin": "LinkedIn",
    "github_profile": "GitHub",
    "leetcode": "LeetCode",
    "hackerrank": "HackerRank",
    "personal_portfolio": "Portfolio",
    "project_demo": "Project Demo",
    "project_repo": "Project Repository",
    "client_site": "Client Site",
    "organization_site": "Organization Site",
    "community_site": "Community Site",
    "website": "Website",
}
SKILL_CATEGORY_MAP = {
    "Python": "Language",
    "JavaScript": "Language",
    "TypeScript": "Language",
    "HTML": "Frontend",
    "CSS": "Frontend",
    "Sass": "Frontend",
    "WebGL": "Frontend",
    "SQL": "Data",
    "PostgreSQL": "Data",
    "MongoDB": "Data",
    "Redis": "Data",
    "RabbitMQ": "Infrastructure",
    "Docker": "Infrastructure",
    "Kubernetes": "Infrastructure",
    "CI/CD": "Infrastructure",
    "Terraform": "Infrastructure",
    "Helm": "Infrastructure",
    "GitHub Actions": "Infrastructure",
    "FastAPI": "Backend",
    "React": "Frontend",
    "Angular": "Frontend",
    "Bootstrap": "Frontend",
    "jQuery": "Frontend",
    "Flask": "Backend",
    "Django": "Backend",
    "ASP.NET": "Backend",
    "ASP.NET Core": "Backend",
    "gRPC": "Backend",
    "Next.js": "Frontend",
    "RAG": "AI",
    "LLM": "AI",
    "OCR": "AI",
    "Document AI": "AI",
    "LayoutLMv3": "AI",
    "PyTorch": "AI",
    "TensorFlow": "AI",
    "NumPy": "AI",
    "Pandas": "AI",
    "RoBERTa": "AI",
    "XGBoost": "AI",
    "BERT": "AI",
    "T5": "AI",
    "NLP": "AI",
    "MLflow": "AI",
    "Docling": "Document AI",
    "PyMuPDF": "Document AI",
    "NSQ": "Infrastructure",
    "AWS": "Cloud",
    "Azure": "Cloud",
    "GCP": "Cloud",
    "Kafka": "Infrastructure",
}
SKILL_FRAGMENT_BLACKLIST = {
    "/cd",
    "peline",
    "lang",
    "langg",
    "ima",
    "men",
    "zure",
    "ify",
    "tor",
}
SKILL_SHORT_ALLOWLIST = {"ai", "ml", "nlp", "ocr", "sql", "aws", "gcp", "ci/cd", "ci", "nsq"}
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
    "backend",
    "front end",
    "frontend",
    "devops",
    "frameworks",
    "technologies",
}
KNOWN_SKILL_WHITELIST = {
    "C#",
    "C++",
    "CSS",
    "SQL",
    "AWS",
    "GCP",
    "NLP",
    "OCR",
    "RAG",
    "LLM",
    "BERT",
    "T5",
    "MVC",
    "Git",
    "Helm",
    "Flask",
    "Kafka",
    "Redis",
    "NSQ",
    "MLflow",
    "FastAPI",
    "PyTorch",
    "TensorFlow",
    "Docker",
    "LangChain",
    "LlamaIndex",
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
    "AWS",
    "Azure",
    "GCP",
    "gRPC",
}
EXPERIENCE_PROJECT_HINTS = {
    "project",
    "pipeline",
    "tool",
    "platform",
    "application",
    "agent",
    "open source",
    "github",
}
ROLE_WORDS = {
    "engineer",
    "developer",
    "analyst",
    "scientist",
    "architect",
    "manager",
    "intern",
    "consultant",
}
FUZZY_DUPLICATE_THRESHOLD = 0.92
FUZZY_DUPLICATE_REVIEW_THRESHOLD = 0.80
SEMANTIC_DUPLICATE_THRESHOLD = 0.95
SEMANTIC_DUPLICATE_REVIEW_THRESHOLD = 0.88
PROJECT_DEMO_SUFFIXES = ("web.app", "vercel.app", "netlify.app", "pages.dev", "onrender.com", "streamlit.app")
COMMUNITY_HOST_HINTS = {"anitab", "chaoss", "community", "meetup", "womenwhocode", "fossasia"}
ORGANIZATION_HOST_HINTS = {"university", "college", "academy", "foundation", "society", "council", "org", "association"}
CLIENT_HOST_HINTS = {"shopify", "wix", "studio", "digital", "agency"}
CRITICAL_REVIEW_REASONS = {
    "current_headline_conflict",
    "same_company_different_roles",
    "same_dates_different_company",
    "missing_organization",
    "degree_wording_conflict",
    "portfolio_conflict",
    "conflicting_contact_value",
    "wrong_company_bullet",
}
OPTIONAL_REVIEW_REASONS = {
    "project_inside_experience",
    "potential_duplicate",
    "low_confidence_skill",
    "section_misclassification",
}


@dataclass
class FusionClaim:
    claim: StructuredProfileClaim
    document: Document | None
    section: str
    quality_score: float
    normalized_key: str
    display_value: str


@dataclass
class ClaimCluster:
    group_type: str
    cluster_key: str
    claims: list[FusionClaim]
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", LOWER_WORD_PATTERN.sub(" ", value.lower())).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _document_role(document: Document | None) -> str:
    if document is None:
        return "general_resume"
    return str((document.parse_metadata or {}).get("document_role") or "general_resume")


def _document_focus(document: Document | None) -> str:
    if document is None:
        return "master"
    return str((document.parse_metadata or {}).get("profile_focus") or "master")


def _document_source_quality(document: Document | None) -> float:
    if document is None:
        return 0.72
    raw = (document.parse_metadata or {}).get("source_quality")
    try:
        return max(0.35, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.72


def _field_priority_bucket(claim: StructuredProfileClaim) -> str:
    preview_section = claim.suggested_section or claim.section
    if preview_section == "identity":
        if claim.field_name == "headline":
            return "current_headline"
        if claim.field_name == "summary":
            return "summary"
        if claim.field_name in {"email", "phone"}:
            return "public_profile"
        return "current_headline"
    if preview_section == "skills":
        return "skills"
    if preview_section == "projects":
        return "projects"
    if preview_section == "education":
        return "education"
    if preview_section == "public_profiles":
        return "public_profile"
    if preview_section == "work_experience":
        value = dict(claim.value_json or {})
        end_date = _clean_text(value.get("end_date"))
        if not end_date or PRESENT_PATTERN.search(end_date):
            return "current_experience"
        return "historical_experience"
    return "historical_experience"


def _source_priority_score(claim: StructuredProfileClaim, document: Document | None) -> float:
    return source_priority_for_role(_field_priority_bucket(claim), _document_role(document))


def _string_similarity(left: str, right: str) -> float:
    left_clean = _normalize_lookup(left)
    right_clean = _normalize_lookup(right)
    if not left_clean or not right_clean:
        return 0.0
    if left_clean == right_clean:
        return 1.0
    if fuzz is not None:
        return float(fuzz.WRatio(left_clean, right_clean)) / 100.0
    return SequenceMatcher(None, left_clean, right_clean).ratio()


def _document_score(document: Document | None) -> float:
    if document is None:
        return 0.65
    validation = dict((document.parse_metadata or {}).get("profile_validation") or {})
    raw_score = float(validation.get("score") or 68)
    return max(0.35, min(1.0, raw_score / 100.0))


def _recency_score(document: Document | None) -> float:
    if document is None or document.created_at is None:
        return 0.65
    created_at = document.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.UTC)
    age_days = max(0.0, (dt.datetime.now(dt.UTC) - created_at).total_seconds() / 86400)
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.92
    if age_days <= 365:
        return 0.84
    return 0.72


def _source_section_score(section: str, claim: StructuredProfileClaim) -> float:
    preview_section = claim.suggested_section or claim.section
    return 1.0 if preview_section == section else 0.72


def _claim_quality(claim: StructuredProfileClaim, document: Document | None) -> float:
    parser_confidence = max(0.0, min(1.0, float(claim.confidence or 0.0)))
    resolver_confidence = max(parser_confidence, min(1.0, float(claim.resolver_confidence or 0.0)))
    accepted_before = 1.0 if claim.status in {"accepted", "edited"} else 0.0
    source_priority = _source_priority_score(claim, document)
    score = (
        0.24 * parser_confidence
        + 0.22 * resolver_confidence
        + 0.12 * _document_score(document)
        + 0.10 * _document_source_quality(document)
        + 0.10 * _source_section_score(claim.suggested_section or claim.section, claim)
        + 0.10 * accepted_before
        + 0.05 * _recency_score(document)
        + 0.07 * source_priority
    )
    return round(max(0.0, min(score, 1.0)), 4)


def _canonicalize_url(value: str) -> str:
    cleaned = _clean_text(value).rstrip(".,);")
    if cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"
    if cleaned and "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if path:
        cleaned = f"https://{host}{path}"
    else:
        cleaned = f"https://{host}"
    return cleaned


def _canonical_url_key(value: str) -> str:
    parsed = urlparse(_canonicalize_url(value))
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _url_segments(value: str) -> list[str]:
    parsed = urlparse(_canonicalize_url(value))
    return [segment for segment in parsed.path.split("/") if segment]


def _classify_link_type(url: str, *, label: str | None = None, user: User | None = None) -> str:
    canonical = _canonicalize_url(url)
    parsed = urlparse(canonical)
    host = parsed.netloc.lower().removeprefix("www.")
    segments = _url_segments(canonical)
    lowered_label = _normalize_lookup(label or "")
    user_tokens = {
        token
        for token in re.split(r"[^a-z]+", (user.full_name.lower() if user and user.full_name else ""))
        if len(token) >= 3
    }
    host_core = host.split(".", 1)[0]
    if host == "linkedin.com":
        return "linkedin"
    if host == "github.com":
        return "project_repo" if len(segments) >= 2 else "github_profile"
    if "leetcode.com" in host:
        return "leetcode"
    if "hackerrank.com" in host:
        return "hackerrank"
    if host == "huggingface.co":
        return "project_repo" if segments and (segments[0] in {"spaces", "datasets", "models"} or len(segments) >= 2) else "organization_site"
    if host.endswith(PROJECT_DEMO_SUFFIXES):
        return "project_demo"
    if any(token in host for token in COMMUNITY_HOST_HINTS):
        return "community_site"
    if any(token in host for token in ORGANIZATION_HOST_HINTS):
        return "organization_site"
    if any(token in host for token in CLIENT_HOST_HINTS):
        return "client_site"
    if lowered_label in {"portfolio", "personal website", "website"}:
        if user_tokens and any(token in host_core for token in user_tokens):
            return "personal_portfolio"
        if host.endswith(".org"):
            return "organization_site"
        return "personal_portfolio"
    if user_tokens and any(token in host_core for token in user_tokens):
        return "personal_portfolio"
    if segments:
        return "client_site"
    if host.endswith(".org"):
        return "community_site"
    return "website"


def _normalize_phone(value: str) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    if phonenumbers is not None:
        try:
            parsed = phonenumbers.parse(raw, "IN")
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        except Exception:
            pass
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 10:
        digits = f"91{digits}"
    if len(digits) >= 12 and digits.startswith("91"):
        return f"+91 {digits[2:7]} {digits[7:]}"
    return raw


def _normalize_email(value: str) -> str:
    return _clean_text(value).lower()


def _safe_host(url: str) -> str:
    return urlparse(_canonicalize_url(url)).netloc.lower().removeprefix("www.")


def _safe_year(value: str | None) -> int | None:
    if not value:
        return None
    match = YEAR_PATTERN.search(value)
    if not match:
        return None
    return int(match.group(0))


def _date_overlap(left_start: str | None, left_end: str | None, right_start: str | None, right_end: str | None) -> bool:
    left_start_year = _safe_year(left_start) or 0
    right_start_year = _safe_year(right_start) or 0
    left_end_year = 9999 if left_end and PRESENT_PATTERN.search(left_end) else (_safe_year(left_end) or 9999)
    right_end_year = 9999 if right_end and PRESENT_PATTERN.search(right_end) else (_safe_year(right_end) or 9999)
    if not left_start_year or not right_start_year:
        return True
    return max(left_start_year, right_start_year) <= min(left_end_year, right_end_year)


def _pick_best_text(values: list[tuple[str, float]]) -> str | None:
    cleaned = [(text, score) for text, score in values if _clean_text(text)]
    if not cleaned:
        return None
    cleaned.sort(key=lambda item: (item[1], len(_clean_text(item[0]))), reverse=True)
    return _clean_text(cleaned[0][0])


def _pick_best_date(values: list[tuple[str, float]], *, prefer_latest: bool = False) -> str | None:
    cleaned = [(text, score, _safe_year(text)) for text, score in values if _clean_text(text)]
    if not cleaned:
        return None
    if prefer_latest:
        cleaned.sort(key=lambda item: (1 if item[2] is not None else 0, item[2] or -1, item[1], len(item[0])), reverse=True)
    else:
        cleaned.sort(key=lambda item: (1 if item[2] is not None else 0, -(item[2] or 9999), item[1], len(item[0])), reverse=True)
    return _clean_text(cleaned[0][0])


def _best_claim(claims: list[FusionClaim]) -> FusionClaim:
    return max(claims, key=lambda item: item.quality_score)


def _skill_alias_reverse_map() -> dict[str, str]:
    reverse: dict[str, str] = {}
    for canonical, aliases in SKILL_ALIASES.items():
        reverse[_normalize_lookup(canonical)] = canonical
        for alias in aliases:
            reverse[_normalize_lookup(alias)] = canonical
    return reverse


SKILL_ALIAS_LOOKUP = _skill_alias_reverse_map()
KNOWN_SKILLS = {canonical for canonical in SKILL_ALIASES} | set(SKILL_CATEGORY_MAP) | set(extract_skills(" ".join(SKILL_ALIASES)))


def _canonical_skill_name(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if _normalize_lookup(cleaned) in {_normalize_lookup(item) for item in SKILL_HEADING_BLACKLIST}:
        return ""
    if cleaned in KNOWN_SKILL_WHITELIST:
        return cleaned
    alias_match = SKILL_ALIAS_LOOKUP.get(_normalize_lookup(cleaned))
    if alias_match:
        return alias_match
    extracted = extract_skills(cleaned)
    if extracted:
        return extracted[0]
    return cleaned


def _looks_like_skill_fragment(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return True
    lowered = _normalize_lookup(cleaned)
    if cleaned in KNOWN_SKILL_WHITELIST or lowered in {_normalize_lookup(item) for item in KNOWN_SKILL_WHITELIST}:
        return False
    if lowered in {_normalize_lookup(item) for item in SKILL_HEADING_BLACKLIST}:
        return True
    if lowered in SKILL_FRAGMENT_BLACKLIST:
        return True
    if lowered in {_normalize_lookup(skill) for skill in KNOWN_SKILLS}:
        return False
    if lowered in SKILL_ALIAS_LOOKUP:
        return False
    if len(lowered) <= 2 and lowered not in SKILL_SHORT_ALLOWLIST:
        return True
    if lowered.startswith("/") and lowered not in {"c/c++", "ci/cd"}:
        return True
    if len(lowered) <= 4 and lowered.isalpha() and lowered.lower() == lowered and lowered not in SKILL_SHORT_ALLOWLIST:
        return True
    if len(lowered) <= 6 and sum(character in "aeiou" for character in lowered) <= 1 and lowered not in SKILL_SHORT_ALLOWLIST:
        return True
    return False


def _skill_category(skill: str) -> str | None:
    return SKILL_CATEGORY_MAP.get(skill)


def _skill_score(claims: list[FusionClaim], canonical_skill: str) -> tuple[float, list[str]]:
    best = _best_claim(claims)
    evidence: list[str] = []
    score = 0.0
    if canonical_skill in KNOWN_SKILL_WHITELIST or _normalize_lookup(canonical_skill) in {_normalize_lookup(item) for item in KNOWN_SKILL_WHITELIST}:
        score += 0.16
        evidence.append("known_skill_whitelist")
    score += max(best.claim.confidence or 0.0, best.claim.resolver_confidence or 0.0) * 0.55
    if any((claim.section == "skills" or claim.claim.section == "skills") for claim in claims):
        score += 0.14
        evidence.append("skills_section")
    if canonical_skill in KNOWN_SKILLS or _normalize_lookup(canonical_skill) in SKILL_ALIAS_LOOKUP:
        score += 0.20
        evidence.append("known_skill_dictionary_match")
    document_ids = {claim.claim.document_id for claim in claims}
    if len(document_ids) > 1:
        score += min(0.12, 0.06 * len(document_ids))
        evidence.append("seen_in_multiple_documents")
    if any(claim.claim.status in {"accepted", "edited"} for claim in claims):
        score += 0.08
        evidence.append("accepted_before")
    if _looks_like_skill_fragment(canonical_skill):
        score -= 0.45
        evidence.append("looks_like_fragment")
    if _normalize_lookup(canonical_skill) in SKILL_FRAGMENT_BLACKLIST:
        score -= 0.35
        evidence.append("blacklisted_token")
    return max(0.0, min(1.0, round(score, 4))), evidence


def _serialize_group(group: ClaimGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "profile_id": group.profile_id,
        "group_type": group.group_type,
        "canonical_key": group.canonical_key,
        "canonical_value": group.canonical_value,
        "canonical_value_json": dict(group.canonical_value_json or {}),
        "confidence": group.confidence,
        "merge_action": group.merge_action,
        "review_reason": group.review_reason,
        "status": group.status,
        "claim_ids": list(group.claim_ids_json or []),
        "group_metadata": dict(group.group_metadata or {}),
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def _serialize_anomaly(anomaly: ProfileAnomaly) -> dict[str, Any]:
    return {
        "id": anomaly.id,
        "profile_id": anomaly.profile_id,
        "claim_group_id": anomaly.claim_group_id,
        "anomaly_type": anomaly.anomaly_type,
        "severity": anomaly.severity,
        "message": anomaly.message,
        "candidate_values_json": list(anomaly.candidate_values_json or []),
        "recommended_action": anomaly.recommended_action,
        "status": anomaly.status,
        "created_at": anomaly.created_at,
        "updated_at": anomaly.updated_at,
    }


def _group_display_value(section: str, value_json: dict[str, Any]) -> str:
    if section == "identity":
        return _clean_text(value_json.get("value"))
    if section == "skills":
        return _clean_text(value_json.get("name"))
    if section == "public_profiles":
        label = _clean_text(value_json.get("label"))
        url = _clean_text(value_json.get("url"))
        return " · ".join(part for part in (label, url) if part)
    if section == "work_experience":
        parts = [
            _clean_text(value_json.get("title")),
            _clean_text(value_json.get("organization")),
            " - ".join(part for part in (_clean_text(value_json.get("start_date")), _clean_text(value_json.get("end_date"))) if part),
        ]
        return " · ".join(part for part in parts if part)
    if section == "education":
        parts = [
            _clean_text(value_json.get("degree")),
            _clean_text(value_json.get("institution")),
            _clean_text(value_json.get("field_of_study")),
        ]
        return " · ".join(part for part in parts if part)
    if section == "projects":
        parts = [_clean_text(value_json.get("name")), _clean_text(value_json.get("summary"))]
        return " · ".join(part for part in parts if part)
    if section == "certifications":
        parts = [_clean_text(value_json.get("name")), _clean_text(value_json.get("issuer"))]
        return " · ".join(part for part in parts if part)
    return _clean_text(value_json)


def build_claim_key(claim: FusionClaim, *, user: User | None = None) -> str:
    value_json = dict(claim.claim.value_json or {})
    section = claim.section
    field_name = claim.claim.field_name
    if section == "identity":
        if field_name == "email":
            return f"identity:email:{_normalize_email(value_json.get('value') or '')}"
        if field_name == "phone":
            return f"identity:phone:{_normalize_phone(value_json.get('value') or '')}"
        if field_name == "summary":
            mode = _clean_text(value_json.get("mode")) or _document_focus(claim.document)
            return f"identity:summary:{mode or 'master'}"
        return f"identity:{field_name}"
    if section == "public_profiles":
        url = _clean_text(value_json.get("url"))
        link_type = _classify_link_type(url, label=_clean_text(value_json.get("label")), user=user)
        if link_type in {"project_repo", "project_demo", "client_site", "organization_site", "community_site"}:
            return f"ignored_public_profile:{_canonical_url_key(url)}"
        return f"public_profile:{link_type}"
    if section == "skills":
        return f"skill:{_normalize_lookup(_canonical_skill_name(value_json.get('name') or ''))}"
    if section == "work_experience":
        return "|".join(
            [
                "work_experience",
                _normalize_lookup(value_json.get("organization") or ""),
                _normalize_lookup(value_json.get("title") or ""),
                _normalize_lookup(value_json.get("start_date") or ""),
                _normalize_lookup(value_json.get("end_date") or ""),
            ]
        )
    if section == "education":
        return "|".join(
            [
                "education",
                _normalize_lookup(value_json.get("institution") or ""),
                _normalize_lookup(value_json.get("degree") or ""),
            ]
        )
    if section == "projects":
        return f"project:{_normalize_lookup(_project_anchor(value_json))}"
    if section == "certifications":
        return "|".join(
            [
                "certification",
                _normalize_lookup(value_json.get("name") or ""),
                _normalize_lookup(value_json.get("issuer") or ""),
            ]
        )
    return f"{section}:{claim.normalized_key}"


def normalize_claim(claim: FusionClaim, *, user: User | None = None) -> FusionClaim:
    return FusionClaim(
        claim=claim.claim,
        document=claim.document,
        section=claim.section,
        quality_score=claim.quality_score,
        normalized_key=build_claim_key(claim, user=user),
        display_value=claim.display_value,
    )


def _build_fusion_claims(session: Session, profile: Profile) -> tuple[list[FusionClaim], dict[str, Document]]:
    documents = {
        document.id: document
        for document in session.scalars(select(Document).where(Document.profile_id == profile.id)).all()
    }
    claims = list(
        session.scalars(
            select(StructuredProfileClaim)
            .where(
                StructuredProfileClaim.profile_id == profile.id,
                StructuredProfileClaim.admission_status == "admit",
                StructuredProfileClaim.status != "rejected",
                StructuredProfileClaim.status != "duplicate",
            )
            .order_by(StructuredProfileClaim.section.asc(), StructuredProfileClaim.position.asc(), StructuredProfileClaim.created_at.asc())
        ).all()
    )
    return [
        FusionClaim(
            claim=claim,
            document=documents.get(claim.document_id),
            section=claim.suggested_section or claim.section,
            quality_score=_claim_quality(claim, documents.get(claim.document_id)),
            normalized_key=_normalize_lookup(claim.normalized_value or claim.value_text),
            display_value=_group_display_value(claim.suggested_section or claim.section, dict(claim.value_json or {})),
        )
        for claim in claims
    ], documents


def _build_group(
    *,
    profile: Profile,
    group_type: str,
    canonical_key: str,
    canonical_value: str,
    canonical_value_json: dict[str, Any],
    confidence: float,
    merge_action: str,
    status: str,
    claims: list[FusionClaim],
    review_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ClaimGroup:
    return ClaimGroup(
        profile_id=profile.id,
        group_type=group_type,
        canonical_key=canonical_key,
        canonical_value=canonical_value,
        canonical_value_json=canonical_value_json,
        confidence=round(confidence, 4),
        merge_action=merge_action,
        review_reason=review_reason,
        status=status,
        claim_ids_json=[claim.claim.id for claim in claims],
        group_metadata=metadata or {},
    )


def _anomaly(
    *,
    profile: Profile,
    group: ClaimGroup | None,
    anomaly_type: str,
    severity: str,
    message: str,
    candidate_values: list[dict[str, Any]],
    recommended_action: str,
) -> ProfileAnomaly:
    return ProfileAnomaly(
        profile_id=profile.id,
        claim_group=group,
        anomaly_type=anomaly_type,
        severity=severity,
        message=message,
        candidate_values_json=candidate_values,
        recommended_action=recommended_action,
        status="open",
    )


def _merge_single_truth_group(
    *,
    profile: Profile,
    group_type: str,
    canonical_key: str,
    field_name: str,
    claims: list[FusionClaim],
    normalizer,
    display_label: str,
    anomaly_type: str | None = None,
    review_reason: str | None = None,
    safe_conflict_margin: float = 0.15,
) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    by_value: dict[str, list[FusionClaim]] = defaultdict(list)
    for claim in claims:
        value_json = dict(claim.claim.value_json or {})
        raw = _clean_text(value_json.get("value") or value_json.get("url"))
        normalized = normalizer(raw)
        if not normalized:
            continue
        by_value[normalized].append(claim)

    if not by_value:
        group = _build_group(
            profile=profile,
            group_type=group_type,
            canonical_key=canonical_key,
            canonical_value="",
            canonical_value_json={},
            confidence=0.0,
            merge_action="ignored_empty",
            status="ignored",
            claims=claims,
            review_reason="empty_value",
            metadata={"field_name": field_name, "source_count": len(claims)},
        )
        return group, []

    ranked_values = sorted(
        (
            {
                "normalized": normalized,
                "display": _pick_best_text([(dict(item.claim.value_json or {}).get("value") or dict(item.claim.value_json or {}).get("url") or "", item.quality_score) for item in items]) or normalized,
                "score": max(item.quality_score for item in items),
                "claims": items,
                "raw_values": _unique_strings(
                    [
                        _clean_text(dict(item.claim.value_json or {}).get("value") or dict(item.claim.value_json or {}).get("url"))
                        for item in items
                    ]
                ),
            }
            for normalized, items in by_value.items()
        ),
        key=lambda item: item["score"],
        reverse=True,
    )

    chosen = ranked_values[0]
    conflicting = len(ranked_values) > 1
    second_score = ranked_values[1]["score"] if conflicting else 0.0
    status = "merged"
    merge_action = "merged"
    anomalies: list[ProfileAnomaly] = []

    if conflicting and (chosen["score"] - second_score) < safe_conflict_margin and second_score >= 0.65 and anomaly_type:
        status = "review"
        merge_action = "conflict_review"
        message = f"{display_label} has conflicting values across uploaded evidence."
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type=anomaly_type,
                severity="medium" if field_name not in {"email", "phone"} else "high",
                message=message,
                candidate_values=[
                    {
                        "value": item["display"],
                        "normalized": item["normalized"],
                        "score": item["score"],
                        "document_ids": sorted({claim.claim.document_id for claim in item["claims"]}),
                    }
                    for item in ranked_values
                ],
                recommended_action="review",
            )
        )
    elif conflicting:
        merge_action = "keep_best_ignore_low"

    display_value = chosen["display"]
    value_payload = {"value": display_value}
    if field_name == "url":
        value_payload = {
            "label": display_label,
            "url": _canonicalize_url(display_value),
        }

    group = _build_group(
        profile=profile,
        group_type=group_type,
        canonical_key=canonical_key,
        canonical_value=display_value,
        canonical_value_json=value_payload,
        confidence=chosen["score"],
        merge_action=merge_action,
        status=status,
        claims=claims,
        review_reason=review_reason if status == "review" else None,
        metadata={
            "field_name": field_name,
            "source_count": len(claims),
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in claims]),
            "has_manual_edit": any(
                claim.claim.status == "edited" or claim.claim.resolver_action == "manual"
                for claim in claims
            ),
            "has_user_accepted": any(claim.claim.status in {"accepted", "edited"} for claim in claims),
            "candidate_values": [
                {
                    "value": item["display"],
                    "score": item["score"],
                    "document_count": len({claim.claim.document_id for claim in item["claims"]}),
                    "raw_values": item["raw_values"],
                }
                for item in ranked_values
            ],
            "ignored_values": [item["display"] for item in ranked_values[1:]],
        },
    )
    for anomaly in anomalies:
        anomaly.claim_group = group
    return group, anomalies


def _identity_group_for_field(groups: list[ClaimGroup], field_name: str) -> ClaimGroup | None:
    for group in groups:
        metadata = dict(group.group_metadata or {})
        if group.group_type == "identity" and metadata.get("field_name") == field_name and group.status == "merged":
            return group
    return None


def _merge_skill_group(profile: Profile, skill_name: str, items: list[FusionClaim]) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    score, evidence = _skill_score(items, skill_name)
    status = "merged"
    merge_action = "merged"
    review_reason = None
    if score < 0.55:
        status = "ignored"
        merge_action = "ignored_noise"
        review_reason = "garbage_skill_fragment" if _looks_like_skill_fragment(skill_name) else "low_confidence_skill"
    elif score < 0.80:
        status = "review"
        merge_action = "review_skill"
        review_reason = "low_confidence_skill"

    group = _build_group(
        profile=profile,
        group_type="skill",
        canonical_key=f"skill:{_normalize_lookup(skill_name)}",
        canonical_value=skill_name,
        canonical_value_json={"name": skill_name},
        confidence=score,
        merge_action=merge_action,
        status=status,
        claims=items,
        review_reason=review_reason,
        metadata={
            "source_count": len(items),
            "document_count": len({item.claim.document_id for item in items}),
            "source_document_ids": _unique_strings([item.claim.document_id for item in items]),
            "category": _skill_category(skill_name),
            "reasons": evidence,
            "ignored_fragments": [_clean_text((item.claim.value_json or {}).get("name")) for item in items if _looks_like_skill_fragment((item.claim.value_json or {}).get("name"))],
        },
    )

    anomalies: list[ProfileAnomaly] = []
    if review_reason == "garbage_skill_fragment":
        anomalies.append(
            _anomaly(
                profile=profile,
                group=group,
                anomaly_type="garbage_skill_fragment",
                severity="low",
                message=f"{skill_name} looks like a fragmented or noisy skill token.",
                candidate_values=[{"value": _clean_text((item.claim.value_json or {}).get("name")), "score": item.quality_score} for item in items],
                recommended_action="ignore",
            )
        )
    return group, anomalies


def _skill_groups(profile: Profile, claims: list[FusionClaim]) -> tuple[list[ClaimGroup], list[ProfileAnomaly]]:
    by_skill: dict[str, list[FusionClaim]] = defaultdict(list)
    groups: list[ClaimGroup] = []
    anomalies: list[ProfileAnomaly] = []

    for claim in claims:
        name = _clean_text((claim.claim.value_json or {}).get("name"))
        canonical = _canonical_skill_name(name)
        if not canonical:
            continue
        by_skill[canonical].append(claim)

    for skill_name, items in sorted(by_skill.items()):
        group, group_anomalies = _merge_skill_group(profile, skill_name, items)
        groups.append(group)
        anomalies.extend(group_anomalies)
    return groups, anomalies


def _merge_date_range(claims: list[FusionClaim]) -> tuple[str | None, str | None]:
    starts: list[tuple[str, float]] = []
    ends: list[tuple[str, float]] = []
    for claim in claims:
        value = dict(claim.claim.value_json or {})
        if _clean_text(value.get("start_date")):
            starts.append((_clean_text(value.get("start_date")), claim.quality_score))
        if _clean_text(value.get("end_date")):
            ends.append((_clean_text(value.get("end_date")), claim.quality_score))
    start_value = _pick_best_date(starts, prefer_latest=False)
    end_value = _pick_best_date(ends, prefer_latest=True)
    return start_value, end_value


def _date_window_key(start_date: str | None, end_date: str | None) -> str:
    start_year = _safe_year(start_date) or 0
    if end_date and PRESENT_PATTERN.search(end_date):
        end_year = 9999
    else:
        end_year = _safe_year(end_date) or 9999
    return f"{start_year}:{end_year}"


def _experience_visual_group_id(value: dict[str, Any]) -> str:
    return _clean_text(value.get("visual_group_id") or value.get("title_block_id") or value.get("org_block_id") or "")


def _cluster_experience_claims(claims: list[FusionClaim]) -> list[list[FusionClaim]]:
    clusters: list[list[FusionClaim]] = []
    for claim in claims:
        value = dict(claim.claim.value_json or {})
        organization = _normalize_lookup(value.get("organization") or "")
        title = _normalize_lookup(value.get("title") or "")
        start_date = _clean_text(value.get("start_date"))
        end_date = _clean_text(value.get("end_date"))
        date_window = _date_window_key(start_date, end_date)
        visual_group_id = _experience_visual_group_id(value)
        matched = False
        for cluster in clusters:
            representative = _best_claim(cluster)
            rep_value = dict(representative.claim.value_json or {})
            rep_org = _normalize_lookup(rep_value.get("organization") or "")
            rep_title = _normalize_lookup(rep_value.get("title") or "")
            rep_start = _clean_text(rep_value.get("start_date"))
            rep_end = _clean_text(rep_value.get("end_date"))
            rep_window = _date_window_key(rep_start, rep_end)
            rep_visual_group_id = _experience_visual_group_id(rep_value)
            same_org = bool(organization and rep_org and organization == rep_org)
            title_similarity = _string_similarity(title, rep_title)
            date_matches = _date_overlap(start_date, end_date, rep_start, rep_end)
            same_window = date_window == rep_window
            same_visual_group = bool(visual_group_id and rep_visual_group_id and visual_group_id == rep_visual_group_id)
            if same_org and date_matches and same_window:
                cluster.append(claim)
                matched = True
                break
            if same_org and date_matches and title_similarity >= 0.72:
                cluster.append(claim)
                matched = True
                break
            if not organization or not rep_org:
                if same_visual_group and date_matches and title_similarity >= 0.72:
                    cluster.append(claim)
                    matched = True
                    break
                continue
            if same_window and organization == rep_org:
                cluster.append(claim)
                matched = True
                break
        if not matched:
            clusters.append([claim])
    return clusters


def _merge_experience_group(profile: Profile, claims: list[FusionClaim]) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    titles = [(_clean_text((claim.claim.value_json or {}).get("title")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("title"))]
    organizations = [(_clean_text((claim.claim.value_json or {}).get("organization")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("organization"))]
    locations = [(_clean_text((claim.claim.value_json or {}).get("location")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("location"))]
    best_title = _pick_best_text(titles)
    best_organization = _pick_best_text(organizations)
    best_location = _pick_best_text(locations)
    start_date, end_date = _merge_date_range(claims)
    highlights = _unique_strings(
        [
            *[_clean_text((claim.claim.value_json or {}).get("summary")) for claim in claims],
            *[
                _clean_text(highlight)
                for claim in claims
                for highlight in (claim.claim.value_json or {}).get("highlights", [])
            ],
        ]
    )
    technologies = _unique_strings(
        [
            _clean_text(value)
            for claim in claims
            for value in (claim.claim.value_json or {}).get("technologies", [])
        ]
    )
    links = _unique_strings(
        [
            _clean_text(value)
            for claim in claims
            for value in (claim.claim.value_json or {}).get("links", [])
        ]
    )
    summary = highlights[0] if highlights else None
    item = {
        "title": best_title,
        "organization": best_organization,
        "location": best_location,
        "start_date": start_date,
        "end_date": end_date,
        "summary": summary,
        "highlights": highlights,
        "technologies": technologies,
        "links": links,
        "source_document_ids": _unique_strings([claim.claim.document_id for claim in claims]),
    }
    anomalies: list[ProfileAnomaly] = []
    status = "merged"
    merge_action = "merged"
    review_reason = None

    distinct_titles = [_normalize_lookup(value) for value, _score in titles if value]
    distinct_organizations = [_normalize_lookup(value) for value, _score in organizations if value]
    unique_titles = sorted({value for value in distinct_titles if value})
    unique_orgs = sorted({value for value in distinct_organizations if value})
    experience_text = " ".join(
        part
        for part in [
            best_title or "",
            best_organization or "",
            summary or "",
            *highlights[:4],
            *links,
        ]
        if part
    ).lower()
    looks_project_like = (
        any(hint in experience_text for hint in EXPERIENCE_PROJECT_HINTS)
        and not any(role_word in (best_title or "").lower() for role_word in ROLE_WORDS)
    ) or any(_classify_link_type(link) == "project_repo" for link in links)
    if not best_organization:
        status = "review"
        merge_action = "missing_organization_review"
        review_reason = "missing_organization"
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="missing_organization",
                severity="high",
                message=f"{best_title or 'Experience entry'} is missing an organization.",
                candidate_values=[{"value": _group_display_value("work_experience", dict(claim.claim.value_json or {})), "score": claim.quality_score} for claim in claims],
                recommended_action="review",
            )
        )
    elif len(unique_titles) > 1:
        status = "review"
        merge_action = "role_conflict_review"
        review_reason = "same_company_different_roles"
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="same_company_different_roles",
                severity="medium",
                message=f"{best_organization} has conflicting role titles across evidence.",
                candidate_values=[{"value": value, "score": max(score for text, score in titles if _normalize_lookup(text) == value)} for value in unique_titles],
                recommended_action="review",
            )
        )
    elif len(unique_orgs) > 1:
        status = "review"
        merge_action = "organization_conflict_review"
        review_reason = "same_dates_different_company"
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="same_dates_different_company",
                severity="high",
                message="The same experience window appears tied to different organizations.",
                candidate_values=[{"value": value} for value in unique_orgs],
                recommended_action="review",
            )
        )
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="wrong_company_bullet",
                severity="high",
                message="Some experience bullets may be attached to the wrong company.",
                candidate_values=[
                    {
                        "organization": _clean_text((claim.claim.value_json or {}).get("organization")),
                        "title": _clean_text((claim.claim.value_json or {}).get("title")),
                        "summary": _clean_text((claim.claim.value_json or {}).get("summary")),
                    }
                    for claim in claims
                ],
                recommended_action="review",
            )
        )

    if looks_project_like:
        status = "review"
        merge_action = "section_review"
        review_reason = "project_inside_experience"
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="project_inside_experience",
                severity="medium",
                message=f"{best_title or 'This experience entry'} looks more like a project than a job.",
                candidate_values=[
                    {
                        "title": best_title,
                        "organization": best_organization,
                        "links": links,
                        "summary": summary,
                    }
                ],
                recommended_action="move_to_projects",
            )
        )

    canonical_value = " · ".join(part for part in (best_title, best_organization, " - ".join(part for part in (start_date, end_date) if part)) if part)
    group = _build_group(
        profile=profile,
        group_type="work_experience",
        canonical_key=f"experience:{_normalize_lookup(best_organization or best_title or canonical_value)}:{_normalize_lookup(start_date or '')}",
        canonical_value=canonical_value or best_title or best_organization or "Experience entry",
        canonical_value_json=item,
        confidence=max(claim.quality_score for claim in claims),
        merge_action=merge_action,
        status=status,
        claims=claims,
        review_reason=review_reason,
        metadata={
            "source_count": len(claims),
            "document_count": len({claim.claim.document_id for claim in claims}),
            "candidate_titles": [value for value in _unique_strings([text for text, _score in titles]) if value],
            "candidate_organizations": [value for value in _unique_strings([text for text, _score in organizations]) if value],
        },
    )
    for anomaly in anomalies:
        anomaly.claim_group = group
    return group, anomalies


def _gpa_from_values(*values: str) -> str | None:
    for value in values:
        if not value:
            continue
        match = GPA_PATTERN.search(value)
        if match:
            return next((part for part in match.groups() if part), None)
    return None


def _cluster_education_claims(claims: list[FusionClaim]) -> list[list[FusionClaim]]:
    clusters: list[list[FusionClaim]] = []
    for claim in claims:
        value = dict(claim.claim.value_json or {})
        institution = _clean_text(value.get("institution"))
        degree = _clean_text(value.get("degree"))
        matched = False
        for cluster in clusters:
            representative = _best_claim(cluster)
            rep_value = dict(representative.claim.value_json or {})
            institution_similarity = _string_similarity(institution, _clean_text(rep_value.get("institution")))
            degree_similarity = _string_similarity(degree, _clean_text(rep_value.get("degree")))
            if institution and institution_similarity >= 0.84:
                cluster.append(claim)
                matched = True
                break
            if degree and degree_similarity >= 0.9 and _date_overlap(_clean_text(value.get("start_date")), _clean_text(value.get("end_date")), _clean_text(rep_value.get("start_date")), _clean_text(rep_value.get("end_date"))):
                cluster.append(claim)
                matched = True
                break
        if not matched:
            clusters.append([claim])
    return clusters


def _merge_education_group(profile: Profile, claims: list[FusionClaim]) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    degrees = [(_clean_text((claim.claim.value_json or {}).get("degree")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("degree"))]
    institutions = [(_clean_text((claim.claim.value_json or {}).get("institution")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("institution"))]
    fields = [(_clean_text((claim.claim.value_json or {}).get("field_of_study")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("field_of_study"))]
    best_degree = _pick_best_text(degrees)
    best_institution = _pick_best_text(institutions)
    best_field = _pick_best_text(fields)
    start_date, end_date = _merge_date_range(claims)
    summary = _pick_best_text([(_clean_text((claim.claim.value_json or {}).get("summary")), claim.quality_score) for claim in claims if _clean_text((claim.claim.value_json or {}).get("summary"))])
    gpa_value = _gpa_from_values(*(summary or "", *[_clean_text((claim.claim.value_json or {}).get("summary")) for claim in claims]))
    if gpa_value and (summary or "") and "gpa" not in (summary or "").lower():
        summary = f"{summary} · GPA {gpa_value}" if summary else f"GPA {gpa_value}"

    item = {
        "degree": best_degree,
        "institution": best_institution,
        "field_of_study": best_field,
        "start_date": start_date,
        "end_date": end_date,
        "summary": summary,
        "technologies": [],
        "highlights": [],
        "links": _unique_strings(
            [_clean_text(link) for claim in claims for link in (claim.claim.value_json or {}).get("links", [])]
        ),
        "source_document_ids": _unique_strings([claim.claim.document_id for claim in claims]),
    }
    anomalies: list[ProfileAnomaly] = []
    status = "merged"
    merge_action = "merged"
    review_reason = None

    distinct_degrees = _unique_strings([value for value, _score in degrees if value])
    if len(distinct_degrees) > 1:
        status = "review"
        merge_action = "degree_conflict_review"
        review_reason = "degree_wording_conflict"
        anomalies.append(
            _anomaly(
                profile=profile,
                group=None,
                anomaly_type="degree_wording_conflict",
                severity="medium",
                message=f"{best_institution or 'Education entry'} has conflicting degree wording across evidence.",
                candidate_values=[{"value": value} for value in distinct_degrees],
                recommended_action="review",
            )
        )

    canonical_value = " · ".join(part for part in (best_degree, best_institution, best_field) if part)
    group = _build_group(
        profile=profile,
        group_type="education",
        canonical_key=f"education:{_normalize_lookup(best_institution or best_degree or canonical_value)}",
        canonical_value=canonical_value or "Education entry",
        canonical_value_json=item,
        confidence=max(claim.quality_score for claim in claims),
        merge_action=merge_action,
        status=status,
        claims=claims,
        review_reason=review_reason,
        metadata={
            "source_count": len(claims),
            "document_count": len({claim.claim.document_id for claim in claims}),
            "candidate_degrees": distinct_degrees,
            "gpa": gpa_value,
        },
    )
    for anomaly in anomalies:
        anomaly.claim_group = group
    return group, anomalies


def _project_anchor(value_json: dict[str, Any]) -> str:
    name = _clean_text(value_json.get("name"))
    if name:
        return name
    links = [_clean_text(link) for link in value_json.get("links", []) if _clean_text(link)]
    for link in links:
        segments = _url_segments(link)
        if segments:
            return segments[-1].replace("-", " ").replace("_", " ")
    summary = _clean_text(value_json.get("summary"))
    return " ".join(summary.split()[:6]).strip()


def _project_tech_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tech = {_normalize_lookup(item) for item in left.get("technologies", []) if _clean_text(item)}
    right_tech = {_normalize_lookup(item) for item in right.get("technologies", []) if _clean_text(item)}
    if not left_tech or not right_tech:
        return 0.0
    return len(left_tech & right_tech) / max(1, min(len(left_tech), len(right_tech)))


def _project_similarity(left: dict[str, Any], right: dict[str, Any], *, settings: Settings | None, profile_id: str, session: Session) -> float:
    left_anchor = _project_anchor(left)
    right_anchor = _project_anchor(right)
    name_similarity = _string_similarity(left_anchor, right_anchor)
    left_links = {_canonical_url_key(link) for link in left.get("links", []) if _clean_text(link)}
    right_links = {_canonical_url_key(link) for link in right.get("links", []) if _clean_text(link)}
    if left_links and right_links and left_links & right_links:
        return 1.0
    if _normalize_lookup(left_anchor) and _normalize_lookup(left_anchor) == _normalize_lookup(right_anchor):
        return 1.0

    tech_overlap = _project_tech_overlap(left, right)
    description_similarity = _string_similarity(_clean_text(left.get("summary")), _clean_text(right.get("summary")))
    score = 0.0
    if name_similarity > 0.92:
        score = max(score, name_similarity)
    elif name_similarity > 0.82 and tech_overlap > 0.50 and description_similarity > 0.80:
        score = max(score, min(0.96, 0.55 * name_similarity + 0.2 * tech_overlap + 0.25 * description_similarity))

    if settings and correction_embedding_available(settings) and left_anchor and right_anchor and name_similarity > 0.78 and tech_overlap > 0.35:
        vectors, _stats = ensure_correction_embeddings(
            session,
            profile_id=profile_id,
            texts=[left_anchor, right_anchor],
            settings=settings,
            embedding_kind="fusion:project",
        )
        if len(vectors) == 2 and vectors[0] and vectors[1]:
            score = max(score, min(0.93, 0.55 * score + 0.45 * cosine_similarity(vectors[0], vectors[1])))
    return score


def _cluster_project_claims(session: Session, profile: Profile, claims: list[FusionClaim], settings: Settings | None) -> list[list[FusionClaim]]:
    clusters: list[list[FusionClaim]] = []
    for claim in claims:
        value = dict(claim.claim.value_json or {})
        matched = False
        for cluster in clusters:
            representative = _best_claim(cluster)
            rep_value = dict(representative.claim.value_json or {})
            if _project_similarity(value, rep_value, settings=settings, profile_id=profile.id, session=session) >= 0.84:
                cluster.append(claim)
                matched = True
                break
        if not matched:
            clusters.append([claim])
    return clusters


def _merge_project_group(profile: Profile, claims: list[FusionClaim]) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    items = [dict(claim.claim.value_json or {}) for claim in claims]
    merged: dict[str, Any] = {}
    for item in items:
        merged = _merge_item_dict(merged, item) if merged else dict(item)
    if not _clean_text(merged.get("name")):
        merged["name"] = _project_anchor(merged)
    merged["source_document_ids"] = _unique_strings([claim.claim.document_id for claim in claims])
    canonical_value = " · ".join(part for part in (_clean_text(merged.get("name")), _clean_text(merged.get("summary"))) if part)
    return (
        _build_group(
            profile=profile,
            group_type="project",
            canonical_key=f"project:{_normalize_lookup(_clean_text(merged.get('name')) or canonical_value)}",
            canonical_value=canonical_value or _clean_text(merged.get("name")) or "Project",
            canonical_value_json=merged,
            confidence=max(claim.quality_score for claim in claims),
            merge_action="merged",
            status="merged",
            claims=claims,
            metadata={
                "source_count": len(claims),
                "document_count": len({claim.claim.document_id for claim in claims}),
            },
        ),
        [],
    )


def _merge_certification_group(profile: Profile, claims: list[FusionClaim]) -> tuple[ClaimGroup, list[ProfileAnomaly]]:
    items = [dict(claim.claim.value_json or {}) for claim in claims]
    merged: dict[str, Any] = {}
    for item in items:
        merged = _merge_item_dict(merged, item) if merged else dict(item)
    merged["source_document_ids"] = _unique_strings([claim.claim.document_id for claim in claims])
    canonical_value = " · ".join(part for part in (_clean_text(merged.get("name")), _clean_text(merged.get("issuer"))) if part)
    return (
        _build_group(
            profile=profile,
            group_type="certification",
            canonical_key=f"certification:{_normalize_lookup(_clean_text(merged.get('name')) or canonical_value)}",
            canonical_value=canonical_value or "Certification",
            canonical_value_json=merged,
            confidence=max(claim.quality_score for claim in claims),
            merge_action="merged",
            status="merged",
            claims=claims,
            metadata={
                "source_count": len(claims),
                "document_count": len({claim.claim.document_id for claim in claims}),
            },
        ),
        [],
    )


def cluster_claims(
    session: Session,
    profile: Profile,
    claims: list[FusionClaim],
    *,
    user: User | None = None,
    settings: Settings | None = None,
) -> list[ClaimCluster]:
    by_section: dict[str, list[FusionClaim]] = defaultdict(list)
    for claim in claims:
        by_section[claim.section].append(claim)

    clusters: list[ClaimCluster] = []

    identity_claims = by_section.get("identity", [])
    for field_name in ("full_name", "headline", "summary", "location", "email", "phone"):
        field_claims = [claim for claim in identity_claims if claim.claim.field_name == field_name]
        if field_claims:
            if field_name == "summary":
                summary_buckets: dict[str, list[FusionClaim]] = defaultdict(list)
                for claim in field_claims:
                    value_json = dict(claim.claim.value_json or {})
                    mode = _clean_text(value_json.get("mode")) or _document_focus(claim.document) or "master"
                    summary_buckets[mode].append(claim)
                for mode, mode_claims in summary_buckets.items():
                    clusters.append(
                        ClaimCluster(
                            group_type="identity",
                            cluster_key=f"identity:summary:{mode}",
                            claims=mode_claims,
                            metadata={"field_name": field_name, "mode": mode},
                        )
                    )
            else:
                clusters.append(
                    ClaimCluster(
                        group_type="identity",
                        cluster_key=f"identity:{field_name}",
                        claims=field_claims,
                        metadata={"field_name": field_name},
                    )
                )

    link_claims = by_section.get("public_profiles", [])
    links_by_key: dict[str, list[FusionClaim]] = defaultdict(list)
    for claim in link_claims:
        value_json = dict(claim.claim.value_json or {})
        url = _clean_text(value_json.get("url"))
        if not url:
            continue
        link_type = _classify_link_type(url, label=_clean_text(value_json.get("label")), user=user)
        if link_type in {"project_repo", "project_demo", "client_site", "organization_site", "community_site"}:
            cluster_key = f"ignored_public_profile:{_canonical_url_key(url)}"
        else:
            cluster_key = f"public_profile:{link_type}"
        links_by_key[cluster_key].append(claim)
    for cluster_key, field_claims in links_by_key.items():
        link_type = cluster_key.split(":", 1)[1]
        clusters.append(
            ClaimCluster(
                group_type="public_profile" if not cluster_key.startswith("ignored_public_profile") else "ignored_public_profile",
                cluster_key=cluster_key,
                claims=field_claims,
                metadata={"link_type": link_type},
            )
        )

    skill_buckets: dict[str, list[FusionClaim]] = defaultdict(list)
    for claim in by_section.get("skills", []):
        name = _clean_text((claim.claim.value_json or {}).get("name"))
        canonical = _canonical_skill_name(name)
        if canonical:
            skill_buckets[canonical].append(claim)
    for skill_name, skill_claims in skill_buckets.items():
        clusters.append(
            ClaimCluster(
                group_type="skill",
                cluster_key=f"skill:{_normalize_lookup(skill_name)}",
                claims=skill_claims,
                metadata={"skill_name": skill_name},
            )
        )

    for index, cluster in enumerate(_cluster_experience_claims(by_section.get("work_experience", []))):
        clusters.append(
            ClaimCluster(
                group_type="work_experience",
                cluster_key=f"work_experience:{index}",
                claims=cluster,
            )
        )

    for index, cluster in enumerate(_cluster_education_claims(by_section.get("education", []))):
        clusters.append(
            ClaimCluster(
                group_type="education",
                cluster_key=f"education:{index}",
                claims=cluster,
            )
        )

    for index, cluster in enumerate(_cluster_project_claims(session, profile, by_section.get("projects", []), settings)):
        clusters.append(
            ClaimCluster(
                group_type="project",
                cluster_key=f"project:{index}",
                claims=cluster,
            )
        )

    certification_buckets: dict[str, list[FusionClaim]] = defaultdict(list)
    for claim in by_section.get("certifications", []):
        value = dict(claim.claim.value_json or {})
        key = f"{_normalize_lookup(value.get('name') or '')}|{_normalize_lookup(value.get('issuer') or '')}"
        certification_buckets[key].append(claim)
    for key, cluster in certification_buckets.items():
        clusters.append(
            ClaimCluster(
                group_type="certification",
                cluster_key=f"certification:{key}",
                claims=cluster,
            )
        )

    return clusters


def merge_claim_group(
    session: Session,
    profile: Profile,
    cluster: ClaimCluster,
    *,
    settings: Settings | None = None,
) -> tuple[list[ClaimGroup], list[ProfileAnomaly]]:
    if cluster.group_type == "identity":
        field_name = str(cluster.metadata.get("field_name") or "")
        normalizer = _normalize_email if field_name == "email" else _normalize_phone if field_name == "phone" else _clean_text
        anomaly_type = (
            "conflicting_contact_value"
            if field_name in {"email", "phone", "location", "full_name"}
            else "current_headline_conflict"
            if field_name == "headline"
            else "summary_conflict"
            if field_name == "summary"
            else None
        )
        group, anomalies = _merge_single_truth_group(
            profile=profile,
            group_type="identity",
            canonical_key=cluster.cluster_key,
            field_name=field_name,
            claims=cluster.claims,
            normalizer=normalizer,
            display_label=field_name.replace("_", " ").title(),
            anomaly_type=anomaly_type,
            review_reason=anomaly_type,
        )
        return [group], anomalies

    if cluster.group_type == "public_profile":
        link_type = str(cluster.metadata.get("link_type") or "website")
        label = LINK_TYPE_LABELS.get(link_type, link_type.replace("_", " ").title())
        group, anomalies = _merge_single_truth_group(
            profile=profile,
            group_type="public_profile",
            canonical_key=cluster.cluster_key,
            field_name="url",
            claims=cluster.claims,
            normalizer=_canonical_url_key,
            display_label=label,
            anomaly_type="portfolio_conflict" if link_type == "portfolio" else "conflicting_contact_value",
            review_reason="portfolio_conflict" if link_type == "portfolio" else "conflicting_contact_value",
            safe_conflict_margin=0.18,
        )
        payload = dict(group.canonical_value_json or {})
        payload["label"] = label
        payload["url"] = _canonicalize_url(payload.get("url") or group.canonical_value)
        group.canonical_value_json = payload
        group.group_metadata = {
            **dict(group.group_metadata or {}),
            "field_name": "url",
            "link_type": link_type,
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in cluster.claims]),
        }
        return [group], anomalies

    if cluster.group_type == "ignored_public_profile":
        groups: list[ClaimGroup] = []
        anomalies: list[ProfileAnomaly] = []
        for claim in cluster.claims:
            url = _canonicalize_url((claim.claim.value_json or {}).get("url") or "")
            link_type = _classify_link_type(
                url,
                label=_clean_text((claim.claim.value_json or {}).get("label")),
                user=None,
            )
            repo_group = _build_group(
                profile=profile,
                group_type="ignored_public_profile",
                canonical_key=f"ignored_link:{_canonical_url_key(url)}",
                canonical_value=url,
                canonical_value_json={
                    "label": _clean_text((claim.claim.value_json or {}).get("label")) or "Repository",
                    "url": url,
                },
                confidence=claim.quality_score,
                merge_action="ignored_repo_link",
                status="ignored",
                claims=[claim],
                review_reason="section_misclassification",
                metadata={
                    "field_name": "url",
                    "link_type": link_type,
                    "source_count": 1,
                    "source_document_ids": [claim.claim.document_id],
                },
            )
            groups.append(repo_group)
        return groups, anomalies

    if cluster.group_type == "skill":
        group, anomalies = _merge_skill_group(profile, str(cluster.metadata.get("skill_name") or ""), cluster.claims)
        return [group], anomalies

    if cluster.group_type == "work_experience":
        group, anomalies = _merge_experience_group(profile, cluster.claims)
        group.group_metadata = {
            **dict(group.group_metadata or {}),
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in cluster.claims]),
        }
        return [group], anomalies

    if cluster.group_type == "education":
        group, anomalies = _merge_education_group(profile, cluster.claims)
        group.group_metadata = {
            **dict(group.group_metadata or {}),
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in cluster.claims]),
        }
        return [group], anomalies

    if cluster.group_type == "project":
        group, anomalies = _merge_project_group(profile, cluster.claims)
        group.group_metadata = {
            **dict(group.group_metadata or {}),
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in cluster.claims]),
        }
        return [group], anomalies

    if cluster.group_type == "certification":
        group, anomalies = _merge_certification_group(profile, cluster.claims)
        group.group_metadata = {
            **dict(group.group_metadata or {}),
            "source_document_ids": _unique_strings([claim.claim.document_id for claim in cluster.claims]),
        }
        return [group], anomalies

    return [], []


def _group_source_count(group: ClaimGroup) -> int:
    metadata = dict(group.group_metadata or {})
    return int(metadata.get("source_count") or len(group.claim_ids_json or []))


def _group_duplicate_key(group: ClaimGroup) -> str:
    payload = dict(group.canonical_value_json or {})
    if group.group_type == "public_profile":
        return f"public_profile:{_canonical_url_key(payload.get('url') or group.canonical_value)}"
    if group.group_type == "skill":
        return f"skill:{_normalize_lookup(payload.get('name') or group.canonical_value)}"
    if group.group_type == "education":
        return f"education:{_normalize_lookup(payload.get('institution') or '')}|{_normalize_lookup(payload.get('degree') or '')}"
    if group.group_type == "project":
        links = payload.get("links", []) or []
        if links:
            return f"project:{_canonical_url_key(links[0])}"
        return f"project:{_normalize_lookup(payload.get('name') or group.canonical_value)}"
    if group.group_type == "certification":
        return f"certification:{_normalize_lookup(payload.get('name') or '')}|{_normalize_lookup(payload.get('issuer') or '')}"
    if group.group_type == "work_experience":
        return "|".join(
            [
                "work_experience",
                _normalize_lookup(payload.get("organization") or ""),
                _normalize_lookup(payload.get("title") or ""),
                _normalize_lookup(payload.get("start_date") or ""),
                _normalize_lookup(payload.get("end_date") or ""),
            ]
        )
    return f"{group.group_type}:{_normalize_lookup(group.canonical_value)}"


def _group_duplicate_text(group: ClaimGroup) -> str:
    payload = dict(group.canonical_value_json or {})
    if group.group_type == "public_profile":
        return _clean_text(payload.get("url") or group.canonical_value)
    if group.group_type == "skill":
        return _clean_text(payload.get("name") or group.canonical_value)
    if group.group_type == "education":
        return " ".join(
            part for part in [
                _clean_text(payload.get("degree")),
                _clean_text(payload.get("institution")),
                _clean_text(payload.get("field_of_study")),
            ] if part
        )
    if group.group_type == "project":
        return " ".join(
            part for part in [
                _clean_text(payload.get("name")),
                _clean_text(payload.get("summary")),
                " ".join(_clean_text(item) for item in payload.get("technologies", [])[:6]),
            ] if part
        )
    if group.group_type == "certification":
        return " ".join(part for part in [_clean_text(payload.get("name")), _clean_text(payload.get("issuer"))] if part)
    if group.group_type == "work_experience":
        return " ".join(
            part for part in [
                _clean_text(payload.get("title")),
                _clean_text(payload.get("organization")),
                _clean_text(payload.get("summary")),
            ] if part
        )
    return _clean_text(group.canonical_value)


def _project_group_duplicate_decision(
    left: ClaimGroup,
    right: ClaimGroup,
    *,
    semantic_score: float,
) -> tuple[bool, bool]:
    left_payload = dict(left.canonical_value_json or {})
    right_payload = dict(right.canonical_value_json or {})
    left_name = _clean_text(left_payload.get("name"))
    right_name = _clean_text(right_payload.get("name"))
    left_links = {_canonical_url_key(link) for link in left_payload.get("links", []) if _clean_text(link)}
    right_links = {_canonical_url_key(link) for link in right_payload.get("links", []) if _clean_text(link)}
    if left_links and right_links and left_links & right_links:
        return True, False
    name_similarity = _string_similarity(left_name, right_name)
    if _normalize_lookup(left_name) and _normalize_lookup(left_name) == _normalize_lookup(right_name):
        return True, False
    if name_similarity > 0.92:
        return True, False
    description_similarity = _string_similarity(_clean_text(left_payload.get("summary")), _clean_text(right_payload.get("summary")))
    tech_overlap = _project_tech_overlap(left_payload, right_payload)
    exactish = bool(name_similarity > 0.82 and tech_overlap > 0.50 and description_similarity > 0.80)
    potential = bool(
        not exactish
        and (
            (name_similarity > 0.76 and tech_overlap > 0.35 and description_similarity > 0.68)
            or (name_similarity > 0.84 and semantic_score >= SEMANTIC_DUPLICATE_REVIEW_THRESHOLD)
        )
    )
    return exactish, potential


def _experience_group_duplicate_decision(left: ClaimGroup, right: ClaimGroup) -> tuple[bool, bool]:
    left_payload = dict(left.canonical_value_json or {})
    right_payload = dict(right.canonical_value_json or {})
    left_org = _normalize_lookup(left_payload.get("organization") or "")
    right_org = _normalize_lookup(right_payload.get("organization") or "")
    if not left_org or not right_org or left_org != right_org:
        return False, False

    left_title = _normalize_lookup(left_payload.get("title") or "")
    right_title = _normalize_lookup(right_payload.get("title") or "")
    left_start = _clean_text(left_payload.get("start_date"))
    left_end = _clean_text(left_payload.get("end_date"))
    right_start = _clean_text(right_payload.get("start_date"))
    right_end = _clean_text(right_payload.get("end_date"))
    overlap = _date_overlap(left_start, left_end, right_start, right_end)
    same_window = _date_window_key(left_start, left_end) == _date_window_key(right_start, right_end)
    titles_close = bool(left_title and right_title and _string_similarity(left_title, right_title) >= 0.9)
    same_title = bool(left_title and right_title and left_title == right_title)
    dates_missing = not (left_start or left_end or right_start or right_end)
    nearby_dates = abs((_safe_year(left_start or left_end) or 0) - (_safe_year(right_start or right_end) or 0)) <= 1

    exact_duplicate = bool((overlap and same_window) or (same_title and (dates_missing or nearby_dates)))
    potential_duplicate = bool(not exact_duplicate and same_title and overlap)
    return exact_duplicate, potential_duplicate


def _mark_group_review(group: ClaimGroup, *, reason: str, action: str = "duplicate_review") -> None:
    if group.status == "ignored":
        return
    group.status = "review"
    group.review_reason = reason
    group.merge_action = action


def _group_ref(group: ClaimGroup) -> str:
    return str(group.id or group.canonical_key or group.canonical_value or "").strip()


def _merge_duplicate_group_ref(metadata: dict[str, Any], group: ClaimGroup) -> dict[str, Any]:
    duplicate_refs = [
        ref
        for ref in [*(metadata.get("merged_duplicate_group_ids", []) or []), _group_ref(group)]
        if ref
    ]
    metadata["merged_duplicate_group_ids"] = _unique_strings(duplicate_refs)
    return metadata


def dedupe_claims(
    session: Session,
    profile: Profile,
    groups: list[ClaimGroup],
    *,
    settings: Settings | None = None,
) -> tuple[list[ClaimGroup], list[ProfileAnomaly]]:
    anomalies: list[ProfileAnomaly] = []
    active_by_type: dict[str, list[ClaimGroup]] = defaultdict(list)
    for group in groups:
        if group.status != "ignored":
            active_by_type[group.group_type].append(group)

    for group_type, typed_groups in active_by_type.items():
        exact_buckets: dict[str, list[ClaimGroup]] = defaultdict(list)
        for group in typed_groups:
            exact_buckets[_group_duplicate_key(group)].append(group)
        for duplicates in exact_buckets.values():
            if len(duplicates) < 2:
                continue
            duplicates.sort(key=lambda item: (item.confidence, _group_source_count(item)), reverse=True)
            winner = duplicates[0]
            for loser in duplicates[1:]:
                loser.status = "ignored"
                loser.merge_action = "ignored_exact_duplicate"
                loser.review_reason = "duplicate_group"
                metadata = dict(winner.group_metadata or {})
                winner.group_metadata = _merge_duplicate_group_ref(metadata, loser)
            if group_type == "public_profile":
                winner_formats = {
                    raw
                    for item in (dict(winner.group_metadata or {}).get("candidate_values", []) or [])
                    for raw in (item.get("raw_values") or [])
                }
                for loser in duplicates[1:]:
                    for item in (dict(loser.group_metadata or {}).get("candidate_values", []) or []):
                        winner_formats.update(item.get("raw_values") or [])
                if len(winner_formats) > 1:
                    anomalies.append(
                        _anomaly(
                            profile=profile,
                            group=winner,
                            anomaly_type="duplicate_url_different_format",
                            severity="low",
                            message="The same link appeared in multiple URL formats and was canonicalized automatically.",
                            candidate_values=[{"value": value} for value in sorted(winner_formats)],
                            recommended_action="keep_canonical",
                        )
                    )

        comparable_groups = [group for group in typed_groups if group.status != "ignored"]
        if len(comparable_groups) < 2:
            continue

        texts = [_group_duplicate_text(group) for group in comparable_groups]
        vectors: list[list[float]] = [[] for _ in comparable_groups]
        if settings and correction_embedding_available(settings) and group_type in {"project", "education", "certification", "skill"}:
            vectors, _stats = ensure_correction_embeddings(
                session,
                profile_id=profile.id,
                texts=texts,
                settings=settings,
                embedding_kind=f"fusion:dedupe:{group_type}",
            )

        for index, left in enumerate(comparable_groups):
            if left.status == "ignored":
                continue
            for compare_index in range(index + 1, len(comparable_groups)):
                right = comparable_groups[compare_index]
                if right.status == "ignored":
                    continue
                if _group_duplicate_key(left) == _group_duplicate_key(right):
                    continue
                if group_type == "public_profile":
                    left_link_type = str((left.group_metadata or {}).get("link_type") or "")
                    right_link_type = str((right.group_metadata or {}).get("link_type") or "")
                    if left_link_type and right_link_type and left_link_type != right_link_type:
                        continue

                fuzzy_score = _string_similarity(texts[index], texts[compare_index])
                semantic_score = 0.0
                if group_type == "work_experience":
                    exactish_duplicate, potential_duplicate = _experience_group_duplicate_decision(left, right)
                else:
                    if vectors[index] and vectors[compare_index]:
                        semantic_score = cosine_similarity(vectors[index], vectors[compare_index])
                    exactish_duplicate = fuzzy_score >= FUZZY_DUPLICATE_THRESHOLD or semantic_score >= SEMANTIC_DUPLICATE_THRESHOLD
                    potential_duplicate = (
                        FUZZY_DUPLICATE_REVIEW_THRESHOLD <= fuzzy_score < FUZZY_DUPLICATE_THRESHOLD
                        or SEMANTIC_DUPLICATE_REVIEW_THRESHOLD <= semantic_score < SEMANTIC_DUPLICATE_THRESHOLD
                    )

                if group_type == "project":
                    exactish_duplicate, potential_duplicate = _project_group_duplicate_decision(
                        left,
                        right,
                        semantic_score=semantic_score,
                    )

                if exactish_duplicate:
                    winner, loser = (
                        (left, right)
                        if (left.confidence, _group_source_count(left)) >= (right.confidence, _group_source_count(right))
                        else (right, left)
                    )
                    loser.status = "ignored"
                    loser.merge_action = "ignored_duplicate_group"
                    loser.review_reason = "duplicate_group"
                    metadata = dict(winner.group_metadata or {})
                    winner.group_metadata = _merge_duplicate_group_ref(metadata, loser)
                    continue

                if potential_duplicate:
                    lower, higher = (
                        (left, right)
                        if (left.confidence, _group_source_count(left)) <= (right.confidence, _group_source_count(right))
                        else (right, left)
                    )
                    _mark_group_review(lower, reason="potential_duplicate")
                    anomalies.append(
                        _anomaly(
                            profile=profile,
                            group=lower,
                            anomaly_type="potential_duplicate",
                            severity="medium",
                            message=f"{higher.canonical_value} and {lower.canonical_value} may be duplicate {group_type.replace('_', ' ')} entries.",
                            candidate_values=[
                                {"value": higher.canonical_value, "fuzzy_score": round(fuzzy_score, 4), "semantic_score": round(semantic_score, 4)},
                                {"value": lower.canonical_value, "fuzzy_score": round(fuzzy_score, 4), "semantic_score": round(semantic_score, 4)},
                            ],
                            recommended_action="review",
                        )
                    )

    return groups, anomalies


def detect_anomalies(
    profile: Profile,
    groups: list[ClaimGroup],
) -> list[ProfileAnomaly]:
    anomalies: list[ProfileAnomaly] = []
    for group in groups:
        if group.group_type == "public_profile" and group.status != "ignored":
            candidate_values = dict(group.group_metadata or {}).get("candidate_values", []) or []
            raw_formats = {
                raw
                for item in candidate_values
                for raw in (item.get("raw_values") or [])
                if _clean_text(raw)
            }
            canonical_destinations = {_canonical_url_key(value) for value in raw_formats}
            if len(raw_formats) > 1 and len(canonical_destinations) == 1:
                anomalies.append(
                    _anomaly(
                        profile=profile,
                        group=group,
                        anomaly_type="duplicate_url_different_format",
                        severity="low",
                        message="The same destination URL appeared in multiple formats and was canonicalized automatically.",
                        candidate_values=[{"value": value} for value in sorted(raw_formats)],
                        recommended_action="keep_canonical",
                    )
                )
        if group.group_type == "ignored_public_profile":
            link_type = str((group.group_metadata or {}).get("link_type") or "website")
            message = {
                "project_repo": "A repository link was kept with project evidence instead of personal profile links.",
                "project_demo": "A project demo link was kept with project evidence instead of personal profile links.",
                "client_site": "A client or external site was kept out of personal profile links.",
                "community_site": "A community link was kept out of personal portfolio links.",
                "organization_site": "An organization link was kept out of personal portfolio links.",
            }.get(link_type, "A non-profile website was kept out of personal profile links.")
            anomalies.append(
                _anomaly(
                    profile=profile,
                    group=group,
                    anomaly_type="section_misclassification",
                    severity="low",
                    message=message,
                    candidate_values=[{"value": _clean_text((group.canonical_value_json or {}).get("url") or group.canonical_value)}],
                    recommended_action="keep_under_project",
                )
            )
            continue
        if group.group_type != "work_experience" or group.status == "ignored":
            continue
        payload = dict(group.canonical_value_json or {})
        experience_text = " ".join(
            part
            for part in [
                _clean_text(payload.get("title")),
                _clean_text(payload.get("summary")),
                *[_clean_text(item) for item in payload.get("highlights", [])[:4]],
                *[_clean_text(item) for item in payload.get("links", [])[:4]],
            ]
            if part
        ).lower()
        if group.review_reason == "project_inside_experience":
            continue
        if any(_classify_link_type(link) == "project_repo" for link in payload.get("links", [])) or (
            any(hint in experience_text for hint in EXPERIENCE_PROJECT_HINTS)
            and not _clean_text(payload.get("organization"))
        ):
            if group.status == "merged":
                group.status = "review"
                group.review_reason = "project_inside_experience"
                group.merge_action = "section_review"
            anomalies.append(
                _anomaly(
                    profile=profile,
                    group=group,
                    anomaly_type="project_inside_experience",
                    severity="medium",
                    message=f"{payload.get('title') or 'This experience entry'} looks more like a project than a job.",
                    candidate_values=[{"value": payload.get("title"), "links": payload.get("links", [])}],
                    recommended_action="move_to_projects",
                )
            )
    return anomalies


def _append_repo_links_to_projects(project_groups: list[ClaimGroup], repo_groups: list[ClaimGroup]) -> None:
    if not project_groups or not repo_groups:
        return
    for repo_group in repo_groups:
        repo_url = _clean_text((repo_group.canonical_value_json or {}).get("url"))
        if not repo_url:
            continue
        link_type = str((repo_group.group_metadata or {}).get("link_type") or "")
        if link_type not in {"project_repo", "project_demo", "client_site"}:
            continue
        segments = _url_segments(repo_url)
        repo_name = (segments[-1] if segments else _safe_host(repo_url).split(".", 1)[0]).replace("-", " ").replace("_", " ").strip()
        if not repo_name:
            continue
        for project_group in project_groups:
            item = dict(project_group.canonical_value_json or {})
            project_name = _clean_text(item.get("name"))
            if _string_similarity(project_name, repo_name) >= 0.78:
                item["links"] = _unique_strings([*(item.get("links", []) or []), repo_url])
                project_group.canonical_value_json = item
                project_group.canonical_value = " · ".join(part for part in (_clean_text(item.get("name")), _clean_text(item.get("summary"))) if part) or project_group.canonical_value
                metadata = dict(project_group.group_metadata or {})
                metadata["repo_links_enriched"] = _unique_strings([*(metadata.get("repo_links_enriched", []) or []), repo_url])
                project_group.group_metadata = metadata
                break


def _group_source_documents(group: ClaimGroup, documents: dict[str, Document]) -> list[Document]:
    return [
        documents[document_id]
        for document_id in dict(group.group_metadata or {}).get("source_document_ids", []) or []
        if document_id in documents
    ]


def _group_source_priority(group: ClaimGroup, field_bucket: str, documents: dict[str, Document]) -> float:
    source_documents = _group_source_documents(group, documents)
    if not source_documents:
        return 0.72
    return max(source_priority_for_role(field_bucket, _document_role(document)) for document in source_documents)


def _group_focus(group: ClaimGroup, documents: dict[str, Document]) -> str:
    source_documents = _group_source_documents(group, documents)
    if not source_documents:
        return "master"
    focus_scores: dict[str, float] = defaultdict(float)
    for document in source_documents:
        focus_scores[_document_focus(document)] += _document_source_quality(document)
    if not focus_scores:
        return "master"
    return max(focus_scores.items(), key=lambda item: item[1])[0]


def _resolve_profile_focus(groups: list[ClaimGroup], documents: dict[str, Document], user: User | None) -> str:
    focus_scores: dict[str, float] = defaultdict(float)
    for group in groups:
        if group.status == "ignored":
            continue
        focus = _group_focus(group, documents)
        weight = max(0.2, float(group.confidence))
        if group.group_type == "work_experience":
            weight += 0.25
        elif group.group_type == "project":
            weight += 0.18
        elif group.group_type == "skill":
            weight += 0.08
        focus_scores[focus] += weight
    if not focus_scores:
        return infer_profile_focus({"identity": {"full_name": user.full_name if user else None}}, "")
    return max(focus_scores.items(), key=lambda item: item[1])[0]


def _headline_from_experience_payload(payload: dict[str, Any]) -> str | None:
    title = _clean_text(payload.get("title"))
    organization = _clean_text(payload.get("organization"))
    if title and organization:
        return f"{title} · {organization}"
    return title or organization or None


def _summary_like_text(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return False
    if len(cleaned) < 80 or len(cleaned) > 900:
        return False
    if re.search(r"^(?:worked on|created|implemented|built|developed|designed|refactored|migrated|led)\b", cleaned, flags=re.IGNORECASE):
        return False
    if YEAR_PATTERN.search(cleaned[:120]):
        return False
    if "|" in cleaned and len(cleaned.split()) < 32:
        return False
    return True


def _resolve_current_role_group(groups: list[ClaimGroup], documents: dict[str, Document]) -> ClaimGroup | None:
    candidates = [group for group in groups if group.group_type == "work_experience" and group.status == "merged"]
    if not candidates:
        return None

    def score(group: ClaimGroup) -> tuple[float, float, float]:
        payload = dict(group.canonical_value_json or {})
        if not _clean_text(payload.get("organization")) or not _clean_text(payload.get("title")) or not _clean_text(payload.get("start_date")):
            return (-1.0, -1.0, -1.0)
        end_date = _clean_text(payload.get("end_date"))
        is_current = 1.0 if (not end_date or PRESENT_PATTERN.search(end_date)) else 0.0
        source_priority = _group_source_priority(group, "current_experience" if is_current else "historical_experience", documents)
        return (
            1.2 * is_current + 0.55 * float(group.confidence) + 0.35 * source_priority,
            _safe_year(end_date) or 9999 if is_current else (_safe_year(end_date) or 0),
            _safe_year(payload.get("start_date")) or 0,
        )

    return max(candidates, key=score)


def _collect_mode_summaries(groups: list[ClaimGroup], documents: dict[str, Document], current_role_group: ClaimGroup | None) -> dict[str, str]:
    identity_candidates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    fallback_candidates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for group in groups:
        if group.status != "merged":
            continue
        payload = dict(group.canonical_value_json or {})
        if group.group_type == "identity" and (group.group_metadata or {}).get("field_name") == "summary":
            summary = _clean_text(payload.get("value"))
            if not _summary_like_text(summary):
                continue
            focus = _group_focus(group, documents)
            score = float(group.confidence) + 0.45 * _group_source_priority(group, "summary", documents) + 0.4
            identity_candidates[focus].append((summary, score))
            identity_candidates["master"].append((summary, score))
        elif group.group_type == "work_experience":
            summary = _clean_text(payload.get("summary"))
            if not _summary_like_text(summary):
                continue
            focus = _group_focus(group, documents)
            score = float(group.confidence) + 0.08 * _group_source_priority(group, "current_experience", documents)
            fallback_candidates[focus].append((summary, score))
            fallback_candidates["master"].append((summary, score))

    if current_role_group is not None:
        payload = dict(current_role_group.canonical_value_json or {})
        summary = _clean_text(payload.get("summary"))
        if _summary_like_text(summary):
            focus = _group_focus(current_role_group, documents)
            fallback_candidates[focus].append((summary, float(current_role_group.confidence) + 0.16))
            fallback_candidates["master"].append((summary, float(current_role_group.confidence) + 0.16))

    resolved: dict[str, str] = {}
    for mode in ("ai_ml", "web_dev", "master"):
        mode_candidates = identity_candidates.get(mode, [])
        if not mode_candidates and mode != "master":
            mode_candidates = identity_candidates.get("master", [])
        if not mode_candidates:
            mode_candidates = fallback_candidates.get(mode, [])
        if not mode_candidates and mode != "master":
            mode_candidates = fallback_candidates.get("master", [])
        best = _pick_best_text(mode_candidates)
        if best:
            resolved[mode] = best
    return resolved


def _review_level(group: ClaimGroup, anomaly_map: dict[str, ProfileAnomaly]) -> str:
    anomaly = anomaly_map.get(group.id)
    if group.review_reason in CRITICAL_REVIEW_REASONS:
        return "critical"
    if anomaly and anomaly.severity in {"high", "critical"}:
        return "critical"
    if group.review_reason in OPTIONAL_REVIEW_REASONS:
        return "optional"
    return "optional"


def _build_canonical_from_groups(profile: Profile, groups: list[ClaimGroup], user: User | None) -> dict[str, Any]:
    canonical = _default_overview_data()
    identity = _default_identity()
    work_items: list[dict[str, Any]] = []
    education_items: list[dict[str, Any]] = []
    project_items: list[dict[str, Any]] = []
    certification_items: list[dict[str, Any]] = []
    source_document_ids: set[str] = set()

    for group in groups:
        if group.status != "merged":
            continue
        payload = dict(group.canonical_value_json or {})
        metadata = dict(group.group_metadata or {})
        source_document_ids.update(metadata.get("source_document_ids", []) or [])
        if group.group_type == "identity":
            field_name = metadata.get("field_name")
            if field_name in {"full_name", "headline", "summary", "location"}:
                identity[field_name] = _clean_text(payload.get("value"))
            elif field_name == "email":
                identity["emails"] = _unique_strings([*identity.get("emails", []), _clean_text(payload.get("value"))])
            elif field_name == "phone":
                identity["phones"] = _unique_strings([*identity.get("phones", []), _clean_text(payload.get("value"))])
        elif group.group_type == "public_profile":
            canonical["public_profiles"] = _unique_links([*canonical["public_profiles"], payload])
        elif group.group_type == "skill":
            canonical["skills"] = _unique_strings([*canonical["skills"], _clean_text(payload.get("name"))])
        elif group.group_type == "work_experience":
            work_items.append(payload)
        elif group.group_type == "education":
            education_items.append(payload)
        elif group.group_type == "project":
            project_items.append(payload)
        elif group.group_type == "certification":
            certification_items.append(payload)

    canonical["identity"] = _normalize_identity(identity)
    if user is not None and not canonical["identity"].get("full_name"):
        canonical["identity"]["full_name"] = user.full_name
    canonical["work_experience"] = work_items
    canonical["education"] = education_items
    canonical["projects"] = project_items
    canonical["certifications"] = certification_items
    canonical["skills"] = _unique_strings(canonical["skills"])
    canonical["public_profiles"] = _unique_links(canonical["public_profiles"])
    canonical["source_documents"] = []
    canonical["auto_updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    return _normalize_overview_data(canonical)


def build_canonical_profile(
    profile: Profile,
    groups: list[ClaimGroup],
    user: User | None,
    documents: dict[str, Document],
) -> dict[str, Any]:
    canonical = _build_canonical_from_groups(profile, groups, user)
    headline_group = _identity_group_for_field(groups, "headline")
    summary_group = _identity_group_for_field(groups, "summary")
    headline_locked = bool(headline_group and dict(headline_group.group_metadata or {}).get("has_manual_edit"))
    summary_locked = bool(summary_group and dict(summary_group.group_metadata or {}).get("has_manual_edit"))
    current_role_group = _resolve_current_role_group(groups, documents)
    current_position = _headline_from_experience_payload(dict(current_role_group.canonical_value_json or {})) if current_role_group is not None else None

    profile_focus = _resolve_profile_focus(groups, documents, user)
    mode_summaries = _collect_mode_summaries(groups, documents, current_role_group)
    canonical["profile_focus"] = profile_focus
    canonical["profile_view"] = profile_focus
    canonical["available_views"] = ["master", "ai_ml", "web_dev", "full_stack", "ats_short"]
    canonical["mode_summaries"] = mode_summaries
    canonical["identity"]["current_position"] = current_position
    canonical["identity"]["target_headline"] = canonical["identity"].get("headline")
    if current_position and not headline_locked and not canonical["identity"].get("headline"):
        canonical["identity"]["headline"] = current_position
    if mode_summaries.get(profile_focus) and not summary_locked:
        canonical["identity"]["summary"] = mode_summaries[profile_focus]
    elif mode_summaries.get("master") and not canonical["identity"].get("summary") and not summary_locked:
        canonical["identity"]["summary"] = mode_summaries["master"]
    return _rebuild_source_documents(canonical, documents, groups)


def _rebuild_source_documents(canonical: dict[str, Any], documents: dict[str, Document], groups: list[ClaimGroup]) -> dict[str, Any]:
    grouped_signals: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        if group.status != "merged":
            continue
        signal = group.group_type
        for document_id in dict(group.group_metadata or {}).get("source_document_ids", []) or []:
            grouped_signals[document_id].add(signal)
    canonical["source_documents"] = [
        {
            "document_id": document_id,
            "filename": documents[document_id].filename,
            "created_at": documents[document_id].created_at.isoformat() if documents[document_id].created_at else None,
            "document_role": (documents[document_id].parse_metadata or {}).get("document_role"),
            "profile_focus": (documents[document_id].parse_metadata or {}).get("profile_focus"),
            "source_quality": (documents[document_id].parse_metadata or {}).get("source_quality"),
            "signals": sorted(signal.replace("_", " ") for signal in signals),
        }
        for document_id, signals in grouped_signals.items()
        if document_id in documents
    ]
    return _normalize_overview_data(canonical)


def _persist_fusion(session: Session, profile: Profile, groups: list[ClaimGroup], anomalies: list[ProfileAnomaly]) -> tuple[list[ClaimGroup], list[ProfileAnomaly]]:
    session.execute(delete(ProfileAnomaly).where(ProfileAnomaly.profile_id == profile.id))
    session.execute(delete(ClaimGroup).where(ClaimGroup.profile_id == profile.id))
    session.flush()
    for group in groups:
        session.add(group)
    session.flush()
    for anomaly in anomalies:
        if anomaly.claim_group is not None and anomaly.claim_group.id is not None:
            anomaly.claim_group_id = anomaly.claim_group.id
        session.add(anomaly)
    session.flush()
    stored_groups = list(
        session.scalars(
            select(ClaimGroup)
            .where(ClaimGroup.profile_id == profile.id)
            .order_by(ClaimGroup.status.asc(), ClaimGroup.group_type.asc(), ClaimGroup.canonical_value.asc())
        ).all()
    )
    stored_anomalies = list(
        session.scalars(
            select(ProfileAnomaly)
            .where(ProfileAnomaly.profile_id == profile.id)
            .order_by(ProfileAnomaly.severity.desc(), ProfileAnomaly.created_at.asc())
        ).all()
    )
    return stored_groups, stored_anomalies


def fuse_profile(
    session: Session,
    profile: Profile,
    user: User | None = None,
    *,
    view: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    raw_claims, documents = _build_fusion_claims(session, profile)
    normalized_claims = [normalize_claim(claim, user=user) for claim in raw_claims]
    clusters = cluster_claims(session, profile, normalized_claims, user=user, settings=settings)

    groups: list[ClaimGroup] = []
    anomalies: list[ProfileAnomaly] = []
    for cluster in clusters:
        cluster_groups, cluster_anomalies = merge_claim_group(session, profile, cluster, settings=settings)
        groups.extend(cluster_groups)
        anomalies.extend(cluster_anomalies)

    repo_link_groups = [group for group in groups if group.group_type == "ignored_public_profile"]
    _append_repo_links_to_projects([group for group in groups if group.group_type == "project"], repo_link_groups)
    groups, duplicate_anomalies = dedupe_claims(session, profile, groups, settings=settings)
    anomalies.extend(duplicate_anomalies)
    anomalies.extend(detect_anomalies(profile, groups))

    groups, anomalies = _persist_fusion(session, profile, groups, anomalies)
    master_profile = build_canonical_profile(profile, groups, user, documents)
    compiled_views = compile_profile_views(master_profile, groups, documents, user)
    resolved_view = _clean_text(view) or _clean_text(master_profile.get("profile_view")) or _clean_text(master_profile.get("profile_focus")) or "master"
    preview_profile = compiled_views.get(resolved_view) or compiled_views.get(_clean_text(master_profile.get("profile_focus")) or "master") or compiled_views["master"]

    merged_groups = [group for group in groups if group.status == "merged"]
    review_groups = [group for group in groups if group.status == "review"]
    ignored_groups = [group for group in groups if group.status == "ignored"]
    anomaly_map = {anomaly.claim_group_id: anomaly for anomaly in anomalies if anomaly.claim_group_id}
    critical_review_groups = [group for group in review_groups if _review_level(group, anomaly_map) == "critical"]
    optional_review_groups = [group for group in review_groups if _review_level(group, anomaly_map) != "critical"]
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "summary": {
            "merged_total": len(merged_groups),
            "review_total": len(review_groups),
            "critical_review_total": len(critical_review_groups),
            "optional_review_total": len(optional_review_groups),
            "ignored_total": len(ignored_groups),
            "anomaly_total": len(anomalies),
        },
        "merged_groups": [_serialize_group(group) for group in merged_groups],
        "review_groups": [_serialize_group(group) for group in review_groups],
        "critical_review_groups": [_serialize_group(group) for group in critical_review_groups],
        "optional_review_groups": [_serialize_group(group) for group in optional_review_groups],
        "ignored_groups": [_serialize_group(group) for group in ignored_groups],
        "anomalies": [_serialize_anomaly(anomaly) for anomaly in anomalies],
        "master_profile": {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "profile_mode": "review",
            "profile_focus": master_profile.get("profile_focus"),
            "profile_view": master_profile.get("profile_view"),
            "available_views": list(master_profile.get("available_views") or compiled_views.keys()),
            "identity": master_profile["identity"],
            "skills": master_profile["skills"],
            "public_profiles": master_profile["public_profiles"],
            "education": master_profile["education"],
            "work_experience": master_profile["work_experience"],
            "projects": master_profile["projects"],
            "certifications": master_profile["certifications"],
            "mode_summaries": master_profile.get("mode_summaries", {}),
            "source_documents": master_profile["source_documents"],
            "documents_total": len(master_profile["source_documents"]),
            "auto_updated_at": master_profile["auto_updated_at"],
            "updated_at": profile.updated_at,
        },
        "compiled_views": {
            key: {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "profile_mode": "review",
                "profile_focus": value.get("profile_focus"),
                "profile_view": value.get("profile_view"),
                "available_views": list(value.get("available_views") or compiled_views.keys()),
                "identity": value["identity"],
                "skills": value["skills"],
                "public_profiles": value["public_profiles"],
                "education": value["education"],
                "work_experience": value["work_experience"],
                "projects": value["projects"],
                "certifications": value["certifications"],
                "mode_summaries": value.get("mode_summaries", {}),
                "source_documents": value["source_documents"],
                "documents_total": len(value["source_documents"]),
                "auto_updated_at": value["auto_updated_at"],
                "updated_at": profile.updated_at,
            }
            for key, value in compiled_views.items()
        },
        "preview_profile": {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "profile_mode": "review",
            "profile_focus": preview_profile.get("profile_focus"),
            "profile_view": preview_profile.get("profile_view"),
            "available_views": list(preview_profile.get("available_views") or compiled_views.keys()),
            "identity": preview_profile["identity"],
            "skills": preview_profile["skills"],
            "public_profiles": preview_profile["public_profiles"],
            "education": preview_profile["education"],
            "work_experience": preview_profile["work_experience"],
            "projects": preview_profile["projects"],
            "certifications": preview_profile["certifications"],
            "mode_summaries": preview_profile.get("mode_summaries", {}),
            "source_documents": preview_profile["source_documents"],
            "documents_total": len(preview_profile["source_documents"]),
            "auto_updated_at": preview_profile["auto_updated_at"],
            "updated_at": profile.updated_at,
        },
    }


def save_fused_canonical_profile(
    session: Session,
    profile: Profile,
    user: User | None = None,
    *,
    view: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    fusion = fuse_profile(session, profile, user, view=view, settings=settings)
    container = _normalize_profile_container(profile.profile_data)
    canonical = _normalize_overview_data(dict(fusion["master_profile"]))
    container["canonical"] = canonical
    container["compiled_views"] = {
        key: _normalize_overview_data(dict(payload))
        for key, payload in dict(fusion.get("compiled_views") or {}).items()
    }
    sync_canonical_values_from_overview(session, profile, canonical)
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.flush()
    compiled = _normalize_overview_data(dict(fusion["preview_profile"]))
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "profile_mode": "canonical",
        "profile_focus": compiled.get("profile_focus"),
        "profile_view": compiled.get("profile_view"),
        "available_views": list(compiled.get("available_views") or container["compiled_views"].keys()),
        "identity": compiled["identity"],
        "skills": compiled["skills"],
        "public_profiles": compiled["public_profiles"],
        "education": compiled["education"],
        "work_experience": compiled["work_experience"],
        "projects": compiled["projects"],
        "certifications": compiled["certifications"],
        "mode_summaries": compiled.get("mode_summaries", {}),
        "source_documents": compiled["source_documents"],
        "documents_total": len(compiled["source_documents"]),
        "auto_updated_at": compiled["auto_updated_at"],
        "updated_at": profile.updated_at,
    }
