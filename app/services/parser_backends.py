from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from app.config import Settings
from app.models import Document
from app.services.docling_resume_parser import parse_resume_document_with_docling
from app.services.resume_parser import parse_resume_document


PARSER_AUTO = "auto"
PARSER_LAYOUT_NER = "layout_ner"
PARSER_DOCLING_STRUCTURED = "docling_structured"

_BACKEND_DEFINITIONS = {
    PARSER_LAYOUT_NER: {
        "label": "Layout + NER",
        "description": "PyMuPDF layout parsing with the local resume NER and formatter pipeline.",
    },
    PARSER_DOCLING_STRUCTURED: {
        "label": "Docling Structured",
        "description": "Docling section extraction with the same resume NER and formatter pipeline.",
    },
}


def _docling_available() -> bool:
    return find_spec("docling") is not None


def _looks_like_pdf_or_image(
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    parser_name: str | None = None,
) -> bool:
    suffix = ""
    if filename:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mime = (mime_type or "").lower()
    parser = (parser_name or "").lower()
    image_suffixes = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
    return (
        suffix == "pdf"
        or suffix in image_suffixes
        or mime == "application/pdf"
        or mime.startswith("image/")
        or "pdf" in parser
        or "ocr" in parser
    )


def resume_parser_backends(settings: Settings) -> list[dict[str, Any]]:
    default_backend = settings.resume_parser_backend if settings.resume_parser_backend in _BACKEND_DEFINITIONS else PARSER_LAYOUT_NER
    backends: list[dict[str, Any]] = []
    for backend_id, metadata in _BACKEND_DEFINITIONS.items():
        available = backend_id != PARSER_DOCLING_STRUCTURED or _docling_available()
        backends.append(
            {
                "id": backend_id,
                "label": metadata["label"],
                "description": metadata["description"],
                "available": available,
                "is_default": backend_id == default_backend,
            }
        )
    if not any(item["available"] and item["is_default"] for item in backends):
        for item in backends:
            if item["id"] == PARSER_LAYOUT_NER:
                item["is_default"] = True
    return backends


def validate_resume_parser_choice(settings: Settings, parser_choice: str | None) -> str | None:
    if not parser_choice:
        return None
    if parser_choice == PARSER_AUTO:
        return PARSER_AUTO

    backends = resume_parser_backends(settings)
    known_backend_ids = {item["id"] for item in backends}
    available_backend_ids = {item["id"] for item in backends if item["available"]}
    if parser_choice not in known_backend_ids:
        raise ValueError(f"Unknown resume parser backend: {parser_choice}")
    if parser_choice not in available_backend_ids:
        raise ValueError(f"Resume parser backend is not available: {parser_choice}")
    return parser_choice


def recommend_resume_parser_backend(
    settings: Settings,
    *,
    document: Document | None = None,
    filename: str | None = None,
    mime_type: str | None = None,
    parser_name: str | None = None,
) -> str:
    candidate_filename = filename
    candidate_mime_type = mime_type
    candidate_parser_name = parser_name
    if document is not None:
        candidate_filename = candidate_filename or document.filename or document.storage_path
        candidate_mime_type = candidate_mime_type or document.mime_type
        candidate_parser_name = candidate_parser_name or (document.parse_metadata or {}).get("parser")

    if _looks_like_pdf_or_image(
        filename=candidate_filename,
        mime_type=candidate_mime_type,
        parser_name=candidate_parser_name,
    ):
        for item in resume_parser_backends(settings):
            if item["id"] == PARSER_DOCLING_STRUCTURED and item["available"]:
                return PARSER_DOCLING_STRUCTURED
    return PARSER_LAYOUT_NER


def resolve_resume_parser_backend(
    settings: Settings,
    *,
    requested_backend: str | None = None,
    document: Document | None = None,
) -> str:
    backends = resume_parser_backends(settings)
    available_backend_ids = {item["id"] for item in backends if item["available"]}

    if requested_backend:
        parser_choice = validate_resume_parser_choice(settings, requested_backend)
        if parser_choice and parser_choice != PARSER_AUTO:
            return parser_choice

    document_backend = None
    if document is not None:
        document_backend = (document.parse_metadata or {}).get("profile_parser_backend")
    if document_backend in available_backend_ids:
        return str(document_backend)

    configured_backend = settings.resume_parser_backend
    if configured_backend == PARSER_AUTO:
        return recommend_resume_parser_backend(settings, document=document)
    if configured_backend in available_backend_ids:
        return configured_backend

    return recommend_resume_parser_backend(settings, document=document)


def parse_resume_with_backend(
    document: Document,
    settings: Settings,
    *,
    requested_backend: str | None = None,
) -> tuple[dict[str, Any], str, list[str], dict[str, Any], str]:
    backend = resolve_resume_parser_backend(settings, requested_backend=requested_backend, document=document)
    if backend == PARSER_DOCLING_STRUCTURED:
        insights, mode, warnings, diagnostics = parse_resume_document_with_docling(document, settings)
    else:
        insights, mode, warnings, diagnostics = parse_resume_document(document, settings)
    diagnostics = {
        **diagnostics,
        "parser_backend": backend,
        "parser_backend_label": _BACKEND_DEFINITIONS[backend]["label"],
    }
    return insights, mode, warnings, diagnostics, backend


def parser_run_summary(insights: dict[str, Any]) -> dict[str, Any]:
    identity = insights.get("identity", {})
    return {
        "full_name": identity.get("full_name"),
        "headline": identity.get("headline"),
        "emails": identity.get("emails", []),
        "phones": identity.get("phones", []),
        "links": [item.get("url") for item in insights.get("public_profiles", []) if item.get("url")],
        "work_count": len(insights.get("work_experience", [])),
        "project_count": len(insights.get("projects", [])),
        "education_count": len(insights.get("education", [])),
        "skill_count": len(insights.get("skills", [])),
        "work_titles": [
            " @ ".join(part for part in (item.get("title"), item.get("organization")) if part)
            for item in insights.get("work_experience", [])
        ],
        "project_names": [item.get("name") for item in insights.get("projects", [])],
        "education_institutions": [item.get("institution") for item in insights.get("education", [])],
        "top_skills": list(insights.get("skills", [])[:10]),
    }


def compare_resume_parser_backends(
    document: Document,
    settings: Settings,
    *,
    requested_backends: list[str] | None = None,
) -> dict[str, Any]:
    available_backends = resume_parser_backends(settings)
    active_backend = resolve_resume_parser_backend(settings, document=document)
    requested = requested_backends or [item["id"] for item in available_backends if item["available"]]
    comparisons: list[dict[str, Any]] = []

    backend_map = {item["id"]: item for item in available_backends}
    for backend in requested:
        metadata = backend_map.get(backend)
        if metadata is None:
            comparisons.append(
                {
                    "backend": backend,
                    "label": backend,
                    "description": "Unknown parser backend.",
                    "mode": None,
                    "warnings": [],
                    "summary": {},
                    "insights": {},
                    "diagnostics": {},
                    "error": f"Unknown resume parser backend: {backend}",
                }
            )
            continue
        if not metadata["available"]:
            comparisons.append(
                {
                    "backend": backend,
                    "label": metadata["label"],
                    "description": metadata["description"],
                    "mode": None,
                    "warnings": [],
                    "summary": {},
                    "insights": {},
                    "diagnostics": {},
                    "error": f"{metadata['label']} is not available in this environment.",
                }
            )
            continue

        try:
            insights, mode, warnings, diagnostics, resolved_backend = parse_resume_with_backend(
                document,
                settings,
                requested_backend=backend,
            )
            comparisons.append(
                {
                    "backend": resolved_backend,
                    "label": metadata["label"],
                    "description": metadata["description"],
                    "mode": mode,
                    "warnings": warnings,
                    "summary": parser_run_summary(insights),
                    "insights": insights,
                    "diagnostics": diagnostics,
                    "error": None,
                }
            )
        except Exception as exc:
            comparisons.append(
                {
                    "backend": backend,
                    "label": metadata["label"],
                    "description": metadata["description"],
                    "mode": None,
                    "warnings": [],
                    "summary": {},
                    "insights": {},
                    "diagnostics": {},
                    "error": f"{metadata['label']} failed with {exc.__class__.__name__}.",
                }
            )

    return {
        "active_backend": active_backend,
        "available_backends": available_backends,
        "comparisons": comparisons,
    }
