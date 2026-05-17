from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import re
from typing import Any

from app.models import ClaimGroup, Document, User
from app.services.profile_memory import _normalize_overview_data, _unique_links, _unique_strings, source_priority_for_role


PROFILE_VIEWS = ("master", "ai_ml", "web_dev", "full_stack", "ats_short")
VIEW_SKILL_PRIORITIES = {
    "ai_ml": [
        "Python",
        "FastAPI",
        "RAG",
        "OCR",
        "LLM",
        "BERT",
        "PyTorch",
        "TensorFlow",
        "Redis",
        "Docker",
        "LangChain",
        "LlamaIndex",
        "LayoutLMv3",
        "Docling",
        "PyMuPDF",
        "NSQ",
    ],
    "web_dev": [
        "JavaScript",
        "TypeScript",
        "Angular",
        "React",
        "ASP.NET",
        "ASP.NET Core",
        "Django",
        "Flask",
        "SQL",
        "Bootstrap",
        "Azure",
        "Shopify",
        "CSS",
        "HTML",
        "jQuery",
    ],
    "full_stack": [
        "Python",
        "FastAPI",
        "JavaScript",
        "TypeScript",
        "React",
        "Angular",
        "ASP.NET",
        "Django",
        "SQL",
        "Docker",
        "Redis",
        "Azure",
        "AWS",
        "GCP",
    ],
}
VIEW_KEYWORDS = {
    "ai_ml": {"ai", "ml", "machine learning", "llm", "rag", "ocr", "bert", "fastapi", "document ai", "layoutlm"},
    "web_dev": {"react", "angular", "asp.net", "django", "javascript", "typescript", "mvc", "shopify", "jquery", "css"},
    "full_stack": {"fastapi", "react", "angular", "asp.net", "django", "javascript", "typescript", "docker", "redis"},
}
VIEW_DEFAULT_HEADLINES = {
    "ai_ml": "AI/ML Engineer",
    "web_dev": "Full-stack Developer",
    "full_stack": "Full-stack Engineer",
    "master": "Software Engineer",
    "ats_short": "Software Engineer",
}
PRESENT_PATTERN = re.compile(r"\b(?:present|current|now)\b", flags=re.IGNORECASE)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ -]+", " ", value.lower())).strip()


def _safe_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def _entry_text(entry: dict[str, Any]) -> str:
    parts = [
        _clean_text(entry.get("title")),
        _clean_text(entry.get("organization")),
        _clean_text(entry.get("name")),
        _clean_text(entry.get("summary")),
        " ".join(_clean_text(item) for item in entry.get("technologies", []) or []),
        " ".join(_clean_text(item) for item in entry.get("highlights", []) or []),
    ]
    return " ".join(part for part in parts if part).lower()


def _group_source_priority(group: ClaimGroup, field_bucket: str, documents: dict[str, Document]) -> float:
    source_ids = dict(group.group_metadata or {}).get("source_document_ids", []) or []
    if not source_ids:
        return 0.72
    priorities = []
    for document_id in source_ids:
        document = documents.get(document_id)
        role = (document.parse_metadata or {}).get("document_role") if document else None
        priorities.append(source_priority_for_role(field_bucket, role))
    return max(priorities or [0.72])


def _resolve_current_role_group(groups: list[ClaimGroup], documents: dict[str, Document]) -> ClaimGroup | None:
    candidates = [group for group in groups if group.group_type == "work_experience" and group.status == "merged"]
    if not candidates:
        return None

    def sort_key(group: ClaimGroup) -> tuple[float, int, int]:
        payload = dict(group.canonical_value_json or {})
        organization = _clean_text(payload.get("organization"))
        title = _clean_text(payload.get("title"))
        start_date = _clean_text(payload.get("start_date"))
        if not organization or not title or not start_date:
            return (-1.0, -1, -1)
        end_date = _clean_text(payload.get("end_date"))
        is_current = 1.0 if (not end_date or PRESENT_PATTERN.search(end_date)) else 0.0
        end_year = 9999 if is_current else (_safe_year(end_date) or 0)
        start_year = _safe_year(start_date) or 0
        priority = _group_source_priority(group, "current_experience" if is_current else "historical_experience", documents)
        score = 1.25 * is_current + 0.55 * float(group.confidence or 0.0) + 0.35 * priority
        return (score, end_year, start_year)

    return max(candidates, key=sort_key)


def _current_position_text(group: ClaimGroup | None) -> str | None:
    if group is None:
        return None
    payload = dict(group.canonical_value_json or {})
    title = _clean_text(payload.get("title"))
    organization = _clean_text(payload.get("organization"))
    if title and organization:
        return f"{title} · {organization}"
    return title or organization or None


def _skill_rank(skill: str, view: str) -> tuple[int, int, str]:
    priorities = VIEW_SKILL_PRIORITIES.get(view, [])
    if skill in priorities:
        return (0, priorities.index(skill), skill.lower())
    if view == "master":
        return (1, 0, skill.lower())
    return (2, 0, skill.lower())


def _generate_target_headline(view: str, skills: list[str], manual_target: str | None = None) -> str:
    if manual_target:
        return manual_target
    priorities = VIEW_SKILL_PRIORITIES.get(view, [])
    chosen = [skill for skill in priorities if skill in skills][:4]
    base = VIEW_DEFAULT_HEADLINES.get(view, "Software Engineer")
    if view == "ai_ml" and "LLM" in chosen and "OCR" in chosen:
        return f"{base} · Python · FastAPI · RAG · OCR · LLM Systems"
    if chosen:
        return f"{base} · " + " · ".join(chosen)
    return manual_target or base


def _view_summary(master: dict[str, Any], view: str) -> str | None:
    mode_summaries = dict(master.get("mode_summaries") or {})
    focus = _clean_text(master.get("profile_focus"))
    return (
        _clean_text(mode_summaries.get(view))
        or _clean_text(mode_summaries.get(focus))
        or _clean_text(master.get("identity", {}).get("summary"))
        or None
    )


def _entry_view_score(entry: dict[str, Any], view: str, *, current_position: str | None = None) -> tuple[float, int, int]:
    text = _entry_text(entry)
    start_year = _safe_year(entry.get("start_date")) or 0
    end_year = 9999 if PRESENT_PATTERN.search(_clean_text(entry.get("end_date"))) else (_safe_year(entry.get("end_date")) or start_year)
    score = 0.0
    if current_position and _clean_text(entry.get("title")) and _clean_text(entry.get("organization")):
        candidate = f"{_clean_text(entry.get('title'))} · {_clean_text(entry.get('organization'))}"
        if candidate == current_position:
            score += 2.0
    for keyword in VIEW_KEYWORDS.get(view, set()):
        if keyword in text:
            score += 0.4
    score += min(0.8, 0.08 * len(entry.get("technologies", []) or []))
    score += min(0.6, 0.04 * len(entry.get("highlights", []) or []))
    if view == "master":
        score += 0.35
    if view == "ats_short":
        score += 0.2
    return (score, end_year, start_year)


def _compile_experience(master: dict[str, Any], view: str, *, current_position: str | None) -> list[dict[str, Any]]:
    items = [dict(item) for item in master.get("work_experience", []) or []]
    if view == "master":
        items.sort(key=lambda item: (_safe_year(item.get("end_date")) or 9999, _safe_year(item.get("start_date")) or 0), reverse=True)
        return items
    ranked = sorted(items, key=lambda item: _entry_view_score(item, view, current_position=current_position), reverse=True)
    limit = 4 if view == "ats_short" else 5
    return ranked[:limit]


def _compile_projects(master: dict[str, Any], view: str) -> list[dict[str, Any]]:
    items = [dict(item) for item in master.get("projects", []) or []]
    if view == "master":
        return items[:10]

    def score(item: dict[str, Any]) -> tuple[float, int, str]:
        text = _entry_text(item)
        value = 0.0
        for keyword in VIEW_KEYWORDS.get(view, set()):
            if keyword in text:
                value += 0.45
        value += min(0.6, 0.08 * len(item.get("technologies", []) or []))
        value += 0.35 if item.get("links") else 0.0
        return (value, len(item.get("technologies", []) or []), _clean_text(item.get("name")).lower())

    ranked = sorted(items, key=score, reverse=True)
    limit = 4 if view == "ats_short" else 6
    return ranked[:limit]


def _compile_skills(master: dict[str, Any], view: str) -> list[str]:
    skills = _unique_strings(master.get("skills", []) or [])
    if view == "master":
        return skills
    ranked = sorted(skills, key=lambda skill: _skill_rank(skill, view))
    limit = 18 if view == "ats_short" else 25
    preferred = [skill for skill in ranked if skill in VIEW_SKILL_PRIORITIES.get(view, [])]
    remainder = [skill for skill in ranked if skill not in preferred]
    return preferred[:limit] + remainder[: max(0, limit - len(preferred[:limit]))]


def _compile_links(master: dict[str, Any]) -> list[dict[str, Any]]:
    personal_labels = {"linkedin", "github", "portfolio", "leetcode", "hackerrank"}
    links = []
    for link in master.get("public_profiles", []) or []:
        label = _clean_text(link.get("label")).lower()
        if any(token in label for token in personal_labels) or _clean_text(link.get("url")):
            links.append(dict(link))
    return _unique_links(links)


def compile_profile_views(
    master_profile: dict[str, Any],
    groups: list[ClaimGroup],
    documents: dict[str, Document],
    user: User | None = None,
) -> dict[str, dict[str, Any]]:
    master = _normalize_overview_data(master_profile)
    current_role_group = _resolve_current_role_group(groups, documents)
    current_position = _current_position_text(current_role_group)
    manual_target = None
    for group in groups:
        if group.group_type != "identity" or group.status != "merged":
            continue
        metadata = dict(group.group_metadata or {})
        if metadata.get("field_name") == "headline" and metadata.get("has_manual_edit"):
            manual_target = _clean_text((group.canonical_value_json or {}).get("value")) or _clean_text(group.canonical_value)
            break
    focus = _clean_text(master.get("profile_focus")) or "master"
    compiled_views: dict[str, dict[str, Any]] = {}

    for view in PROFILE_VIEWS:
        compiled = _normalize_overview_data(deepcopy(master))
        compiled["profile_view"] = view
        compiled["available_views"] = list(PROFILE_VIEWS)
        compiled["profile_focus"] = focus
        compiled["skills"] = _compile_skills(master, view)
        compiled["public_profiles"] = _compile_links(master)
        compiled["work_experience"] = _compile_experience(master, view, current_position=current_position)
        compiled["projects"] = _compile_projects(master, view)
        compiled["education"] = list(master.get("education", []) or [])
        compiled["certifications"] = list(master.get("certifications", []) or [])
        identity = dict(compiled.get("identity") or {})
        identity["current_position"] = current_position
        identity["target_headline"] = _generate_target_headline(view, compiled["skills"], manual_target=manual_target)
        identity["headline"] = identity["target_headline"]
        identity["summary"] = _view_summary(master, view)
        if user and not identity.get("full_name"):
            identity["full_name"] = user.full_name
        compiled["identity"] = identity
        compiled_views[view] = _normalize_overview_data(compiled)

    return compiled_views
