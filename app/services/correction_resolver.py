from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from openai import OpenAI
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.embeddings import cosine_similarity, correction_embedding_available, ensure_correction_embeddings
from app.models import CanonicalValue, CorrectionRule, Profile, StructuredProfileClaim

try:
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover - optional runtime dependency
    fuzz = None
    process = None

try:
    import phonenumbers
except Exception:  # pragma: no cover - optional runtime dependency
    phonenumbers = None

try:
    import spacy
    from spacy.language import Language
except Exception:  # pragma: no cover - optional runtime dependency
    spacy = None
    Language = Any  # type: ignore[assignment]


LOWER_WORD_PATTERN = re.compile(r"[^a-z0-9+#./ -]+")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
URL_PATTERN = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+")
LOCATION_WORDS = {
    "india",
    "bengaluru",
    "bangalore",
    "mumbai",
    "pune",
    "hyderabad",
    "delhi",
    "remote",
    "hybrid",
}
PROJECT_HINTS = {
    "project",
    "pipeline",
    "github",
    "demo",
    "portfolio",
    "platform",
    "application",
    "tool",
    "system",
    "agent",
}
ROLE_HINTS = {
    "engineer",
    "developer",
    "analyst",
    "scientist",
    "architect",
    "manager",
    "intern",
    "consultant",
    "freelance",
    "freelancing",
}
ROLE_WORD_PATTERN = re.compile(r"\b(" + "|".join(sorted(ROLE_HINTS)) + r")\b", re.IGNORECASE)
SAFE_AUTO_FIELD_TYPES = {"email", "phone", "url", "skill", "degree", "company"}
ARBITER_FIELD_TYPES = {"skill", "company", "role", "degree"}

SKILL_ALIASES = {
    "FastAPI": ["fast api", "fastapi"],
    "PostgreSQL": ["postgres", "postgre sql", "pgsql", "postgresql"],
    "JavaScript": ["javascript", "js"],
    "Node.js": ["node", "nodejs", "node js"],
    "Kubernetes": ["k8s", "kube", "kubernetes"],
    "TypeScript": ["typescript", "ts"],
    "Machine Learning": ["machine learning", "ml"],
    "Document AI": ["document ai", "document intelligence"],
    "OCR": ["ocr", "optical character recognition"],
    "Redis": ["redis"],
    "Docker": ["docker"],
    "Python": ["python", "py"],
    "RAG": ["rag", "retrieval augmented generation"],
    "LayoutLMv3": ["layoutlmv3", "layoutlm v3"],
}

ROLE_ALIASES = {
    "AI/ML Developer": ["ai ml developer", "ai/ml developer", "ml dev", "ai developer"],
    "Machine Learning Developer": ["machine learning developer", "ml developer"],
    "Document AI Engineer": ["document ai engineer", "document intelligence engineer"],
    "Backend Engineer": ["backend engineer", "backend developer"],
}

DEGREE_ALIASES = {
    "B.Tech in Computer Engineering": [
        "btech comp engg",
        "b tech comp engg",
        "btech computer engineering",
        "b.tech computer engineering",
        "b.tech in computer engineering",
    ],
    "B.E. Computer Engineering": [
        "be computer",
        "b.e computer",
        "be computer engineering",
        "b.e computer engineering",
    ],
    "Bachelor of Technology in Computer Science": [
        "bachelor of technology in computer science",
        "btech computer science",
        "b.tech computer science",
    ],
}


@dataclass
class ResolverCandidate:
    value: str
    source: str
    alias_score: float = 0.0
    fuzzy_score: float = 0.0
    embedding_score: float = 0.0
    graph_score: float = 0.0
    section_context_score: float = 0.0
    final_score: float = 0.0
    evidence: list[str] = field(default_factory=list)


@dataclass
class ResolverDecision:
    corrected_value_json: dict[str, Any]
    corrected_section: str | None = None
    resolver_action: str = "keep"
    resolver_confidence: float = 0.0
    resolver_evidence: list[str] = field(default_factory=list)
    status_override: str | None = None


@dataclass
class ArbiterChoice:
    decision: str
    action: str
    confidence: float
    reason_code: str


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", LOWER_WORD_PATTERN.sub(" ", value.lower())).strip()


def _normalize_url(value: str) -> str:
    cleaned = value.strip().rstrip(".,);")
    if cleaned and cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"
    return cleaned


def _canonical_url(value: str) -> str:
    url = _normalize_url(value)
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _smart_title(value: str) -> str:
    words = [word for word in re.split(r"\s+", value.strip()) if word]
    return " ".join(word.upper() if word.isupper() else word[:1].upper() + word[1:] for word in words)


def _looks_like_skill_value(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 40:
        return False
    if EMAIL_PATTERN.search(cleaned) or URL_PATTERN.search(cleaned):
        return False
    tokens = [token for token in re.split(r"[\s,/|+-]+", cleaned) if token]
    if not 1 <= len(tokens) <= 4:
        return False
    if any(len(token) > 20 for token in tokens):
        return False
    if sum(character.isalpha() for character in cleaned) < 2:
        return False
    return True


def _entity_ruler() -> Language | None:
    if spacy is None:
        return None
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    patterns = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in {canonical, *aliases}:
            patterns.append({"label": canonical, "pattern": alias})
    ruler.add_patterns(patterns)
    return nlp


def _existing_canonical_values(session: Session, profile: Profile, value_type: str) -> list[CanonicalValue]:
    return list(
        session.scalars(
            select(CanonicalValue)
            .where(CanonicalValue.profile_id == profile.id, CanonicalValue.value_type == value_type)
            .order_by(CanonicalValue.confidence.desc(), CanonicalValue.canonical_value.asc())
        ).all()
    )


def _existing_rules(session: Session, profile: Profile, field_type: str) -> list[CorrectionRule]:
    return list(
        session.scalars(
            select(CorrectionRule)
            .where(CorrectionRule.profile_id == profile.id, CorrectionRule.field_type == field_type)
            .order_by(CorrectionRule.confidence.desc(), CorrectionRule.created_at.desc())
        ).all()
    )


def correction_arbiter_available(settings: Settings | None) -> bool:
    if not settings or not settings.enable_correction_llm_arbiter:
        return False
    provider = (settings.correction_arbiter_provider or "openai").lower()
    if provider == "ollama":
        return bool(settings.ollama_arbiter_model)
    return bool(settings.openai_api_key)


def _arbiter_client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _rapidfuzz_best(query: str, choices: list[str]) -> tuple[str | None, float]:
    if not query or not choices or process is None or fuzz is None:
        return None, 0.0
    result = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if not result:
        return None, 0.0
    value, score, _index = result
    return str(value), float(score) / 100.0


def _score_candidate(
    *,
    parser_confidence: float,
    alias_score: float,
    fuzzy_score: float,
    embedding_score: float,
    graph_score: float,
    section_context_score: float,
    conflict_penalty: float = 0.0,
) -> float:
    score = (
        0.25 * parser_confidence
        + 0.25 * alias_score
        + 0.20 * fuzzy_score
        + 0.15 * embedding_score
        + 0.10 * graph_score
        + 0.05 * section_context_score
        - conflict_penalty
    )
    return round(max(0.0, min(1.0, score)), 4)


def _rule_candidate(raw_value: str, rules: list[CorrectionRule]) -> ResolverCandidate | None:
    normalized_raw = _normalize_lookup(raw_value)
    for rule in rules:
        if _normalize_lookup(rule.pattern) == normalized_raw and rule.target_value:
            evidence = [f"rule:{rule.action}"]
            return ResolverCandidate(
                value=rule.target_value,
                source="correction_rule",
                alias_score=min(1.0, float(rule.confidence)),
                graph_score=min(1.0, float(rule.confidence)),
                evidence=evidence,
            )
    return None


def _canonical_candidates(
    raw_value: str,
    canonical_values: list[CanonicalValue],
    *,
    section_context_score: float,
) -> list[ResolverCandidate]:
    normalized_raw = _normalize_lookup(raw_value)
    candidates: list[ResolverCandidate] = []
    choice_strings = [item.canonical_value for item in canonical_values]
    fuzzy_value, fuzzy_score = _rapidfuzz_best(normalized_raw, [_normalize_lookup(choice) for choice in choice_strings])

    canonical_by_lookup = {_normalize_lookup(item.canonical_value): item for item in canonical_values}
    if fuzzy_value and fuzzy_value in canonical_by_lookup:
        matched = canonical_by_lookup[fuzzy_value]
        candidates.append(
            ResolverCandidate(
                value=matched.canonical_value,
                source="canonical_fuzzy",
                fuzzy_score=fuzzy_score,
                graph_score=min(1.0, matched.confidence),
                section_context_score=section_context_score,
                evidence=["canonical_fuzzy_match"],
            )
        )

    for item in canonical_values:
        aliases = {_normalize_lookup(alias) for alias in item.aliases_json or []}
        if normalized_raw in aliases or normalized_raw == _normalize_lookup(item.canonical_value):
            candidates.append(
                ResolverCandidate(
                    value=item.canonical_value,
                    source="canonical_alias",
                    alias_score=1.0,
                    fuzzy_score=1.0,
                    graph_score=min(1.0, item.confidence),
                    section_context_score=section_context_score,
                    evidence=["canonical_alias_match"],
                )
            )
    return candidates


def _builtin_alias_candidates(
    raw_value: str,
    alias_map: dict[str, list[str]],
    *,
    section_context_score: float,
) -> list[ResolverCandidate]:
    normalized_raw = _normalize_lookup(raw_value)
    choices = list(alias_map.keys())
    candidates: list[ResolverCandidate] = []

    for canonical, aliases in alias_map.items():
        alias_set = {_normalize_lookup(alias) for alias in aliases}
        if normalized_raw == _normalize_lookup(canonical) or normalized_raw in alias_set:
            candidates.append(
                ResolverCandidate(
                    value=canonical,
                    source="builtin_alias",
                    alias_score=1.0,
                    fuzzy_score=1.0,
                    graph_score=0.95,
                    section_context_score=section_context_score,
                    evidence=["builtin_alias_match", "exact_lookup_match"],
                )
            )
    fuzzy_value, fuzzy_score = _rapidfuzz_best(
        normalized_raw,
        [_normalize_lookup(choice) for choice in [*choices, *(alias for aliases in alias_map.values() for alias in aliases)]],
    )
    if fuzzy_value and fuzzy_score >= 0.82:
        for canonical, aliases in alias_map.items():
            lookup_choices = {_normalize_lookup(canonical), *(_normalize_lookup(alias) for alias in aliases)}
            if fuzzy_value in lookup_choices:
                candidates.append(
                    ResolverCandidate(
                        value=canonical,
                        source="builtin_fuzzy",
                        fuzzy_score=fuzzy_score,
                        section_context_score=section_context_score,
                        evidence=["builtin_fuzzy_match"],
                    )
                )
                break
    return candidates


def _merge_candidates(candidates: list[ResolverCandidate]) -> list[ResolverCandidate]:
    merged: dict[str, ResolverCandidate] = {}
    for candidate in candidates:
        key = _normalize_lookup(candidate.value)
        if key not in merged:
            merged[key] = ResolverCandidate(
                value=candidate.value,
                source=candidate.source,
                alias_score=candidate.alias_score,
                fuzzy_score=candidate.fuzzy_score,
                embedding_score=candidate.embedding_score,
                graph_score=candidate.graph_score,
                section_context_score=candidate.section_context_score,
                final_score=candidate.final_score,
                evidence=list(candidate.evidence),
            )
            continue
        existing = merged[key]
        existing.alias_score = max(existing.alias_score, candidate.alias_score)
        existing.fuzzy_score = max(existing.fuzzy_score, candidate.fuzzy_score)
        existing.embedding_score = max(existing.embedding_score, candidate.embedding_score)
        existing.graph_score = max(existing.graph_score, candidate.graph_score)
        existing.section_context_score = max(existing.section_context_score, candidate.section_context_score)
        existing.evidence = list(dict.fromkeys([*existing.evidence, *candidate.evidence]))
        if candidate.source not in existing.source.split(","):
            existing.source = ",".join([part for part in [existing.source, candidate.source] if part])
    return list(merged.values())


def _semantic_candidate_lookup(
    session: Session,
    profile: Profile,
    raw_value: str,
    *,
    field_type: str,
    section: str,
    source_text: str | None,
    candidates: list[ResolverCandidate],
    settings: Settings | None,
) -> list[ResolverCandidate]:
    if not candidates or settings is None or not correction_embedding_available(settings):
        return candidates
    if len(candidates) < 2 or not raw_value.strip():
        return candidates

    query_text = " | ".join(
        part
        for part in (
            f"field:{field_type}",
            f"section:{section}",
            f"raw:{raw_value}",
            source_text or "",
        )
        if part
    )
    try:
        vectors, cache_stats = ensure_correction_embeddings(
            session,
            profile_id=profile.id,
            texts=[query_text, *[candidate.value for candidate in candidates]],
            settings=settings,
            embedding_kind=f"resolver:{field_type}",
        )
    except Exception:
        return candidates

    if len(vectors) != len(candidates) + 1:
        return candidates

    query_vector = vectors[0]
    for candidate, vector in zip(candidates, vectors[1:], strict=True):
        similarity = (cosine_similarity(query_vector, vector) + 1.0) / 2.0
        candidate.embedding_score = max(candidate.embedding_score, max(0.0, min(1.0, similarity)))
        if candidate.embedding_score >= 0.58:
            candidate.evidence = list(dict.fromkeys([*candidate.evidence, "embedding_similarity"]))
        if cache_stats["hits"] > 0:
            candidate.evidence = list(dict.fromkeys([*candidate.evidence, "embedding_cache_hit"]))
        if cache_stats["misses"] > 0:
            candidate.evidence = list(dict.fromkeys([*candidate.evidence, "embedding_cache_miss"]))
    return candidates


def _rank_candidates(raw_value: str, candidates: list[ResolverCandidate], *, parser_confidence: float) -> list[ResolverCandidate]:
    if not candidates:
        return []
    normalized_raw = _normalize_lookup(raw_value)
    ranked: list[ResolverCandidate] = []
    for candidate in _merge_candidates(candidates):
        conflict_penalty = 0.0
        if _normalize_lookup(candidate.value) == normalized_raw:
            conflict_penalty = 0.05 if candidate.alias_score == 0.0 and candidate.fuzzy_score < 0.9 else 0.0
        candidate.final_score = _score_candidate(
            parser_confidence=parser_confidence,
            alias_score=candidate.alias_score,
            fuzzy_score=candidate.fuzzy_score,
            embedding_score=candidate.embedding_score,
            graph_score=candidate.graph_score,
            section_context_score=candidate.section_context_score,
            conflict_penalty=conflict_penalty,
        )
        ranked.append(candidate)
    ranked.sort(key=lambda candidate: candidate.final_score, reverse=True)
    return ranked


def _should_use_arbiter(field_type: str, ranked_candidates: list[ResolverCandidate], settings: Settings | None) -> bool:
    if field_type not in ARBITER_FIELD_TYPES or not correction_arbiter_available(settings):
        return False
    if len(ranked_candidates) < 2:
        return False
    best = ranked_candidates[0]
    second = ranked_candidates[1]
    assert settings is not None
    if best.alias_score >= 0.99 and best.fuzzy_score >= 0.99:
        return False
    if not (settings.correction_arbiter_min_score <= best.final_score <= settings.correction_arbiter_max_score):
        return False
    return abs(best.final_score - second.final_score) <= settings.correction_arbiter_margin


def _call_llm_arbiter(
    *,
    raw_value: str,
    field_type: str,
    section: str,
    source_text: str | None,
    ranked_candidates: list[ResolverCandidate],
    parser_confidence: float,
    settings: Settings | None,
) -> ArbiterChoice | None:
    if not correction_arbiter_available(settings):
        return None
    assert settings is not None
    allowed_candidates = ranked_candidates[: settings.correction_arbiter_candidate_limit]
    allowed_values = [candidate.value for candidate in allowed_candidates]
    request_payload = {
        "claim": {
            "field_type": field_type,
            "raw_value": raw_value,
            "section": section,
            "source_text": source_text or "",
            "parser_confidence": parser_confidence,
        },
        "candidates": [
            {
                "value": candidate.value,
                "score": candidate.final_score,
                "evidence": candidate.evidence,
            }
            for candidate in allowed_candidates
        ],
        "allowed_decisions": [*allowed_values, "NO_CORRECTION"],
        "allowed_actions": ["auto_correct", "suggest", "keep", "needs_review"],
    }
    response_content: str | None = None
    provider = (settings.correction_arbiter_provider or "openai").lower()

    if provider == "ollama":
        schema = {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": [*allowed_values, "NO_CORRECTION"]},
                "action": {"type": "string", "enum": ["auto_correct", "suggest", "keep", "needs_review"]},
                "confidence": {"type": "number"},
                "reason_code": {"type": "string"},
            },
            "required": ["decision", "action", "confidence", "reason_code"],
            "additionalProperties": False,
        }
        prompt = (
            "Choose only from the candidate values or NO_CORRECTION. "
            "Return JSON only.\n"
            f"{json.dumps(request_payload, ensure_ascii=True)}"
        )
        body = json.dumps(
            {
                "model": settings.ollama_arbiter_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        try:
            request = urllib_request.Request(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                response_content = payload.get("response")
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError):
            return None
    else:
        try:
            response = _arbiter_client(settings).chat.completions.create(
                model=settings.correction_arbiter_model or settings.openai_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a correction arbiter. Choose only from the provided candidates or NO_CORRECTION. "
                            "Never invent a value. Return valid JSON with keys decision, action, confidence, reason_code."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(request_payload),
                    },
                ],
            )
            response_content = response.choices[0].message.content if response.choices else None
        except Exception:
            return None

    if not response_content:
        return None
    try:
        payload = json.loads(response_content)
    except json.JSONDecodeError:
        return None

    decision = str(payload.get("decision") or "").strip()
    action = str(payload.get("action") or "needs_review").strip().lower()
    if decision not in {*allowed_values, "NO_CORRECTION"}:
        return None
    if action not in {"auto_correct", "suggest", "keep", "needs_review"}:
        action = "needs_review"
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    reason_code = str(payload.get("reason_code") or "candidate_selection").strip() or "candidate_selection"
    return ArbiterChoice(
        decision=decision,
        action=action,
        confidence=max(0.0, min(1.0, confidence)),
        reason_code=reason_code,
    )


def _resolved_candidate(
    session: Session,
    profile: Profile,
    raw_value: str,
    *,
    field_type: str,
    section: str,
    source_text: str | None,
    parser_confidence: float,
    candidates: list[ResolverCandidate],
    settings: Settings | None,
) -> tuple[ResolverCandidate | None, float, str | None, list[str]]:
    ranked = _rank_candidates(
        raw_value,
        _semantic_candidate_lookup(
            session,
            profile,
            raw_value,
            field_type=field_type,
            section=section,
            source_text=source_text,
            candidates=candidates,
            settings=settings,
        ),
        parser_confidence=parser_confidence,
    )
    if not ranked:
        return None, parser_confidence, None, []

    best = ranked[0]
    evidence = list(best.evidence)
    action_override: str | None = None
    score = best.final_score
    if _should_use_arbiter(field_type, ranked, settings):
        arbiter = _call_llm_arbiter(
            raw_value=raw_value,
            field_type=field_type,
            section=section,
            source_text=source_text,
            ranked_candidates=ranked,
            parser_confidence=parser_confidence,
            settings=settings,
        )
        if arbiter is not None:
            evidence = list(dict.fromkeys([*evidence, f"llm_arbiter:{arbiter.reason_code}"]))
            action_override = arbiter.action
            score = max(score, arbiter.confidence)
            if arbiter.decision == "NO_CORRECTION":
                return None, max(parser_confidence, arbiter.confidence), action_override, evidence
            for candidate in ranked:
                if candidate.value == arbiter.decision:
                    best = candidate
                    evidence = list(dict.fromkeys([*candidate.evidence, f"llm_arbiter:{arbiter.reason_code}"]))
                    score = max(candidate.final_score, arbiter.confidence)
                    break

    return best, score, action_override, evidence


def _safe_auto_action(field_type: str, score: float, exact_or_alias: bool) -> str:
    if field_type == "skill":
        if score >= 0.78 or (exact_or_alias and score >= 0.68):
            return "auto_correct"
        if score >= 0.52:
            return "suggest"
        return "needs_review"
    if field_type in SAFE_AUTO_FIELD_TYPES and (score >= 0.84 or (exact_or_alias and score >= 0.76)):
        return "auto_correct"
    if score >= 0.62:
        return "suggest"
    return "needs_review"


def _contact_decision(raw_value_json: dict[str, Any], field_type: str) -> ResolverDecision:
    if field_type == "email":
        raw_value = str(raw_value_json.get("value") or "").strip()
        corrected = raw_value.lower()
        if corrected and EMAIL_PATTERN.fullmatch(corrected):
            return ResolverDecision(
                corrected_value_json={"value": corrected},
                resolver_action="auto_correct" if corrected != raw_value else "keep",
                resolver_confidence=0.99,
                resolver_evidence=["email_regex", "deterministic_normalization"],
            )
        return ResolverDecision(corrected_value_json=raw_value_json, resolver_action="needs_review", resolver_confidence=0.42)

    if field_type == "url":
        raw_value = str(raw_value_json.get("url") or "").strip()
        corrected = _normalize_url(raw_value)
        label = raw_value_json.get("label") or "Link"
        parsed = urlparse(corrected if "://" in corrected else f"https://{corrected}")
        if parsed.netloc:
            host = parsed.netloc.lower().removeprefix("www.")
            if "github.com" in host:
                label = "GitHub"
            elif "linkedin.com" in host:
                label = "LinkedIn"
            elif "huggingface.co" in host:
                label = "Hugging Face"
            return ResolverDecision(
                corrected_value_json={"label": label, "url": corrected},
                resolver_action="auto_correct" if corrected != raw_value or label != raw_value_json.get("label") else "keep",
                resolver_confidence=0.98,
                resolver_evidence=["url_parser", "contact_section"],
            )
        return ResolverDecision(corrected_value_json=raw_value_json, resolver_action="needs_review", resolver_confidence=0.35)

    if field_type == "phone":
        raw_value = str(raw_value_json.get("value") or "").strip()
        if phonenumbers is not None:
            try:
                parsed = phonenumbers.parse(raw_value, "IN")
                if phonenumbers.is_valid_number(parsed):
                    corrected = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                    return ResolverDecision(
                        corrected_value_json={"value": corrected},
                        resolver_action="auto_correct" if corrected != raw_value else "keep",
                        resolver_confidence=0.97,
                        resolver_evidence=["phonenumbers", "contact_section"],
                    )
            except Exception:
                pass
        digits = re.sub(r"\D+", "", raw_value)
        if len(digits) >= 10:
            corrected = f"+{digits}" if raw_value.startswith("+") else digits
            return ResolverDecision(
                corrected_value_json={"value": corrected},
                resolver_action="suggest",
                resolver_confidence=0.78,
                resolver_evidence=["digit_normalization"],
            )
        return ResolverDecision(corrected_value_json=raw_value_json, resolver_action="needs_review", resolver_confidence=0.25)

    if field_type == "location":
        raw_value = str(raw_value_json.get("value") or "").strip()
        corrected = _smart_title(raw_value)
        confidence = 0.84 if any(token in _normalize_lookup(corrected) for token in LOCATION_WORDS) else 0.58
        action = "auto_correct" if confidence >= 0.9 and corrected != raw_value else "suggest" if corrected != raw_value else "keep"
        return ResolverDecision(
            corrected_value_json={"value": corrected},
            resolver_action=action,
            resolver_confidence=confidence,
            resolver_evidence=["location_case_normalization"],
        )

    return ResolverDecision(corrected_value_json=raw_value_json, resolver_action="keep", resolver_confidence=0.4)


def _skill_decision(
    session: Session,
    profile: Profile,
    raw_value_json: dict[str, Any],
    parser_confidence: float,
    *,
    source_text: str | None = None,
    settings: Settings | None = None,
) -> ResolverDecision:
    raw_value = str(raw_value_json.get("name") or "").strip()
    section_context_score = 1.0
    candidates = _builtin_alias_candidates(raw_value, SKILL_ALIASES, section_context_score=section_context_score)
    candidates.extend(_canonical_candidates(raw_value, _existing_canonical_values(session, profile, "skill"), section_context_score=section_context_score))
    rule_candidate = _rule_candidate(raw_value, _existing_rules(session, profile, "skill"))
    if rule_candidate:
        candidates.append(rule_candidate)

    nlp = _entity_ruler()
    if nlp is not None and raw_value:
        doc = nlp(f"{raw_value} {raw_value_json.get('source_text', '')}")
        for ent in doc.ents:
            if ent.label_:
                candidates.append(
                    ResolverCandidate(
                        value=ent.label_,
                        source="entity_ruler",
                        alias_score=0.92,
                        section_context_score=section_context_score,
                        evidence=["spacy_entity_ruler"],
                    )
                )

    best, score, action_override, evidence = _resolved_candidate(
        session,
        profile,
        raw_value,
        field_type="skill",
        section="skills",
        source_text=source_text,
        parser_confidence=parser_confidence,
        candidates=candidates,
        settings=settings,
    )
    if best is None:
        if _looks_like_skill_value(raw_value):
            fallback_confidence = max(parser_confidence, 0.68 if parser_confidence >= 0.48 else 0.56)
            fallback_action = "keep" if parser_confidence >= 0.48 else "suggest"
            return ResolverDecision(
                corrected_value_json={"name": raw_value},
                resolver_action=fallback_action,
                resolver_confidence=fallback_confidence,
                resolver_evidence=["skills_section", "parser_extracted_skill"],
            )
        action = action_override if action_override in {"keep", "needs_review"} else "needs_review"
        return ResolverDecision(corrected_value_json=raw_value_json, resolver_action=action, resolver_confidence=score)

    if (
        _looks_like_skill_value(raw_value)
        and _normalize_lookup(best.value) != _normalize_lookup(raw_value)
        and best.alias_score < 0.9
        and best.embedding_score < 0.72
        and score < 0.78
    ):
        fallback_confidence = max(parser_confidence, 0.66 if parser_confidence >= 0.48 else 0.54)
        fallback_action = "keep" if parser_confidence >= 0.48 else "suggest"
        return ResolverDecision(
            corrected_value_json={"name": raw_value},
            resolver_action=fallback_action,
            resolver_confidence=fallback_confidence,
            resolver_evidence=["skills_section", "weak_candidate_rejected", "parser_extracted_skill"],
        )

    action = action_override or _safe_auto_action("skill", score, best.alias_score >= 0.95)
    corrected = {"name": best.value}
    if _normalize_lookup(best.value) == _normalize_lookup(raw_value):
        action = "keep" if raw_value == best.value else "auto_correct"
    status_override = "duplicate" if action == "duplicate" else None
    return ResolverDecision(
        corrected_value_json=corrected,
        resolver_action=action,
        resolver_confidence=score,
        resolver_evidence=evidence or best.evidence or [best.source],
        status_override=status_override,
    )


def _company_or_role_candidates(session: Session, profile: Profile, field_type: str) -> list[CanonicalValue]:
    return _existing_canonical_values(session, profile, field_type)


def _company_decision(
    session: Session,
    profile: Profile,
    raw_value: str,
    parser_confidence: float,
    *,
    source_text: str | None = None,
    settings: Settings | None = None,
) -> ResolverDecision:
    candidates = _canonical_candidates(raw_value, _company_or_role_candidates(session, profile, "company"), section_context_score=0.92)
    rule_candidate = _rule_candidate(raw_value, _existing_rules(session, profile, "company"))
    if rule_candidate:
        candidates.append(rule_candidate)
    best, score, action_override, evidence = _resolved_candidate(
        session,
        profile,
        raw_value,
        field_type="company",
        section="work_experience",
        source_text=source_text,
        parser_confidence=parser_confidence,
        candidates=candidates,
        settings=settings,
    )
    if best is None:
        action = action_override if action_override in {"keep", "needs_review"} else "keep"
        return ResolverDecision(corrected_value_json={"value": raw_value}, resolver_action=action, resolver_confidence=parser_confidence)
    action = action_override or _safe_auto_action("company", score, best.alias_score >= 0.95)
    return ResolverDecision(
        corrected_value_json={"value": best.value},
        resolver_action=action,
        resolver_confidence=score,
        resolver_evidence=evidence or best.evidence or [best.source],
    )


def _role_decision(
    session: Session,
    profile: Profile,
    raw_value: str,
    parser_confidence: float,
    *,
    source_text: str | None = None,
    settings: Settings | None = None,
) -> ResolverDecision:
    candidates = _builtin_alias_candidates(raw_value, ROLE_ALIASES, section_context_score=0.88)
    candidates.extend(_canonical_candidates(raw_value, _company_or_role_candidates(session, profile, "role"), section_context_score=0.88))
    rule_candidate = _rule_candidate(raw_value, _existing_rules(session, profile, "role"))
    if rule_candidate:
        candidates.append(rule_candidate)
    best, score, action_override, evidence = _resolved_candidate(
        session,
        profile,
        raw_value,
        field_type="role",
        section="work_experience",
        source_text=source_text,
        parser_confidence=parser_confidence,
        candidates=candidates,
        settings=settings,
    )
    if best is None:
        action = action_override if action_override in {"keep", "needs_review"} else "keep"
        return ResolverDecision(corrected_value_json={"value": raw_value}, resolver_action=action, resolver_confidence=parser_confidence)
    exact_title_match = (
        best.source in {"builtin_alias", "canonical_alias"}
        or any(reason in {"exact_lookup_match", "canonical_alias_match", "builtin_alias_match"} for reason in (evidence or best.evidence or []))
    )
    raw_title_is_specific = bool(ROLE_WORD_PATTERN.search(raw_value)) and len(_normalize_lookup(raw_value).split()) >= 2
    candidate_changes_title = _normalize_lookup(best.value) != _normalize_lookup(raw_value)
    if raw_title_is_specific and candidate_changes_title and not exact_title_match:
        keep_confidence = max(parser_confidence, 0.82 if parser_confidence >= 0.55 else 0.68)
        return ResolverDecision(
            corrected_value_json={"value": raw_value},
            resolver_action="keep",
            resolver_confidence=keep_confidence,
            resolver_evidence=["parser_specific_role", "weak_role_candidate_rejected"],
        )
    action = action_override or ("auto_correct" if score >= 0.96 and exact_title_match else "suggest" if score >= 0.74 else "needs_review")
    return ResolverDecision(
        corrected_value_json={"value": best.value},
        resolver_action=action,
        resolver_confidence=score,
        resolver_evidence=evidence or best.evidence or [best.source],
    )


def _degree_decision(
    session: Session,
    profile: Profile,
    raw_value: str,
    parser_confidence: float,
    *,
    source_text: str | None = None,
    settings: Settings | None = None,
) -> ResolverDecision:
    candidates = _builtin_alias_candidates(raw_value, DEGREE_ALIASES, section_context_score=0.95)
    candidates.extend(_canonical_candidates(raw_value, _existing_canonical_values(session, profile, "degree"), section_context_score=0.95))
    rule_candidate = _rule_candidate(raw_value, _existing_rules(session, profile, "degree"))
    if rule_candidate:
        candidates.append(rule_candidate)
    best, score, action_override, evidence = _resolved_candidate(
        session,
        profile,
        raw_value,
        field_type="degree",
        section="education",
        source_text=source_text,
        parser_confidence=parser_confidence,
        candidates=candidates,
        settings=settings,
    )
    if best is None:
        action = action_override if action_override in {"keep", "needs_review"} else "keep"
        return ResolverDecision(corrected_value_json={"value": raw_value}, resolver_action=action, resolver_confidence=parser_confidence)
    exact_degree_match = (
        best.alias_score >= 0.95
        or best.source in {"builtin_alias", "canonical_alias", "correction_rule"}
        or any(reason in {"exact_lookup_match", "canonical_alias_match", "builtin_alias_match"} for reason in (evidence or best.evidence or []))
    )
    fuzzy_only_degree_match = best.source in {"builtin_fuzzy", "canonical_fuzzy"} and not exact_degree_match
    action = action_override or _safe_auto_action("degree", score, exact_degree_match)
    corrected_value = best.value
    if fuzzy_only_degree_match:
        action = "needs_review"
        corrected_value = raw_value
    return ResolverDecision(
        corrected_value_json={"value": corrected_value},
        resolver_action=action,
        resolver_confidence=score,
        resolver_evidence=evidence or best.evidence or [best.source],
    )


def _section_move_suggestion(section: str, value_json: dict[str, Any]) -> tuple[str | None, list[str], float]:
    if section == "work_experience":
        text = " ".join(
            str(part or "")
            for part in (
                value_json.get("title"),
                value_json.get("organization"),
                value_json.get("summary"),
                " ".join(value_json.get("highlights", [])),
                " ".join(value_json.get("links", [])),
            )
        ).lower()
        if not value_json.get("start_date") and any(hint in text for hint in PROJECT_HINTS):
            return "projects", ["project_like_experience_item"], 0.81
    if section == "projects":
        text = " ".join(
            str(part or "")
            for part in (
                value_json.get("name"),
                value_json.get("summary"),
            )
        ).lower()
        if any(hint in text for hint in ROLE_HINTS) and value_json.get("start_date"):
            return "work_experience", ["experience_like_project_item"], 0.78
    return None, [], 0.0


def _resolve_entry_claim(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    settings: Settings | None = None,
) -> ResolverDecision:
    value_json = dict(claim.raw_value_json or claim.value_json or {})
    evidence: list[str] = []
    resolver_action = "keep"
    resolver_confidence = claim.confidence
    suggested_section = None

    if claim.section == "work_experience":
        if value_json.get("organization"):
            company = _company_decision(
                session,
                profile,
                str(value_json["organization"]),
                claim.confidence,
                source_text=claim.source_text,
                settings=settings,
            )
            value_json["organization"] = company.corrected_value_json.get("value", value_json["organization"])
            evidence.extend(company.resolver_evidence)
            resolver_confidence = max(resolver_confidence, company.resolver_confidence)
            resolver_action = company.resolver_action if company.resolver_action != "keep" else resolver_action
        if value_json.get("title"):
            role = _role_decision(
                session,
                profile,
                str(value_json["title"]),
                claim.confidence,
                source_text=claim.source_text,
                settings=settings,
            )
            value_json["title"] = role.corrected_value_json.get("value", value_json["title"])
            evidence.extend(role.resolver_evidence)
            resolver_confidence = max(resolver_confidence, role.resolver_confidence)
            if resolver_action == "keep" and role.resolver_action != "keep":
                resolver_action = role.resolver_action
    if claim.section == "education" and value_json.get("degree"):
        degree = _degree_decision(
            session,
            profile,
            str(value_json["degree"]),
            claim.confidence,
            source_text=claim.source_text,
            settings=settings,
        )
        value_json["degree"] = degree.corrected_value_json.get("value", value_json["degree"])
        evidence.extend(degree.resolver_evidence)
        resolver_confidence = max(resolver_confidence, degree.resolver_confidence)
        resolver_action = degree.resolver_action if degree.resolver_action != "keep" else resolver_action

    next_section, section_evidence, section_score = _section_move_suggestion(claim.section, value_json)
    if next_section:
        suggested_section = next_section
        evidence.extend(section_evidence)
        resolver_confidence = max(resolver_confidence, section_score)
        if resolver_action == "keep":
            resolver_action = "suggest"

    if not evidence and resolver_action == "keep":
        evidence.append("parser_output")

    return ResolverDecision(
        corrected_value_json=value_json,
        corrected_section=suggested_section,
        resolver_action=resolver_action,
        resolver_confidence=round(min(0.99, resolver_confidence), 4),
        resolver_evidence=list(dict.fromkeys(evidence)),
    )


def resolve_structured_claim(
    session: Session,
    profile: Profile,
    claim: StructuredProfileClaim,
    *,
    settings: Settings | None = None,
) -> ResolverDecision:
    raw_value_json = dict(claim.raw_value_json or claim.value_json or {})
    parser_confidence = float(claim.confidence or 0.6)

    if claim.section == "identity":
        if claim.field_name in {"email", "phone", "location"}:
            return _contact_decision(raw_value_json, claim.field_name)
        if claim.field_name in {"full_name", "headline", "summary"}:
            return ResolverDecision(
                corrected_value_json=raw_value_json,
                resolver_action="keep",
                resolver_confidence=parser_confidence,
                resolver_evidence=["parser_output"],
            )

    if claim.section == "public_profiles":
        return _contact_decision(raw_value_json, "url")

    if claim.section == "skills":
        return _skill_decision(
            session,
            profile,
            raw_value_json,
            parser_confidence,
            source_text=claim.source_text,
            settings=settings,
        )

    if claim.field_name == "entry" and claim.section in {"work_experience", "projects", "education", "certifications"}:
        return _resolve_entry_claim(session, profile, claim, settings=settings)

    return ResolverDecision(
        corrected_value_json=raw_value_json,
        resolver_action="keep",
        resolver_confidence=parser_confidence,
        resolver_evidence=["parser_output"],
    )


def apply_correction_decision(claim: StructuredProfileClaim, decision: ResolverDecision) -> None:
    claim.value_json = decision.corrected_value_json
    claim.resolver_action = decision.resolver_action
    claim.resolver_confidence = decision.resolver_confidence
    claim.resolver_evidence = decision.resolver_evidence
    claim.suggested_section = decision.corrected_section


def _claim_signature(preview_section: str, field_name: str, value_json: dict[str, Any]) -> str:
    normalized_json = json.dumps(value_json or {}, sort_keys=True, ensure_ascii=True).lower()
    return f"{preview_section}|{field_name}|{normalized_json}"[:512]


def resolve_structured_profile_claims(
    session: Session,
    profile: Profile,
    claims: list[StructuredProfileClaim],
    *,
    settings: Settings | None = None,
) -> None:
    seen_signatures: set[str] = set()
    for claim in claims:
        preview_section = claim.suggested_section or claim.section
        if claim.status == "rejected":
            continue
        if claim.status == "edited" or claim.resolver_action == "manual":
            signature = _claim_signature(preview_section, claim.field_name, dict(claim.value_json or {}))
            seen_signatures.add(signature)
            continue

        decision = resolve_structured_claim(session, profile, claim, settings=settings)
        apply_correction_decision(claim, decision)

        preview_section = claim.suggested_section or claim.section
        signature = _claim_signature(preview_section, claim.field_name, dict(claim.value_json or {}))
        if signature in seen_signatures and preview_section in {"skills", "public_profiles"}:
            claim.status = "duplicate"
            claim.resolver_action = "duplicate"
            claim.resolver_evidence = list(dict.fromkeys([*claim.resolver_evidence, "duplicate_value"]))
            claim.suggested_section = None
        else:
            seen_signatures.add(signature)
            if claim.status not in {"accepted", "edited", "rejected"}:
                if claim.resolver_action == "auto_correct":
                    claim.status = "accepted"
                elif claim.resolver_action == "duplicate":
                    claim.status = "duplicate"
                else:
                    claim.status = "pending"


def sync_canonical_values_from_overview(session: Session, profile: Profile, overview: dict[str, Any]) -> None:
    session.execute(delete(CanonicalValue).where(CanonicalValue.profile_id == profile.id))
    rows: list[CanonicalValue] = []

    def add_row(value_type: str, canonical_value: str, aliases: list[str] | None = None, confidence: float = 1.0) -> None:
        cleaned = canonical_value.strip()
        if not cleaned:
            return
        rows.append(
            CanonicalValue(
                profile_id=profile.id,
                value_type=value_type,
                canonical_value=cleaned,
                aliases_json=aliases or [],
                source="canonical_profile",
                confidence=confidence,
            )
        )

    for skill in overview.get("skills", []):
        aliases = SKILL_ALIASES.get(skill, [])
        add_row("skill", skill, aliases=aliases)
    for item in overview.get("work_experience", []):
        if item.get("organization"):
            add_row("company", item["organization"], aliases=[], confidence=0.98)
        if item.get("title"):
            add_row("role", item["title"], aliases=ROLE_ALIASES.get(item["title"], []), confidence=0.95)
    for item in overview.get("education", []):
        if item.get("degree"):
            add_row("degree", item["degree"], aliases=DEGREE_ALIASES.get(item["degree"], []), confidence=0.98)
        if item.get("institution"):
            add_row("institution", item["institution"], aliases=[], confidence=0.92)
    for link in overview.get("public_profiles", []):
        if link.get("url"):
            add_row("url", link["url"], aliases=[], confidence=0.94)

    for row in rows:
        session.add(row)
    session.flush()


def maybe_record_correction_rule(session: Session, profile: Profile, claim: StructuredProfileClaim) -> None:
    raw_value = claim.raw_value_json or {}
    corrected_value = claim.value_json or {}
    if raw_value == corrected_value:
        return

    field_type = "generic"
    pattern = ""
    target_value = None

    if claim.section == "skills":
        field_type = "skill"
        pattern = str(raw_value.get("name") or "").strip()
        target_value = str(corrected_value.get("name") or "").strip()
    elif claim.section == "public_profiles":
        field_type = "url"
        pattern = str(raw_value.get("url") or "").strip()
        target_value = str(corrected_value.get("url") or "").strip()
    elif claim.section == "education":
        field_type = "degree"
        pattern = str(raw_value.get("degree") or "").strip()
        target_value = str(corrected_value.get("degree") or "").strip()
    elif claim.section == "work_experience":
        if raw_value.get("organization") and corrected_value.get("organization"):
            field_type = "company"
            pattern = str(raw_value.get("organization") or "").strip()
            target_value = str(corrected_value.get("organization") or "").strip()
        elif raw_value.get("title") and corrected_value.get("title"):
            field_type = "role"
            pattern = str(raw_value.get("title") or "").strip()
            target_value = str(corrected_value.get("title") or "").strip()

    if not pattern or not target_value or _normalize_lookup(pattern) == _normalize_lookup(target_value):
        return

    existing = session.scalar(
        select(CorrectionRule).where(
            CorrectionRule.profile_id == profile.id,
            CorrectionRule.field_type == field_type,
            CorrectionRule.pattern == pattern,
            CorrectionRule.target_value == target_value,
        )
    )
    if existing is not None:
        return

    session.add(
        CorrectionRule(
            profile_id=profile.id,
            pattern=pattern,
            field_type=field_type,
            action="normalize_to",
            target_value=target_value,
            target_section=claim.section,
            confidence=max(0.88, claim.resolver_confidence or claim.confidence),
        )
    )
    session.flush()
