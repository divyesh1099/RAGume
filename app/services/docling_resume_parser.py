from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import Document
from app.services.pdf_layout import extract_pdf_layout
from app.services.resume_parser import (
    DATE_RANGE_PATTERN,
    INSTITUTION_PATTERN,
    ROLE_WORD_PATTERN,
    _build_validation,
    _canonical_section_heading,
    _clean_multiline_text,
    _clean_text,
    _coerce_schema,
    _collect_skills,
    _gpt_format_resume_json,
    _identity_from_header,
    _parse_certifications,
    _parse_education,
    _parse_projects,
    _parse_work_experience,
    _run_resume_ner,
    _unique_strings,
    _visible_url_links,
)


_PROJECT_DESCRIPTION_PREFIXES = (
    "this ",
    "it ",
    "implemented",
    "created",
    "deployed",
    "refactored",
    "integrated",
    "used ",
    "project built",
    "routing implemented",
    "crud implementation",
    "assits",
    "machine learning",
    "repository",
    "here is",
    "azure deployment",
    "ef core",
    "wix",
    "razorpay",
    "google maps",
    "canva",
    "adobe ",
    "nbpgames.com",
    "badboystyle.",
    "shreeaccountax.",
    "worked on",
    "designed",
    "building",
    "built ",
)
_SOCIAL_LOCATION_FRAGMENTS = ("github", "linkedin", "leetcode", "ithub", "eetcode")


def _strip_bullet(text: str) -> str:
    return re.sub(r"^[•\-*·]+\s*", "", _clean_text(text))


def _make_block(
    lines: list[str],
    *,
    is_bold: bool = False,
    link_uris: list[str] | None = None,
) -> dict[str, Any]:
    cleaned_lines = [_clean_text(line) for line in lines if _clean_text(line)]
    return {
        "text": "\n".join(cleaned_lines),
        "lines": cleaned_lines,
        "page": 0,
        "column": 0,
        "x0": 0.0,
        "y0": 0.0,
        "link_uris": list(link_uris or []),
        "max_font_size": 12.5 if is_bold else 11.0,
        "avg_font_size": 12.5 if is_bold else 11.0,
        "is_bold": is_bold,
    }


def _safe_layout(document: Document) -> dict[str, Any]:
    path = Path(document.storage_path)
    if path.suffix.lower() != ".pdf":
        return {
            "parser": document.parse_metadata.get("parser") or "plain_text",
            "page_count": document.parse_metadata.get("page_count"),
            "block_count": 0,
            "link_count": 0,
            "text": document.extracted_text,
            "pages": [],
            "links": [],
        }
    try:
        return extract_pdf_layout(path)
    except Exception:
        return {
            "parser": "docling_structured_fallback",
            "page_count": None,
            "block_count": 0,
            "link_count": 0,
            "text": document.extracted_text,
            "pages": [],
            "links": [],
        }


def _build_ephemeral_document(document: Document, extracted_text: str, parser: str) -> Document:
    working = Document(
        filename=document.filename,
        storage_path=document.storage_path,
        source_type=document.source_type,
        mime_type=document.mime_type,
        checksum=document.checksum,
        extracted_text=extracted_text,
        parse_metadata={**(document.parse_metadata or {}), "parser": parser},
        profile_id=document.profile_id,
    )
    working.id = document.id or f"{parser}:{Path(document.storage_path).stem}"
    return working


def _collect_docling_lines(docling_document: Any) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    header_lines: list[dict[str, Any]] = []
    section_lines: dict[str, list[dict[str, Any]]] = {}
    section_order: list[str] = []
    current_section: str | None = None

    for item, _level in docling_document.iterate_items():
        label = str(getattr(item, "label", "") or "")
        text = _clean_text(getattr(item, "text", "") or "")
        if not text:
            continue

        line = {
            "text": text,
            "label": label,
            "is_bold": label != "text",
        }
        if label == "section_header":
            canonical = _canonical_section_heading(text)
            if canonical:
                current_section = canonical
                section_lines.setdefault(canonical, [])
                if canonical not in section_order:
                    section_order.append(canonical)
                continue
            if current_section is None:
                header_lines.append({**line, "is_bold": True})
            else:
                section_lines.setdefault(current_section, []).append({**line, "is_bold": True})
            continue

        if current_section is None:
            header_lines.append(line)
        else:
            section_lines.setdefault(current_section, []).append(line)

    return header_lines, section_lines, section_order


def _group_header_blocks(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_make_block([line["text"]], is_bold=line.get("is_bold", False)) for line in raw_lines]


def _group_work_blocks(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []

    for raw_line in raw_lines:
        original = raw_line["text"]
        cleaned = _strip_bullet(original)
        if not cleaned:
            continue
        starts_entry = bool(
            DATE_RANGE_PATTERN.search(cleaned)
            and ROLE_WORD_PATTERN.search(cleaned)
            and not original.lstrip().startswith(("-", "•", "·", "*"))
        )
        if starts_entry and current_lines:
            blocks.append(_make_block(current_lines, is_bold=True))
            current_lines = [cleaned]
            continue
        current_lines.append(cleaned)

    if current_lines:
        blocks.append(_make_block(current_lines, is_bold=True))
    return blocks


def _looks_like_project_title(text: str) -> bool:
    plain = _strip_bullet(text).rstrip(":").strip()
    lowered = plain.lower()
    words = re.findall(r"[A-Za-z][A-Za-z0-9.+#-]*", plain)
    if not words or len(words) > 6:
        return False
    if plain.startswith("(") or "http" in lowered or "url" in lowered:
        return False
    if lowered.startswith(_PROJECT_DESCRIPTION_PREFIXES):
        return False
    if plain.endswith("."):
        return False
    titlecase_words = sum(1 for word in words if word[:1].isupper() or word.isupper())
    titlecase_ratio = titlecase_words / max(1, len(words))
    return text.rstrip().endswith(":") or titlecase_ratio >= 0.8


def _group_project_blocks(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []

    for raw_line in raw_lines:
        cleaned = _strip_bullet(raw_line["text"])
        if not cleaned:
            continue
        starts_project = _looks_like_project_title(raw_line["text"])
        if starts_project and current_lines:
            blocks.append(_make_block(current_lines, is_bold=True))
            current_lines = [cleaned.rstrip(":")]
            continue
        current_lines.append(cleaned.rstrip(":") if starts_project else cleaned)

    if current_lines:
        blocks.append(_make_block(current_lines, is_bold=True))
    return blocks


def _group_education_blocks(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []

    for raw_line in raw_lines:
        cleaned = _strip_bullet(raw_line["text"])
        if not cleaned:
            continue
        starts_entry = bool(current_lines and INSTITUTION_PATTERN.search(cleaned))
        if starts_entry:
            blocks.append(_make_block(current_lines, is_bold=True))
            current_lines = [cleaned]
            continue
        current_lines.append(cleaned)

    if current_lines:
        blocks.append(_make_block(current_lines, is_bold=True))
    return blocks


def _group_simple_blocks(raw_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _make_block([_strip_bullet(raw_line["text"])], is_bold=raw_line.get("is_bold", False))
        for raw_line in raw_lines
        if _strip_bullet(raw_line["text"])
    ]


def _cleanup_identity(identity: dict[str, Any]) -> dict[str, Any]:
    location = identity.get("location")
    if location:
        lowered = str(location).lower().replace(" ", "")
        if len(lowered) < 4 or any(fragment in lowered for fragment in _SOCIAL_LOCATION_FRAGMENTS):
            identity["location"] = None
    return identity


def parse_resume_document_with_docling(
    document: Document,
    settings: Settings,
) -> tuple[dict[str, Any], str, list[str], dict[str, Any]]:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:  # pragma: no cover - exercised manually
        raise RuntimeError(
            "Docling is not installed. Install it with "
            "`pip install docling --extra-index-url https://download.pytorch.org/whl/cpu`."
        ) from exc

    converter = DocumentConverter()
    docling_document = converter.convert(document.storage_path).document
    docling_text = docling_document.export_to_text()
    working_document = _build_ephemeral_document(document, docling_text, "docling_structured")
    layout = _safe_layout(working_document)

    header_lines, raw_sections, section_order = _collect_docling_lines(docling_document)
    section_blocks = {
        "__header__": _group_header_blocks(header_lines),
        "summary": _group_simple_blocks(raw_sections.get("summary", [])),
        "skills": _group_simple_blocks(raw_sections.get("skills", [])),
        "work_experience": _group_work_blocks(raw_sections.get("work_experience", [])),
        "education": _group_education_blocks(raw_sections.get("education", [])),
        "projects": _group_project_blocks(raw_sections.get("projects", [])),
        "certifications": _group_simple_blocks(raw_sections.get("certifications", [])),
    }

    warnings: list[str] = []
    ner_cache: dict[str, list[dict[str, Any]]] = {}

    def ner_for_text(text: str) -> list[dict[str, Any]]:
        cleaned = _clean_multiline_text(text)
        if not cleaned:
            return []
        if cleaned not in ner_cache:
            try:
                ner_cache[cleaned] = _run_resume_ner(cleaned, settings)
            except Exception as exc:
                warnings.append(f"Local resume NER failed with {exc.__class__.__name__}.")
                ner_cache[cleaned] = []
        return ner_cache[cleaned]

    work_experience = _parse_work_experience(section_blocks["work_experience"], working_document.id, ner_for_text)
    education = _parse_education(section_blocks["education"], working_document.id, ner_for_text)
    projects = _parse_projects(section_blocks["projects"], working_document.id, ner_for_text)
    certifications = _parse_certifications(section_blocks["certifications"], working_document.id, ner_for_text)

    draft = {
        "identity": _cleanup_identity(
            _identity_from_header(
                section_blocks["__header__"],
                layout,
                section_blocks,
                work_experience,
                ner_for_text,
            )
        ),
        "skills": _collect_skills(working_document, section_blocks, work_experience, projects, ner_for_text),
        "public_profiles": _visible_url_links(working_document, layout),
        "education": education,
        "work_experience": work_experience,
        "projects": projects,
        "certifications": certifications,
    }
    draft = _coerce_schema(draft, working_document.id)

    mode = "docling_ner_local"
    if settings.enable_resume_gpt_formatter and settings.openai_api_key:
        section_text_map = {
            key: "\n\n".join(block["text"] for block in blocks)
            for key, blocks in section_blocks.items()
            if blocks
        }
        try:
            refined = _gpt_format_resume_json(draft, section_text_map, settings, working_document)
            draft = _coerce_schema(refined, working_document.id)
            mode = "docling_ner_gpt"
        except Exception as exc:
            warnings.append(f"GPT resume formatter failed with {exc.__class__.__name__}; local formatter was used instead.")

    validation = _build_validation(draft, section_blocks, mode)
    diagnostics = {
        "section_order": section_order,
        "section_counts": {key: len(value) for key, value in section_blocks.items()},
        "docling": {
            "parser": "docling_structured",
            "header_line_count": len(header_lines),
            "raw_section_counts": {key: len(value) for key, value in raw_sections.items()},
        },
        "layout": {
            "parser": layout.get("parser"),
            "page_count": layout.get("page_count"),
            "block_count": layout.get("block_count"),
            "link_count": layout.get("link_count"),
        },
        "validation": validation,
    }
    return draft, mode, _unique_strings([*warnings, *validation["warnings"]]), diagnostics
