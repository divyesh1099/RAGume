from __future__ import annotations

import re
from typing import Any

from app.models import Document
from app.services.claim_utils import extract_skills
from app.services.resume_parser import (
    BULLET_LINE_PATTERN,
    DATE_RANGE_PATTERN,
    DEGREE_PATTERN,
    INSTITUTION_PATTERN,
    ROLE_WORD_PATTERN,
    URL_PATTERN,
    _clean_text as _parser_clean_text,
    _entry_summary,
    _extract_date_range,
    _iter_text_sections,
    _normalize_highlights,
    _unique_skill_strings,
    _unique_strings,
)


LOWER_WORD_PATTERN = re.compile(r"[^a-z0-9+#./& -]+")
INLINE_SEPARATOR_PATTERN = re.compile(r"\s*[|⋄]\s*")
INLINE_DASH_PATTERN = re.compile(r"\s*[–-]\s*", flags=re.UNICODE)
EXPERIENCE_ACTION_PATTERN = re.compile(
    r"^(?:worked|built|created|implemented|designed|developed|migrated|led|managed|refactored|optimized|deployed|presented|instituted|automated)\b",
    flags=re.IGNORECASE,
)
ORG_HINT_PATTERN = re.compile(
    r"\b(?:ltd|limited|pvt|private|llp|inc|corp|consultant|consultancy|solutions|systems|learning|technologies|tech|labs|india|navy|college|university|council|foundation)\b",
    flags=re.IGNORECASE,
)
EXPERIENCE_ROLE_TOKENS = {
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
SUMMARY_BAD_START_PATTERN = re.compile(
    r"^(?:worked on|created|implemented|built|designed|developed|migrated|refactored|led)\b",
    flags=re.IGNORECASE,
)
MONTH_WORD_PATTERN = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b", flags=re.IGNORECASE)
PROJECT_FRAGMENT_BLACKLIST = {
    "app that auto",
    "python nsq",
    "tech fest budget",
    "volunteers freelance",
    "student rep",
    "leadership mentor",
}
PROJECT_SECTION_KEYWORDS = {"projects", "selected projects", "open source"}
LEADERSHIP_HINTS = {
    "mentor",
    "student rep",
    "student representative",
    "open source day",
    "council",
    "volunteers",
    "leadership",
}
FREELANCE_HINTS = {"freelance", "shopify", "wix", "client", "stores", "smb"}
KNOWN_PROJECT_STYLE_TOKENS = {"bot", "pipeline", "app", "application", "store", "queue", "locator", "assistant", "platform"}
SKILL_TAXONOMY = {
    "Programming languages": {
        "Python",
        "JavaScript",
        "TypeScript",
        "C#",
        "C++",
        "SQL",
        "HTML",
        "CSS",
        "Sass",
    },
    "Frameworks": {
        "Angular",
        "React",
        "ASP.NET",
        "ASP.NET Core",
        "Flask",
        "Django",
        "FastAPI",
        "Bootstrap",
        "jQuery",
        "WebGL",
    },
    "ML/AI": {
        "NLP",
        "OCR",
        "RAG",
        "LLM",
        "BERT",
        "RoBERTa",
        "T5",
        "PyTorch",
        "TensorFlow",
        "NumPy",
        "Pandas",
        "XGBoost",
        "Prophet",
        "ARIMA",
        "LangChain",
        "LlamaIndex",
        "LangGraph",
        "AutoGen",
        "CrewAI",
        "MLflow",
        "Weights & Biases",
    },
    "Databases": {"MongoDB", "Redis", "PostgreSQL", "RabbitMQ"},
    "Cloud": {"AWS", "Azure", "GCP", "Anthos", "Vertex AI", "Azure OpenAI"},
    "DevOps": {"Docker", "Terraform", "Helm", "GitHub Actions", "CI/CD", "Kafka", "NSQ"},
    "Backend": {"gRPC", "REST", "Django REST"},
    "Soft skills": {"Agile", "Scrum", "Mentor", "Technical leadership"},
}


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", LOWER_WORD_PATTERN.sub(" ", value.lower())).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return _parser_clean_text(str(value))


def _section_blocks_from_text(document: Document) -> dict[str, list[dict[str, Any]]]:
    sections = [section for section in _iter_text_sections(document.extracted_text or "") if section]
    section_blocks: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        heading = str(section.get("heading") or "")
        blocks: list[dict[str, Any]] = []
        for index, block in enumerate(section.get("blocks") or []):
            blocks.append(
                {
                    **dict(block),
                    "_assembler_section": heading,
                    "_assembler_block_id": f"{heading}:{index}",
                    "_assembler_index": index,
                }
            )
        section_blocks[heading] = blocks
    return section_blocks


def _frame_block_ids(blocks: list[dict[str, Any]]) -> list[str]:
    return [str(block.get("_assembler_block_id") or f"block:{index}") for index, block in enumerate(blocks)]


def _frame_visual_group(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "group:unknown"
    first = blocks[0]
    return str(first.get("_assembler_block_id") or "group:unknown")


def _frame_page(blocks: list[dict[str, Any]]) -> int | None:
    if not blocks:
        return None
    return int(blocks[0].get("page") or 0)


def _clean_lines(block: dict[str, Any]) -> list[str]:
    return [line for line in (_clean_text(line) for line in block.get("lines", [])) if line]


def _body_line(line: str) -> str:
    return _clean_text(line).lstrip("•*- ").strip()


def _split_header_parts(lines: list[str]) -> list[str]:
    parts: list[str] = []
    for line in lines:
        split = [item for item in (_clean_text(part) for part in INLINE_SEPARATOR_PATTERN.split(line)) if item]
        if len(split) > 1:
            parts.extend(split)
        else:
            parts.append(line)
    return parts


def _split_experience_block_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    header_lines: list[str] = []
    body_lines: list[str] = []
    for raw_line in lines:
        line = _clean_text(raw_line)
        if not line:
            continue
        if body_lines:
            body_lines.append(_body_line(line))
            continue
        if BULLET_LINE_PATTERN.match(line) or EXPERIENCE_ACTION_PATTERN.search(line):
            body_lines.append(_body_line(line))
            continue
        header_lines.append(line)
    return header_lines, body_lines


def _looks_like_experience_header_lines(lines: list[str]) -> bool:
    if not lines:
        return False
    first = lines[0]
    if BULLET_LINE_PATTERN.match(first) or EXPERIENCE_ACTION_PATTERN.search(first):
        return False
    text = " ".join(lines)
    if len(text) > 220 and not DATE_RANGE_PATTERN.search(text):
        return False
    return bool(DATE_RANGE_PATTERN.search(text) or ROLE_WORD_PATTERN.search(text))


def _looks_like_experience_header_block(block: dict[str, Any]) -> bool:
    header_lines, _body_lines = _split_experience_block_lines(_clean_lines(block))
    return _looks_like_experience_header_lines(header_lines)


def _looks_like_title(value: str) -> bool:
    return bool(ROLE_WORD_PATTERN.search(value))


def _looks_like_organization(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or DATE_RANGE_PATTERN.search(cleaned):
        return False
    if ORG_HINT_PATTERN.search(cleaned):
        return True
    return not _looks_like_title(cleaned) and len(cleaned.split()) >= 2


def _split_embedded_title_org(value: str) -> tuple[str | None, str | None]:
    cleaned = _clean_text(value)
    if not cleaned:
        return None, None
    reduced = DATE_RANGE_PATTERN.sub("", cleaned)
    reduced = re.sub(r"\([^)]*\)", "", reduced)
    reduced = _clean_text(reduced).strip(" -|().")
    if " in " not in reduced.lower():
        return None, None
    left, right = re.split(r"\bin\b", reduced, maxsplit=1, flags=re.IGNORECASE)
    left = _clean_text(left).strip(" -|().")
    right = _clean_text(right).strip(" -|().")
    left = re.sub(r"\s*[(-]?\d.*$", "", left).strip(" -|().")
    right = re.sub(r"\s*[(-]?\d.*$", "", right).strip(" -|().")
    right_is_embedded_org = bool(right) and not DATE_RANGE_PATTERN.search(right) and not _looks_like_title(right)
    left_is_embedded_org = bool(left) and not DATE_RANGE_PATTERN.search(left) and not _looks_like_title(left)
    if _looks_like_title(left) and (_looks_like_organization(right) or right_is_embedded_org):
        return left, right
    if _looks_like_title(right) and (_looks_like_organization(left) or left_is_embedded_org):
        return right, left
    return None, None


def _experience_hint_is_reliable(hint: dict[str, Any]) -> bool:
    title = _clean_text(hint.get("title"))
    organization = _clean_text(hint.get("organization"))
    summary = _clean_text(hint.get("summary"))
    if not title or not organization:
        return False
    combined = " ".join(part for part in (title, organization, summary) if part)
    if "@" in combined or "linkedin.com" in combined.lower() or "github.com" in combined.lower():
        return False
    if len(summary) > 420:
        return False
    normalized_summary = _normalize_lookup(summary)
    role_hits = sum(1 for token in EXPERIENCE_ROLE_TOKENS if token in normalized_summary)
    if role_hits > 3:
        return False
    return True


def _is_skill_like_token(value: str) -> bool:
    normalized = _normalize_lookup(value)
    if not normalized:
        return False
    for values in SKILL_TAXONOMY.values():
        if any(_normalize_lookup(item) == normalized for item in values):
            return True
    return False


def _experience_hint_score(frame: dict[str, Any], hint: dict[str, Any]) -> float:
    score = 0.0
    frame_title = _normalize_lookup(frame.get("title") or "")
    frame_org = _normalize_lookup(frame.get("organization") or "")
    frame_start = _normalize_lookup(frame.get("start_date") or "")
    frame_end = _normalize_lookup(frame.get("end_date") or "")
    hint_title = _normalize_lookup(hint.get("title") or "")
    hint_org = _normalize_lookup(hint.get("organization") or "")
    hint_start = _normalize_lookup(hint.get("start_date") or "")
    hint_end = _normalize_lookup(hint.get("end_date") or "")
    if frame_org and hint_org and (frame_org in hint_org or hint_org in frame_org):
        score += 0.45
    if frame_title and hint_title and (frame_title in hint_title or hint_title in frame_title):
        score += 0.35
    if frame_start and hint_start and frame_start == hint_start:
        score += 0.2
    if frame_end and hint_end and frame_end == hint_end:
        score += 0.15
    if not frame_org and hint_org:
        score += 0.05
    if not frame_title and hint_title:
        score += 0.05
    return score


def _match_experience_hint(frame: dict[str, Any], hints: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for hint in hints:
        if not _experience_hint_is_reliable(hint):
            continue
        score = _experience_hint_score(frame, hint)
        if score > best_score:
            best = hint
            best_score = score
    return best if best_score >= 0.4 else None


def _weak_title(value: str | None) -> bool:
    cleaned = _clean_text(value)
    return not cleaned or not _looks_like_title(cleaned) or len(cleaned.split()) <= 1


def _weak_organization(value: str | None) -> bool:
    cleaned = _clean_text(value)
    return not cleaned or not _looks_like_organization(cleaned)


def _assemble_experience_header(block: dict[str, Any], header_lines: list[str], hints: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [line for line in header_lines if line]
    parts = _split_header_parts(lines)
    header_text = _clean_text(" ".join(lines))
    date_index = next((index for index, part in enumerate(parts) if DATE_RANGE_PATTERN.search(part)), None)
    title = next((part for part in parts if _looks_like_title(part) and not DATE_RANGE_PATTERN.search(part)), None)
    organization = next((part for part in parts if _looks_like_organization(part) and part != title), None)
    location = next(
        (
            part
            for part in parts
            if part not in {title, organization}
            and not DATE_RANGE_PATTERN.search(part)
            and not _looks_like_title(part)
            and len(part.split()) <= 4
        ),
        None,
    )

    if date_index is not None:
        before_parts = [part for part in parts[:date_index] if part]
        after_parts = [part for part in parts[date_index + 1 :] if part]
        if before_parts and not any(_looks_like_title(part) for part in before_parts):
            organization = organization or before_parts[0]
        if after_parts:
            title = title or next((part for part in after_parts if _looks_like_title(part)), None)
            location = location or next(
                (part for part in after_parts if part not in {title, organization} and not _looks_like_title(part)),
                None,
            )
        if not title and before_parts and _looks_like_title(before_parts[0]):
            title = before_parts[0]
            if len(before_parts) >= 2:
                organization = organization or before_parts[1]

    for candidate in (title, organization, header_text):
        split_title, split_org = _split_embedded_title_org(candidate or "")
        if not split_title or not split_org:
            continue
        if not title or title == candidate or " in " in (title or "").lower():
            title = split_title
        if not organization or organization == candidate or DATE_RANGE_PATTERN.search(organization or ""):
            organization = split_org
        break

    start_date, end_date = _extract_date_range(" | ".join(parts))
    frame = {
        "record_type": "experience",
        "organization": _clean_text(organization) or None,
        "title": _clean_text(title) or None,
        "location": _clean_text(location) or None,
        "start_date": start_date,
        "end_date": end_date,
        "summary": None,
        "highlights": [],
        "technologies": [],
        "source_page": _frame_page([block]),
        "visual_group_id": _frame_visual_group([block]),
        "source_block_ids": _frame_block_ids([block]),
        "title_block_id": str(block.get("_assembler_block_id")),
        "org_block_id": str(block.get("_assembler_block_id")) if organization else None,
        "date_block_id": str(block.get("_assembler_block_id")) if start_date or end_date else None,
        "bullet_block_ids": [],
        "_body_lines": [],
    }

    hint = _match_experience_hint(frame, hints)
    if hint is not None:
        if _weak_title(frame.get("title")):
            frame["title"] = _clean_text(hint.get("title")) or frame["title"]
        if _weak_organization(frame.get("organization")):
            frame["organization"] = _clean_text(hint.get("organization")) or frame["organization"]
        if not frame.get("location"):
            frame["location"] = _clean_text(hint.get("location")) or frame["location"]
        if not frame.get("start_date"):
            frame["start_date"] = _clean_text(hint.get("start_date")) or frame["start_date"]
        if not frame.get("end_date"):
            frame["end_date"] = _clean_text(hint.get("end_date")) or frame["end_date"]
        if hint.get("highlights"):
            frame["_body_lines"].extend([_clean_text(item) for item in hint.get("highlights", []) if _clean_text(item)])
        if hint.get("technologies"):
            frame["technologies"] = _unique_skill_strings([*frame["technologies"], *hint.get("technologies", [])])
    return frame


def _finalize_experience_frame(frame: dict[str, Any], document_id: str) -> dict[str, Any] | None:
    highlights = _normalize_highlights(frame.pop("_body_lines", []))
    technologies = _unique_skill_strings([*frame.get("technologies", []), *extract_skills(" ".join(highlights))])
    frame["highlights"] = highlights
    frame["summary"] = frame.get("summary") or _entry_summary(highlights)
    frame["technologies"] = technologies
    frame["source_document_ids"] = [document_id]
    completeness = sum(
        1
        for value in (
            frame.get("organization"),
            frame.get("title"),
            frame.get("start_date"),
            frame.get("end_date"),
            frame.get("summary") or highlights,
        )
        if value
    )
    frame["confidence"] = round(max(0.0, min(1.0, 0.42 + 0.12 * completeness + 0.04 * min(4, len(highlights)))) , 3)
    if not frame.get("organization") and not frame.get("title"):
        return None
    return frame


def assemble_experience_frames(blocks: list[dict[str, Any]], hints: list[dict[str, Any]], *, document_id: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finalize_current() -> None:
        nonlocal current
        if current is None:
            return
        finalized = _finalize_experience_frame(current, document_id)
        if finalized is not None:
            frames.append(finalized)
        current = None

    for block in blocks:
        lines = _clean_lines(block)
        if not lines:
            continue
        header_lines, body_lines = _split_experience_block_lines(lines)
        if _looks_like_experience_header_lines(header_lines):
            finalize_current()
            current = _assemble_experience_header(block, header_lines, hints)
            if body_lines:
                current["_body_lines"].extend(body_lines)
                current["source_block_ids"].extend(_frame_block_ids([block]))
                current["bullet_block_ids"].extend(_frame_block_ids([block]))
            continue
        if current is None:
            continue
        current["_body_lines"].extend(_body_line(line) for line in lines)
        current["source_block_ids"].extend(_frame_block_ids([block]))
        current["bullet_block_ids"].extend(_frame_block_ids([block]))

    finalize_current()
    return frames


def _project_noise_name(name: str) -> bool:
    normalized = _normalize_lookup(name)
    if not normalized:
        return True
    if normalized in {"n a", "na"}:
        return True
    if normalized in PROJECT_FRAGMENT_BLACKLIST:
        return True
    if name.lstrip().startswith(("•", "-", "*")):
        return True
    if normalized.startswith(("it is", "this was", "assits", "created and", "implemented")):
        return True
    if normalized.startswith(("app that", "tech fest", "volunteers")):
        return True
    if name[:1].islower() and not any(character.isupper() for character in name[1:]):
        return True
    return False


def _looks_like_project_title_line(value: str) -> bool:
    cleaned = _clean_text(value).rstrip(":")
    if not cleaned:
        return False
    if BULLET_LINE_PATTERN.match(cleaned) or URL_PATTERN.search(cleaned):
        return False
    if ROLE_WORD_PATTERN.search(cleaned) and not any(token in _normalize_lookup(cleaned) for token in KNOWN_PROJECT_STYLE_TOKENS):
        return False
    if DATE_RANGE_PATTERN.search(cleaned) or MONTH_WORD_PATTERN.search(cleaned):
        return False
    if len(cleaned.split()) > 6:
        return False
    return not _project_noise_name(cleaned)


def _classify_project_candidate(name: str, summary: str, technologies: list[str], links: list[str], section: str) -> str:
    combined = _normalize_lookup(" ".join(part for part in (name, summary) if part))
    if _project_noise_name(name):
        return "reject"
    if any(token in combined for token in FREELANCE_HINTS):
        return "freelance"
    if any(token in combined for token in LEADERSHIP_HINTS):
        return "leadership"
    project_signals = 0
    if name and not _project_noise_name(name):
        project_signals += 1
    if summary and len(summary.split()) >= 5:
        project_signals += 1
    if technologies:
        project_signals += 1
    if links:
        project_signals += 1
    if section in PROJECT_SECTION_KEYWORDS:
        project_signals += 1
    if project_signals >= 2:
        return "project"
    return "reject"


def _split_inline_project_segments(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for chunk in [item for item in (_clean_text(piece) for piece in INLINE_SEPARATOR_PATTERN.split(text)) if item]:
        if "http" in chunk and " " not in chunk:
            continue
        if "–" not in chunk and "-" not in chunk:
            continue
        parts = INLINE_DASH_PATTERN.split(chunk, maxsplit=1)
        if len(parts) != 2:
            continue
        name = _clean_text(parts[0]).rstrip(".")
        summary = _clean_text(parts[1])
        if name and summary.lower().endswith(name.lower()):
            summary = _clean_text(summary[: -len(name)]).strip(" .-|")
        if name:
            segments.append((name, summary))
    return segments


def _project_frame(
    *,
    name: str,
    summary: str,
    source_blocks: list[dict[str, Any]],
    document_id: str,
    classification: str = "project",
) -> dict[str, Any]:
    technologies = _unique_skill_strings([*extract_skills(summary), *[skill for skill in extract_skills(name) if _is_skill_like_token(skill)]])
    links = _unique_strings(match.group(0) for match in URL_PATTERN.finditer(f"{name} {summary}"))
    return {
        "record_type": classification,
        "name": _clean_text(name) or None,
        "summary": _clean_text(summary) or None,
        "technologies": technologies,
        "links": links,
        "source_document_ids": [document_id],
        "source_page": _frame_page(source_blocks),
        "visual_group_id": _frame_visual_group(source_blocks),
        "source_block_ids": _frame_block_ids(source_blocks),
        "confidence": round(max(0.0, min(1.0, 0.46 + 0.08 * len(technologies) + (0.16 if summary else 0.0) + (0.12 if links else 0.0))), 3),
    }


def _project_frame_from_block(
    block: dict[str, Any],
    *,
    document_id: str,
) -> dict[str, Any] | None:
    lines = _clean_lines(block)
    if len(lines) < 2:
        return None
    first = _clean_text(lines[0]).rstrip(":")
    if not _looks_like_project_title_line(first):
        return None
    body_lines: list[str] = []
    for line in lines[1:]:
        cleaned = _clean_text(line)
        if not cleaned or cleaned.upper() == "N/A":
            continue
        if not body_lines and (DATE_RANGE_PATTERN.search(cleaned) or MONTH_WORD_PATTERN.search(cleaned)):
            continue
        body_lines.append(_body_line(cleaned))
    summary = " ".join(item for item in body_lines if item).strip()
    links = _unique_strings(match.group(0) for match in URL_PATTERN.finditer(" ".join(lines)))
    technologies = _unique_skill_strings(extract_skills(summary))
    classification = _classify_project_candidate(first, summary, technologies, links, "projects")
    if classification == "reject":
        return None
    frame = _project_frame(
        name=first,
        summary=summary,
        source_blocks=[block],
        document_id=document_id,
        classification=classification,
    )
    frame["technologies"] = technologies or frame["technologies"]
    frame["links"] = _unique_strings([*frame["links"], *links])
    return frame


def _best_project_hint_match(name: str, hints: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = _normalize_lookup(name)
    for hint in hints:
        hint_name = _normalize_lookup(hint.get("name") or "")
        if hint_name and (hint_name == normalized or hint_name in normalized or normalized in hint_name):
            return hint
    return None


def assemble_project_frames(
    blocks: list[dict[str, Any]],
    hints: list[dict[str, Any]],
    *,
    document_id: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "project_frames": [],
        "leadership_frames": [],
        "freelance_frames": [],
        "achievement_frames": [],
    }
    seen_names: set[str] = set()

    for block in blocks:
        direct_frame = _project_frame_from_block(block, document_id=document_id)
        if direct_frame is not None:
            key = f"{direct_frame['record_type']}:{_normalize_lookup(direct_frame.get('name') or '')}"
            if key not in seen_names:
                seen_names.add(key)
                grouped[f"{direct_frame['record_type']}_frames"].append(direct_frame)
            continue
        block_text = " | ".join(_clean_lines(block))
        for name, summary in _split_inline_project_segments(block_text):
            hint = _best_project_hint_match(name, hints)
            if hint is not None:
                summary = _clean_text(summary) or _clean_text(hint.get("summary")) or summary
            if _project_noise_name(name):
                continue
            links = _unique_strings(match.group(0) for match in URL_PATTERN.finditer(f"{name} {summary}"))
            technologies = _unique_skill_strings([*extract_skills(summary), *(hint.get("technologies", []) if hint else [])])
            classification = _classify_project_candidate(name, summary, technologies, links, "projects")
            if classification == "reject":
                continue
            key = f"{classification}:{_normalize_lookup(name)}"
            if key in seen_names:
                continue
            seen_names.add(key)
            frame = _project_frame(
                name=name,
                summary=summary,
                source_blocks=[block],
                document_id=document_id,
                classification=classification,
            )
            frame["technologies"] = technologies or frame["technologies"]
            frame["links"] = _unique_strings([*frame["links"], *links, *(hint.get("links", []) if hint else [])])
            grouped[f"{classification}_frames"].append(frame)

    for hint in hints:
        name = _clean_text(hint.get("name"))
        summary = _clean_text(hint.get("summary"))
        key = f"project:{_normalize_lookup(name)}"
        if not name or key in seen_names:
            continue
        if "|" in name or len(name.split()) > 6 or re.search(r"[–-].{12,}", name) or "•" in name or DATE_RANGE_PATTERN.search(name) or MONTH_WORD_PATTERN.search(name):
            continue
        classification = _classify_project_candidate(
            name,
            summary,
            _unique_skill_strings(hint.get("technologies", []) or []),
            _unique_strings(hint.get("links", []) or []),
            "projects",
        )
        if classification == "reject":
            continue
        seen_names.add(f"{classification}:{_normalize_lookup(name)}")
        frame = _project_frame(
            name=name,
            summary=summary,
            source_blocks=[],
            document_id=document_id,
            classification=classification,
        )
        frame["technologies"] = _unique_skill_strings(hint.get("technologies", []) or [])
        frame["links"] = _unique_strings(hint.get("links", []) or [])
        grouped[f"{classification}_frames"].append(frame)

    return grouped


def assemble_education_frames(blocks: list[dict[str, Any]], hints: list[dict[str, Any]], *, document_id: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for block in blocks:
        lines = _clean_lines(block)
        text = " | ".join(lines)
        if not text:
            continue
        parts = _split_header_parts(lines)
        institution = next((part for part in parts if INSTITUTION_PATTERN.search(part)), None)
        degree = next((part for part in parts if DEGREE_PATTERN.search(part)), None)
        start_date, end_date = _extract_date_range(text)
        summary_parts = [part for part in parts if part not in {institution, degree} and not DATE_RANGE_PATTERN.search(part)]
        frame = {
            "record_type": "education",
            "institution": _clean_text(institution) or None,
            "degree": _clean_text(degree) or None,
            "field_of_study": None,
            "start_date": start_date,
            "end_date": end_date,
            "summary": _clean_text(" ".join(summary_parts)) or None,
            "source_document_ids": [document_id],
            "source_page": _frame_page([block]),
            "visual_group_id": _frame_visual_group([block]),
            "source_block_ids": _frame_block_ids([block]),
            "confidence": 0.82,
        }
        if frame["institution"] or frame["degree"]:
            frames.append(frame)

    if not frames:
        for hint in hints:
            institution = _clean_text(hint.get("institution"))
            degree = _clean_text(hint.get("degree"))
            if not institution and not degree:
                continue
            frames.append(
                {
                    "record_type": "education",
                    "institution": institution or None,
                    "degree": degree or None,
                    "field_of_study": _clean_text(hint.get("field_of_study")) or None,
                    "start_date": _clean_text(hint.get("start_date")) or None,
                    "end_date": _clean_text(hint.get("end_date")) or None,
                    "summary": _clean_text(hint.get("summary")) or None,
                    "source_document_ids": [document_id],
                    "source_page": None,
                    "visual_group_id": "education:fallback",
                    "source_block_ids": [],
                    "confidence": 0.76,
                }
            )
    return frames


def assemble_summary_frames(
    blocks: list[dict[str, Any]],
    fallback_summary: str | None,
    *,
    document: Document,
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for block in blocks:
        lines = _clean_lines(block)
        text = _clean_text(" ".join(lines))
        if not text:
            continue
        if len(text) < 80 or len(text) > 900:
            continue
        if SUMMARY_BAD_START_PATTERN.search(text):
            continue
        if DATE_RANGE_PATTERN.search(text[:80]):
            continue
        frames.append(
            {
                "record_type": "summary",
                "text": text,
                "mode": str((document.parse_metadata or {}).get("profile_focus") or "master"),
                "source_document_ids": [document.id],
                "source_page": _frame_page([block]),
                "visual_group_id": _frame_visual_group([block]),
                "source_block_ids": _frame_block_ids([block]),
                "confidence": 0.92,
            }
        )

    fallback = _clean_text(fallback_summary)
    if not frames and fallback and 80 <= len(fallback) <= 900 and not SUMMARY_BAD_START_PATTERN.search(fallback):
        frames.append(
            {
                "record_type": "summary",
                "text": fallback,
                "mode": str((document.parse_metadata or {}).get("profile_focus") or "master"),
                "source_document_ids": [document.id],
                "source_page": None,
                "visual_group_id": "summary:fallback",
                "source_block_ids": [],
                "confidence": 0.68,
            }
        )
    return frames


def assemble_document_records(document: Document, insights: dict[str, Any]) -> dict[str, Any]:
    section_blocks = _section_blocks_from_text(document)
    project_buckets = assemble_project_frames(
        section_blocks.get("projects", []),
        list(insights.get("projects", []) or []),
        document_id=document.id,
    )
    leadership_blocks = section_blocks.get("leadership", [])
    if leadership_blocks:
        leadership_buckets = assemble_project_frames(leadership_blocks, [], document_id=document.id)
        project_buckets["leadership_frames"].extend(leadership_buckets.get("project_frames", []))
        project_buckets["leadership_frames"].extend(leadership_buckets.get("leadership_frames", []))
        project_buckets["freelance_frames"].extend(leadership_buckets.get("freelance_frames", []))

    experience_frames = assemble_experience_frames(
        section_blocks.get("work_experience", []),
        list(insights.get("work_experience", []) or []),
        document_id=document.id,
    )
    education_frames = assemble_education_frames(
        section_blocks.get("education", []),
        list(insights.get("education", []) or []),
        document_id=document.id,
    )
    summary_frames = assemble_summary_frames(
        section_blocks.get("summary", []),
        (insights.get("identity") or {}).get("summary"),
        document=document,
    )
    return {
        "experience_frames": experience_frames,
        "project_frames": project_buckets.get("project_frames", []),
        "leadership_frames": project_buckets.get("leadership_frames", []),
        "freelance_frames": project_buckets.get("freelance_frames", []),
        "achievement_frames": project_buckets.get("achievement_frames", []),
        "education_frames": education_frames,
        "summary_frames": summary_frames,
        "section_counts": {key: len(value) for key, value in section_blocks.items()},
    }
