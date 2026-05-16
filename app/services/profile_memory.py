import datetime as dt
import json
import re
from collections import defaultdict
from typing import Any

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, Profile, User
from app.services.claim_utils import extract_skills
from app.services.parser_backends import parse_resume_with_backend, resolve_resume_parser_backend

EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
URL_PATTERN = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+")
SECTION_HEADING_PATTERN = re.compile(r"^[A-Za-z][A-Za-z /&+-]{1,40}:?$")
DATE_RANGE_PATTERN = re.compile(
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+)?\d{4}"
    r"(?:\s*[-–to]+\s*(?:(?:present|current)|(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+)?\d{4}))?",
    flags=re.IGNORECASE,
)
DEGREE_PATTERN = re.compile(
    r"\b(?:b\.?tech|m\.?tech|bachelor(?:'s)?|master(?:'s)?|ph\.?d|diploma|mba|bca|mca|bs|ms|be|me)\b",
    flags=re.IGNORECASE,
)
ROLE_PATTERN = re.compile(
    r"\b(?:engineer|developer|scientist|analyst|intern|consultant|researcher|manager|lead|architect|specialist|designer)\b",
    flags=re.IGNORECASE,
)
INSTITUTION_PATTERN = re.compile(
    r"\b(?:university|college|institute|school|academy|polytechnic)\b",
    flags=re.IGNORECASE,
)
PROJECT_PATTERN = re.compile(
    r"\b(?:project|platform|application|system|tool|pipeline|dashboard|agent|assistant)\b",
    flags=re.IGNORECASE,
)
SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "about", "profile", "overview"},
    "skills": {"skills", "technical skills", "technologies", "tools", "stack", "core skills"},
    "work_experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "career history",
    },
    "education": {"education", "academic background", "academics"},
    "projects": {"projects", "selected projects", "personal projects", "key projects", "portfolio"},
    "certifications": {"certifications", "certification", "licenses", "courses"},
    "contact": {"contact", "details", "contact details", "contact information"},
}
GENERIC_HEADINGS = set().union(*SECTION_ALIASES.values())
LOCATION_PATTERN = re.compile(
    r"\b(?:remote|hybrid|india|usa|united states|canada|uk|london|new york|california|"
    r"bengaluru|bangalore|mumbai|delhi|pune|hyderabad|chennai|gurugram|gurgaon)\b",
    flags=re.IGNORECASE,
)
CERTIFICATION_PATTERN = re.compile(
    r"\b(?:certification|certificate|certified|credential|license|licensed)\b",
    flags=re.IGNORECASE,
)


def _default_identity() -> dict[str, Any]:
    return {
        "full_name": None,
        "headline": None,
        "summary": None,
        "location": None,
        "emails": [],
        "phones": [],
    }


def _default_overview_data() -> dict[str, Any]:
    return {
        "identity": _default_identity(),
        "skills": [],
        "public_profiles": [],
        "education": [],
        "work_experience": [],
        "projects": [],
        "certifications": [],
        "source_documents": [],
        "auto_updated_at": None,
    }


def _default_profile_container() -> dict[str, Any]:
    return {
        "auto": _default_overview_data(),
        "manual": {},
    }


def _clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _split_contact_segments(line: str) -> list[str]:
    return [
        segment
        for segment in (_clean_line(part) for part in re.split(r"\s*[|•·]\s*|\s{2,}", line))
        if segment
    ]


def _normalize_url(url: str) -> str:
    cleaned = url.strip().rstrip(".,);")
    if cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"
    return cleaned


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = _clean_line(value)
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        unique.append(cleaned)
        seen.add(lowered)
    return unique


def _unique_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in links:
        url = _normalize_url(item.get("url", ""))
        if not url or url.lower() in seen:
            continue
        unique.append(
            {
                "label": _clean_line(item.get("label") or "Link"),
                "url": url,
            }
        )
        seen.add(url.lower())
    return unique


def _normalize_text_field(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _clean_line(str(value))
    return cleaned or None


def _normalize_identity(value: dict[str, Any] | None) -> dict[str, Any]:
    identity = _default_identity()
    raw = value or {}
    identity["full_name"] = _normalize_text_field(raw.get("full_name"))
    identity["headline"] = _normalize_text_field(raw.get("headline"))
    identity["summary"] = _normalize_text_field(raw.get("summary"))
    identity["location"] = _normalize_text_field(raw.get("location"))
    identity["emails"] = _unique_strings([str(item) for item in raw.get("emails", [])])
    identity["phones"] = _unique_strings([str(item) for item in raw.get("phones", [])])
    return identity


def _normalize_source_document(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": _normalize_text_field(item.get("document_id")) or "",
        "filename": _normalize_text_field(item.get("filename")) or "Unknown document",
        "created_at": _normalize_text_field(item.get("created_at")),
        "signals": _unique_strings([str(signal) for signal in item.get("signals", [])]),
    }


def _normalize_item_list(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        normalized_item = {
            "title": _normalize_text_field(item.get("title")),
            "organization": _normalize_text_field(item.get("organization")),
            "institution": _normalize_text_field(item.get("institution")),
            "degree": _normalize_text_field(item.get("degree")),
            "field_of_study": _normalize_text_field(item.get("field_of_study")),
            "name": _normalize_text_field(item.get("name")),
            "issuer": _normalize_text_field(item.get("issuer")),
            "location": _normalize_text_field(item.get("location")),
            "start_date": _normalize_text_field(item.get("start_date")),
            "end_date": _normalize_text_field(item.get("end_date")),
            "summary": _normalize_text_field(item.get("summary")),
            "credential_id": _normalize_text_field(item.get("credential_id")),
            "technologies": _unique_strings([str(value) for value in item.get("technologies", [])]),
            "highlights": _unique_strings([str(value) for value in item.get("highlights", [])]),
            "links": _unique_strings([str(value) for value in item.get("links", [])]),
            "source_document_ids": _unique_strings([str(value) for value in item.get("source_document_ids", [])]),
        }

        if kind == "education":
            key_fields = [
                normalized_item["institution"],
                normalized_item["degree"],
                normalized_item["field_of_study"],
            ]
        elif kind == "work_experience":
            key_fields = [
                normalized_item["title"],
                normalized_item["organization"],
                normalized_item["start_date"],
                normalized_item["end_date"],
            ]
        elif kind == "projects":
            key_fields = [
                normalized_item["name"],
                normalized_item["summary"],
            ]
        else:
            key_fields = [
                normalized_item["name"],
                normalized_item["issuer"],
                normalized_item["credential_id"],
            ]

        if not any(key_fields):
            continue
        normalized.append(normalized_item)
    return normalized


def _normalize_overview_data(value: dict[str, Any] | None) -> dict[str, Any]:
    data = _default_overview_data()
    raw = value or {}
    data["identity"] = _normalize_identity(raw.get("identity"))
    data["skills"] = _unique_strings([str(item) for item in raw.get("skills", [])])
    data["public_profiles"] = _unique_links(list(raw.get("public_profiles", [])))
    data["education"] = _normalize_item_list(list(raw.get("education", [])), "education")
    data["work_experience"] = _normalize_item_list(list(raw.get("work_experience", [])), "work_experience")
    data["projects"] = _normalize_item_list(list(raw.get("projects", [])), "projects")
    data["certifications"] = _normalize_item_list(list(raw.get("certifications", [])), "certifications")
    data["source_documents"] = [
        normalized
        for normalized in (_normalize_source_document(item) for item in raw.get("source_documents", []))
        if normalized["document_id"]
    ]
    data["auto_updated_at"] = _normalize_text_field(raw.get("auto_updated_at"))
    return data


def _normalize_profile_container(value: dict[str, Any] | None) -> dict[str, Any]:
    container = _default_profile_container()
    raw = value or {}
    container["auto"] = _normalize_overview_data(raw.get("auto"))
    manual = raw.get("manual") or {}
    normalized_manual: dict[str, Any] = {}
    if "identity" in manual:
        normalized_manual["identity"] = _normalize_identity(manual.get("identity"))
    if "skills" in manual:
        normalized_manual["skills"] = _unique_strings([str(item) for item in manual.get("skills", [])])
    if "public_profiles" in manual:
        normalized_manual["public_profiles"] = _unique_links(list(manual.get("public_profiles", [])))
    container["manual"] = normalized_manual
    return container


def profile_overview_payload(profile: Profile, user: User | None = None) -> dict[str, Any]:
    container = _normalize_profile_container(profile.profile_data)
    auto = container["auto"]
    manual = container["manual"]

    identity = auto["identity"]
    if "identity" in manual:
        manual_identity = manual["identity"]
        for key, value in manual_identity.items():
            if value is not None or key in {"emails", "phones"}:
                identity[key] = value
    if not identity["full_name"] and user is not None:
        identity["full_name"] = user.full_name

    skills = manual["skills"] if "skills" in manual else auto["skills"]
    public_profiles = manual["public_profiles"] if "public_profiles" in manual else auto["public_profiles"]

    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "identity": identity,
        "skills": skills,
        "public_profiles": public_profiles,
        "education": auto["education"],
        "work_experience": auto["work_experience"],
        "projects": auto["projects"],
        "certifications": auto["certifications"],
        "source_documents": auto["source_documents"],
        "documents_total": len(auto["source_documents"]),
        "auto_updated_at": auto["auto_updated_at"],
        "updated_at": profile.updated_at,
    }


def _canonical_section_heading(line: str) -> str | None:
    lowered = line.strip().lower().rstrip(":")
    if lowered in GENERIC_HEADINGS:
        for canonical, aliases in SECTION_ALIASES.items():
            if lowered in aliases:
                return canonical
    return None


def _split_resume_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    preamble: list[str] = []
    sections: dict[str, list[str]] = defaultdict(list)
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            if current_section is not None:
                sections[current_section].append("")
            elif preamble:
                preamble.append("")
            continue

        canonical = None
        if SECTION_HEADING_PATTERN.match(line):
            canonical = _canonical_section_heading(line)

        if canonical:
            current_section = canonical
            continue

        if current_section is None:
            preamble.append(line)
        else:
            sections[current_section].append(line)

    return preamble, sections


def _split_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _classify_link(url: str) -> str:
    lowered = url.lower()
    if "linkedin" in lowered:
        return "LinkedIn"
    if "github" in lowered:
        return "GitHub"
    if "huggingface" in lowered:
        return "Hugging Face"
    if "leetcode" in lowered:
        return "LeetCode"
    if "x.com" in lowered or "twitter.com" in lowered:
        return "X"
    return "Portfolio"


def _looks_like_name(line: str) -> bool:
    words = [word.strip(".,") for word in re.split(r"\s+", line) if word]
    if len(words) < 2 or len(words) > 5:
        return False
    if any(any(character.isdigit() for character in word) for word in words):
        return False
    if any("@" in word or "http" in word.lower() for word in words):
        return False
    lowered = line.lower()
    if lowered in GENERIC_HEADINGS:
        return False
    return all(
        re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", word) is not None and (word.isupper() or word[:1].isupper())
        for word in words
    )


def _extract_name(lines: list[str]) -> str | None:
    for line in lines[:4]:
        for segment in _split_contact_segments(line) or [line]:
            if _looks_like_name(segment):
                return segment
    return None


def _guess_headline(lines: list[str]) -> str | None:
    candidates: list[str] = []
    for line in lines[:8]:
        candidates.extend(_split_contact_segments(line) or [line])
    for candidate in candidates:
        if not candidate:
            continue
        if EMAIL_PATTERN.search(candidate) or PHONE_PATTERN.search(candidate) or URL_PATTERN.search(candidate):
            continue
        if _looks_like_name(candidate):
            continue
        if LOCATION_PATTERN.search(candidate):
            continue
        if DATE_RANGE_PATTERN.search(candidate):
            continue
        if _canonical_section_heading(candidate):
            continue
        if len(candidate) <= 90:
            return candidate
    return None


def _guess_location(lines: list[str]) -> str | None:
    for line in lines[:6]:
        for segment in _split_contact_segments(line) or [line]:
            if LOCATION_PATTERN.search(segment):
                return segment
            if "," in segment and not EMAIL_PATTERN.search(segment) and not URL_PATTERN.search(segment):
                return segment
    return None


def _collect_urls(text: str) -> list[dict[str, str]]:
    urls = [_normalize_url(match.group(0)) for match in URL_PATTERN.finditer(text)]
    return _unique_links([{"label": _classify_link(url), "url": url} for url in urls])


def _parse_skill_section(lines: list[str], text: str) -> list[str]:
    extracted: list[str] = []
    for line in lines:
        if not line:
            continue
        for token in re.split(r"[|,/·•]+", line):
            cleaned = _clean_line(token)
            if 1 < len(cleaned) <= 32 and cleaned.lower() not in GENERIC_HEADINGS:
                extracted.append(cleaned)
    extracted.extend(extract_skills(text))
    return _unique_strings(extracted)


def _extract_summary(preamble: list[str], sections: dict[str, list[str]]) -> str | None:
    summary_lines = [line for line in sections.get("summary", []) if line]
    if summary_lines:
        return _clean_line(" ".join(summary_lines[:4]))
    for line in preamble:
        if len(line) >= 70 and not EMAIL_PATTERN.search(line):
            return line
    return None


def _parse_role_and_org(header: str, block_lines: list[str]) -> tuple[str | None, str | None]:
    candidates = [header, *block_lines[1:3]]
    role = None
    organization = None

    separators = [" | ", " - ", " @ ", " at "]
    for line in candidates:
        for separator in separators:
            if separator in line:
                left, right = [part.strip() for part in line.split(separator, 1)]
                if ROLE_PATTERN.search(left):
                    return left, right
                if ROLE_PATTERN.search(right):
                    return right, left

    for line in candidates:
        if role is None and ROLE_PATTERN.search(line):
            role = line
            continue
        if organization is None and not ROLE_PATTERN.search(line):
            organization = line
    return role, organization


def _extract_date_range(text: str) -> tuple[str | None, str | None]:
    match = DATE_RANGE_PATTERN.search(text)
    if not match:
        return None, None
    value = match.group(0)
    parts = re.split(r"\s*[-–to]+\s*", value, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return value.strip(), None


def _extract_location_from_block(block: list[str]) -> str | None:
    for line in block[:4]:
        if EMAIL_PATTERN.search(line) or URL_PATTERN.search(line):
            continue
        if LOCATION_PATTERN.search(line):
            return line
        if "," in line and not ROLE_PATTERN.search(line):
            return line
    return None


def _parse_work_experience(lines: list[str], document_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        joined = " ".join(block)
        if not ROLE_PATTERN.search(joined):
            continue
        if len(block[0]) > 120:
            continue
        title, organization = _parse_role_and_org(block[0], block)
        start_date, end_date = _extract_date_range(joined)
        if not title and not organization:
            continue
        if not start_date and len(block) < 2 and len(joined) < 80:
            continue
        highlights = [line.lstrip("-•* ").strip() for line in block[1:] if line and line != organization]
        items.append(
            {
                "title": title,
                "organization": organization,
                "location": _extract_location_from_block(block),
                "start_date": start_date,
                "end_date": end_date,
                "summary": _clean_line(" ".join(highlights[:2])) if highlights else None,
                "highlights": highlights,
                "source_document_ids": [document_id],
            }
        )
    return _normalize_item_list(items, "work_experience")


def _parse_education(lines: list[str], document_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        joined = " ".join(block)
        if not (INSTITUTION_PATTERN.search(joined) or DEGREE_PATTERN.search(joined)):
            continue
        institution = next((line for line in block if INSTITUTION_PATTERN.search(line)), block[0] if block else None)
        degree_line = next((line for line in block if DEGREE_PATTERN.search(line)), None)
        start_date, end_date = _extract_date_range(joined)
        field = None
        if degree_line:
            field_match = re.search(r"\b(?:in|with a focus on)\s+(.+)$", degree_line, flags=re.IGNORECASE)
            if field_match:
                field = _clean_line(field_match.group(1))
        items.append(
            {
                "institution": institution,
                "degree": degree_line,
                "field_of_study": field,
                "start_date": start_date,
                "end_date": end_date,
                "summary": _clean_line(" ".join(line for line in block[1:] if line not in {institution, degree_line})),
                "source_document_ids": [document_id],
            }
        )
    return _normalize_item_list(items, "education")


def _parse_projects(lines: list[str], document_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        if not block:
            continue
        joined = " ".join(block)
        header = block[0].lstrip("-•* ").strip()
        technologies = extract_skills(joined)
        links = [_normalize_url(match.group(0)) for match in URL_PATTERN.finditer(joined)]
        header_like_project = (
            len(header) <= 96
            and not ROLE_PATTERN.search(header)
            and not INSTITUTION_PATTERN.search(header)
            and not _canonical_section_heading(header)
        )
        if not (
            PROJECT_PATTERN.search(joined)
            or any(domain in joined.lower() for domain in ("github", "gitlab", "huggingface", "portfolio", "demo"))
            or (header_like_project and technologies and len(block) >= 2)
        ):
            continue
        summary_lines = [line.lstrip("-•* ").strip() for line in block[1:] if line]
        items.append(
            {
                "name": header,
                "summary": _clean_line(" ".join(summary_lines[:2])) if summary_lines else None,
                "technologies": technologies,
                "links": links,
                "source_document_ids": [document_id],
            }
        )
    return _normalize_item_list(items, "projects")


def _parse_certifications(lines: list[str], document_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        if not block:
            continue
        joined = " ".join(block)
        if not CERTIFICATION_PATTERN.search(joined):
            continue
        start_date, _ = _extract_date_range(joined)
        items.append(
            {
                "name": block[0],
                "issuer": block[1] if len(block) > 1 else None,
                "start_date": start_date,
                "credential_id": next((line for line in block if "credential" in line.lower()), None),
                "summary": _clean_line(" ".join(block[1:3])),
                "source_document_ids": [document_id],
            }
        )
    return _normalize_item_list(items, "certifications")


def heuristic_extract_profile_insights(text: str, filename: str, document_id: str) -> dict[str, Any]:
    preamble, sections = _split_resume_sections(text)
    all_lines = [line for line in (_clean_line(raw_line) for raw_line in text.splitlines()) if line]
    filename_lower = filename.lower()

    identity = _default_identity()
    preamble_non_empty = [line for line in preamble if line]
    identity["full_name"] = _extract_name(preamble_non_empty) or _extract_name(all_lines)
    identity["headline"] = _guess_headline(preamble_non_empty[1:6] or all_lines[:6])
    identity["summary"] = _extract_summary(preamble_non_empty, sections)
    identity["location"] = _guess_location(preamble_non_empty or all_lines[:6])
    identity["emails"] = _unique_strings([match.group(0) for match in EMAIL_PATTERN.finditer(text)])
    identity["phones"] = _unique_strings([_clean_line(match.group(0)) for match in PHONE_PATTERN.finditer(text)])

    skills = _parse_skill_section(sections.get("skills", []), text)
    public_profiles = _collect_urls(text)
    work_experience = _parse_work_experience(sections.get("work_experience", []) or all_lines, document_id)
    education = _parse_education(sections.get("education", []) or all_lines, document_id)
    project_lines = sections.get("projects", [])
    if not project_lines and any(token in filename_lower for token in ("project", "portfolio", "readme", "case-study", "case_study")):
        project_lines = all_lines
    projects = _parse_projects(project_lines or [], document_id)
    certification_lines = sections.get("certifications", [])
    if not certification_lines and CERTIFICATION_PATTERN.search(text):
        certification_lines = all_lines
    certifications = _parse_certifications(certification_lines or [], document_id)

    if not identity["headline"] and work_experience:
        first_role = work_experience[0]
        identity["headline"] = " · ".join(
            part for part in (first_role.get("title"), first_role.get("organization")) if part
        ) or None

    if not identity["summary"]:
        summary_candidates = [item.get("summary") for item in work_experience[:2]] + [item.get("summary") for item in projects[:2]]
        identity["summary"] = next((candidate for candidate in summary_candidates if candidate), None)

    insights = {
        "identity": identity,
        "skills": skills,
        "public_profiles": public_profiles,
        "education": education,
        "work_experience": work_experience,
        "projects": projects,
        "certifications": certifications,
    }
    return _normalize_overview_data(insights)


def llm_extract_profile_insights(text: str, filename: str, document_id: str, settings: Settings) -> dict[str, Any]:
    client = OpenAI(api_key=settings.openai_api_key)
    prompt_text = text[:14000]

    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract structured resume/profile information from evidence. "
                    "Use only details explicitly supported by the text. "
                    "Return JSON with keys: identity, skills, public_profiles, education, work_experience, projects, certifications. "
                    "identity must include full_name, headline, summary, location, emails, phones. "
                    "For work_experience use title, organization, location, start_date, end_date, summary, highlights. "
                    "For education use institution, degree, field_of_study, start_date, end_date, summary. "
                    "For projects use name, summary, technologies, links. "
                    "For certifications use name, issuer, start_date, credential_id, summary. "
                    "Do not invent values. Use empty arrays when absent."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "filename": filename,
                        "document_id": document_id,
                        "text": prompt_text,
                    }
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    normalized = _normalize_overview_data(parsed)

    for key in ("education", "work_experience", "projects", "certifications"):
        for item in normalized[key]:
            item["source_document_ids"] = _unique_strings([*item.get("source_document_ids", []), document_id])

    return normalized


def extract_document_profile_insights(
    document: Document,
    settings: Settings,
    parser_backend: str | None = None,
) -> tuple[dict[str, Any], str, list[str], dict[str, Any]]:
    warnings: list[str] = []
    diagnostics: dict[str, Any] = {}
    resolved_backend = resolve_resume_parser_backend(
        settings,
        requested_backend=parser_backend,
        document=document,
    )

    try:
        insights, mode, parser_warnings, diagnostics, backend = parse_resume_with_backend(
            document,
            settings,
            requested_backend=parser_backend,
        )
        warnings.extend(parser_warnings)
        diagnostics["parser_backend"] = backend
        return _normalize_overview_data(insights), mode, warnings, diagnostics
    except ValueError:
        raise
    except Exception as exc:
        warnings.append(
            f"Structured resume parser failed with {exc.__class__.__name__}; falling back to the legacy extractor."
        )

    mode = "heuristic"

    if settings.enable_llm_extractor and settings.openai_api_key:
        try:
            insights = llm_extract_profile_insights(
                text=document.extracted_text,
                filename=document.filename,
                document_id=document.id,
                settings=settings,
            )
            mode = "llm"
            diagnostics = {
                "parser_backend": resolved_backend,
                "layout": {"parser": document.parse_metadata.get("parser")},
                "validation": {
                    "score": 55,
                    "status": "legacy",
                    "warnings": ["Legacy document-wide LLM extraction was used as a fallback."],
                    "checks": [],
                    "detected_sections": {},
                },
            }
            return insights, mode, warnings, diagnostics
        except Exception as exc:
            warnings.append(f"Structured LLM profile extraction failed with {exc.__class__.__name__}; heuristic extraction was used instead.")

    insights = heuristic_extract_profile_insights(
        text=document.extracted_text,
        filename=document.filename,
        document_id=document.id,
    )
    diagnostics = {
        "parser_backend": resolved_backend,
        "layout": {"parser": document.parse_metadata.get("parser")},
        "validation": {
            "score": 40,
            "status": "legacy",
            "warnings": ["Legacy heuristic extraction was used as a fallback."],
            "checks": [],
            "detected_sections": {},
        },
    }
    return insights, mode, warnings, diagnostics


def _identity_score(identity: dict[str, Any]) -> int:
    score = 0
    if identity.get("full_name"):
        score += 4
    if identity.get("headline"):
        score += 3
    if identity.get("summary"):
        score += 3
    if identity.get("location"):
        score += 1
    score += min(2, len(identity.get("emails", [])))
    score += min(2, len(identity.get("phones", [])))
    return score


def _pick_identity_text(existing: str | None, candidate: str | None, *, field: str) -> str | None:
    if not candidate:
        return existing
    if not existing:
        return candidate

    def score(value: str) -> tuple[int, int]:
        normalized = _clean_line(value)
        if field == "full_name":
            return (3 if _looks_like_name(normalized) else 1, -len(normalized))
        if field == "headline":
            return (
                3 if ROLE_PATTERN.search(normalized) else 1,
                len(normalized),
            )
        if field == "summary":
            return (
                3 if len(normalized) >= 60 else 1,
                len(normalized),
            )
        if field == "location":
            return (
                3 if LOCATION_PATTERN.search(normalized) or "," in normalized else 1,
                len(normalized),
            )
        return (1, len(normalized))

    return candidate if score(candidate) > score(existing) else existing


def _merge_identity(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    merged = _normalize_identity(target)
    normalized_source = _normalize_identity(source)
    for field in ("full_name", "headline", "summary", "location"):
        merged[field] = _pick_identity_text(merged.get(field), normalized_source.get(field), field=field)
    merged["emails"] = _unique_strings([*merged.get("emails", []), *normalized_source.get("emails", [])])
    merged["phones"] = _unique_strings([*merged.get("phones", []), *normalized_source.get("phones", [])])
    return merged


def _merge_item_dict(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for field in ("title", "organization", "institution", "degree", "field_of_study", "name", "issuer", "location", "start_date", "end_date", "credential_id"):
        if not merged.get(field) and source.get(field):
            merged[field] = source[field]
    if source.get("summary") and (not merged.get("summary") or len(source["summary"]) > len(merged["summary"])):
        merged["summary"] = source["summary"]
    merged["technologies"] = _unique_strings([*merged.get("technologies", []), *source.get("technologies", [])])
    merged["highlights"] = _unique_strings([*merged.get("highlights", []), *source.get("highlights", [])])
    merged["links"] = _unique_strings([*merged.get("links", []), *source.get("links", [])])
    merged["source_document_ids"] = _unique_strings([*merged.get("source_document_ids", []), *source.get("source_document_ids", [])])
    return merged


def _merge_item_collection(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    merged_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        if kind == "education":
            key_parts = [item.get("institution"), item.get("degree"), item.get("field_of_study")]
        elif kind == "work_experience":
            key_parts = [item.get("title"), item.get("organization"), item.get("start_date"), item.get("end_date")]
        elif kind == "projects":
            key_parts = [item.get("name"), item.get("summary")]
        else:
            key_parts = [item.get("name"), item.get("issuer"), item.get("credential_id")]
        key = "|".join((part or "").lower() for part in key_parts if part)
        if not key:
            key = json.dumps(item, sort_keys=True).lower()
        existing = merged_by_key.get(key)
        merged_by_key[key] = _merge_item_dict(existing or {}, item) if existing else dict(item)
    return list(merged_by_key.values())


def rebuild_profile_overview(session: Session, profile: Profile, settings: Settings) -> dict[str, Any]:
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.profile_id == profile.id)
            .order_by(Document.created_at.asc())
        ).all()
    )

    auto = _default_overview_data()
    collected_education: list[dict[str, Any]] = []
    collected_work: list[dict[str, Any]] = []
    collected_projects: list[dict[str, Any]] = []
    collected_certifications: list[dict[str, Any]] = []

    merged_identity = _default_identity()

    for document in documents:
        parse_metadata = dict(document.parse_metadata or {})
        insights = parse_metadata.get("profile_insights")
        if not isinstance(insights, dict):
            insights, extraction_mode, warnings, diagnostics = extract_document_profile_insights(document, settings)
            parse_metadata["profile_insights"] = insights
            parse_metadata["profile_extraction_mode"] = extraction_mode
            parse_metadata["profile_extraction_warnings"] = warnings
            parse_metadata["profile_validation"] = diagnostics.get("validation", {})
            parse_metadata["profile_parser_diagnostics"] = diagnostics
            document.parse_metadata = parse_metadata
        normalized = _normalize_overview_data(insights)

        merged_identity = _merge_identity(merged_identity, normalized["identity"])

        auto["skills"] = _unique_strings([*auto["skills"], *normalized["skills"]])
        auto["public_profiles"] = _unique_links([*auto["public_profiles"], *normalized["public_profiles"]])
        collected_education.extend(normalized["education"])
        collected_work.extend(normalized["work_experience"])
        collected_projects.extend(normalized["projects"])
        collected_certifications.extend(normalized["certifications"])
        auto["source_documents"].append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "created_at": document.created_at.isoformat() if document.created_at else None,
                "signals": [
                    key
                    for key in ("identity", "skills", "education", "work_experience", "projects", "certifications")
                    if (normalized["identity"] if key == "identity" else normalized.get(key))
                    and (
                        key != "identity"
                        or any(normalized["identity"].get(field) for field in ("full_name", "headline", "summary", "emails", "phones"))
                    )
                ],
            }
        )

    auto["identity"] = merged_identity
    auto["education"] = _merge_item_collection(collected_education, "education")
    auto["work_experience"] = _merge_item_collection(collected_work, "work_experience")
    auto["projects"] = _merge_item_collection(collected_projects, "projects")
    auto["certifications"] = _merge_item_collection(collected_certifications, "certifications")
    auto["auto_updated_at"] = dt.datetime.now(dt.UTC).isoformat()

    container = _normalize_profile_container(profile.profile_data)
    container["auto"] = auto
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.flush()

    return profile_overview_payload(profile, profile.user)


def update_manual_profile_overrides(
    session: Session,
    profile: Profile,
    *,
    identity: dict[str, Any] | None = None,
    skills: list[str] | None = None,
    public_profiles: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    container = _normalize_profile_container(profile.profile_data)
    manual = dict(container["manual"])

    if identity is not None:
        manual["identity"] = _normalize_identity(identity)
    if skills is not None:
        manual["skills"] = _unique_strings(skills)
    if public_profiles is not None:
        manual["public_profiles"] = _unique_links(public_profiles)

    container["manual"] = manual
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.commit()
    session.refresh(profile)
    return profile_overview_payload(profile, profile.user)


def reset_manual_profile_overrides(session: Session, profile: Profile) -> dict[str, Any]:
    container = _normalize_profile_container(profile.profile_data)
    container["manual"] = {}
    profile.profile_data = container
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.commit()
    session.refresh(profile)
    return profile_overview_payload(profile, profile.user)
