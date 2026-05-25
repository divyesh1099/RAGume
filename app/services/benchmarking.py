from __future__ import annotations

import ast
import csv
import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from rapidfuzz import fuzz

from app.config import Settings
from app.models import Document
from app.services.parser_backends import PARSER_AUTO
from app.services.parsing import compute_checksum, detect_mime_type, extract_text_from_path
from app.services.profile_memory import annotate_document_profile_metadata, extract_document_profile_insights


GOLD_JSON_FIELDS = {
    "gold_links_json": "links",
    "gold_skills_json": "skills",
    "gold_experience_json": "experience",
    "gold_education_json": "education",
    "gold_projects_json": "projects",
    "gold_certifications_json": "certifications",
    "gold_achievements_json": "achievements",
}

FIELD_LABELS = {
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "location": "Location",
    "summary": "Summary",
    "links": "Links",
    "skills": "Skills",
    "experience": "Experience",
    "education": "Education",
    "projects": "Projects",
    "certifications": "Certifications",
    "achievements": "Achievements",
}

FIELD_WEIGHTS = {
    "name": 0.25,
    "email": 0.3,
    "phone": 0.3,
    "location": 0.35,
    "summary": 0.5,
    "links": 0.55,
    "skills": 1.0,
    "experience": 1.2,
    "education": 0.95,
    "projects": 1.0,
    "certifications": 0.65,
    "achievements": 0.55,
}

FIELD_ORDER = [
    "name",
    "email",
    "phone",
    "location",
    "summary",
    "links",
    "skills",
    "experience",
    "education",
    "projects",
    "certifications",
    "achievements",
]

SCALAR_FIELDS = {"name", "email", "phone", "location", "summary"}
SET_FIELDS = {"links", "skills"}
RECORD_FIELDS = {"experience", "education", "projects", "certifications", "achievements"}

HOME_DATASET_CANDIDATE = Path.home() / "Downloads" / "ragume_benchmark_gold_v0"


def resolve_benchmark_dataset_dir(settings: Settings) -> Path | None:
    if settings.benchmark_dataset_dir:
        candidate = Path(settings.benchmark_dataset_dir).expanduser()
        return candidate
    if HOME_DATASET_CANDIDATE.exists():
        return HOME_DATASET_CANDIDATE
    return None


def _benchmark_reports_dir(settings: Settings) -> Path:
    return Path(settings.benchmark_reports_dir).expanduser()


def _safe_jsonish(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return default


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _normalize_text(value: str) -> str:
    compact = _normalize_whitespace(value).lower()
    compact = compact.replace("&", " and ")
    compact = re.sub(r"[^a-z0-9+#./ -]+", " ", compact)
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def _normalize_name(value: str) -> str:
    compact = _normalize_text(value)
    compact = re.sub(r"\b(?:mr|mrs|ms|dr|resume|curriculum|vitae)\b", " ", compact)
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if len(digits) > 10:
        return digits[-10:]
    return digits


def _normalize_url(value: str) -> str:
    raw = _normalize_whitespace(value)
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}"


def _normalize_skill(value: str) -> str:
    compact = _normalize_text(value)
    compact = compact.replace("node js", "node.js")
    compact = compact.replace("postgre sql", "postgresql")
    compact = compact.replace("fast api", "fastapi")
    compact = compact.replace("asp net", "asp.net")
    compact = compact.replace("react js", "reactjs")
    return compact.strip()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return max(
        fuzz.token_set_ratio(left, right),
        fuzz.token_sort_ratio(left, right),
        fuzz.partial_ratio(left, right),
    ) / 100.0


def _clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(float(value), 1.0))


def _status_from_score(score: float | None) -> str:
    if score is None:
        return "not_scored"
    if score >= 0.95:
        return "match"
    if score >= 0.75:
        return "close"
    return "miss"


def _nonempty_list(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _normalize_whitespace(str(value))
        if not cleaned:
            continue
        normalized = cleaned.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return result


def _scalar_gold_value(row: dict[str, str], field: str) -> str | None:
    key = f"gold_{field}"
    value = _normalize_whitespace(row.get(key, ""))
    return value or None


def _normalize_gold_row(row: dict[str, str]) -> dict[str, Any]:
    gold = {
        "name": _scalar_gold_value(row, "name"),
        "email": _scalar_gold_value(row, "email"),
        "phone": _scalar_gold_value(row, "phone"),
        "location": _scalar_gold_value(row, "location"),
        "summary": _scalar_gold_value(row, "summary"),
    }
    for csv_field, field_name in GOLD_JSON_FIELDS.items():
        parsed = _safe_jsonish(row.get(csv_field), [])
        if isinstance(parsed, list):
            gold[field_name] = parsed
        elif isinstance(parsed, dict):
            gold[field_name] = [parsed]
        else:
            gold[field_name] = []
    return gold


def _dataset_case_path(base_dir: Path, row: dict[str, str], manifest_by_resume: dict[str, dict[str, str]]) -> Path | None:
    manifest_row = manifest_by_resume.get(row.get("resume_id", ""))
    candidates: list[Path] = []
    if manifest_row:
        for key in ("local_pdf_path", "source_pdf_path"):
            raw = (manifest_row.get(key) or "").strip()
            if raw:
                candidates.append(Path(raw).expanduser())
    local_name = (row.get("local_pdf_name") or "").strip()
    if local_name:
        candidates.append(base_dir / "sample_pdfs" / local_name)
        candidates.append(base_dir / local_name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _load_manifest_rows(manifest_path: Path) -> dict[str, dict[str, str]]:
    if not manifest_path.exists():
        return {}
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {row.get("resume_id", ""): row for row in reader if row.get("resume_id")}


def load_benchmark_cases(settings: Settings) -> tuple[Path | None, list[dict[str, Any]]]:
    dataset_dir = resolve_benchmark_dataset_dir(settings)
    if dataset_dir is None or not dataset_dir.exists():
        return dataset_dir, []

    gold_path = dataset_dir / "gold_annotation_template.csv"
    manifest_path = dataset_dir / "sample_pdf_manifest.csv"
    if not gold_path.exists():
        return dataset_dir, []

    manifest_by_resume = _load_manifest_rows(manifest_path)
    cases: list[dict[str, Any]] = []
    with gold_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("resume_id"):
                continue
            file_path = _dataset_case_path(dataset_dir, row, manifest_by_resume)
            gold = _normalize_gold_row(row)
            cases.append(
                {
                    "resume_id": row["resume_id"],
                    "category": row.get("category") or "UNKNOWN",
                    "filename": row.get("local_pdf_name") or (file_path.name if file_path else "resume.pdf"),
                    "file_path": str(file_path) if file_path else "",
                    "review_status": row.get("review_status") or "",
                    "reviewer_notes": row.get("reviewer_notes") or "",
                    "gold": gold,
                }
            )
    return dataset_dir, cases


def _field_has_gold(field: str, gold_value: Any) -> bool:
    if field in SCALAR_FIELDS:
        return bool(gold_value)
    if isinstance(gold_value, list):
        return len(gold_value) > 0
    return False


def _string_preview(value: Any) -> str:
    return _normalize_whitespace(str(value))


def _link_preview(item: Any) -> str:
    if isinstance(item, dict):
        label = _normalize_whitespace(str(item.get("label", "")))
        url = _normalize_whitespace(str(item.get("url", "")))
        return " · ".join(bit for bit in (label, url) if bit)
    return _string_preview(item)


def _record_preview(record: Any, field: str) -> str:
    if not isinstance(record, dict):
        return _string_preview(record)
    if field == "experience":
        parts = [
            record.get("title"),
            record.get("organization"),
            " - ".join(bit for bit in (record.get("start_date"), record.get("end_date")) if bit),
        ]
        fallback = record.get("summary") or " ".join(record.get("bullets", [])[:1] if isinstance(record.get("bullets"), list) else [])
        return " · ".join(bit for bit in parts if bit) or _normalize_whitespace(str(fallback or ""))
    if field == "education":
        parts = [record.get("degree"), record.get("institution"), record.get("field_of_study")]
        fallback = record.get("gpa_or_score") or record.get("summary")
        return " · ".join(bit for bit in parts if bit) or _normalize_whitespace(str(fallback or ""))
    if field == "projects":
        parts = [record.get("name"), record.get("summary")]
        if not any(parts):
            parts = [record.get("title"), record.get("organization")]
        return " · ".join(bit for bit in parts if bit)
    if field == "certifications":
        parts = [record.get("name"), record.get("issuer"), record.get("credential_id")]
        return " · ".join(bit for bit in parts if bit)
    if field == "achievements":
        parts = [record.get("title"), record.get("name"), record.get("summary")]
        return " · ".join(bit for bit in parts if bit)
    return _string_preview(record)


def _record_signature(record: Any, field: str) -> str:
    preview = _record_preview(record, field)
    return _normalize_text(preview)


def _extract_case_inputs(insights: dict[str, Any]) -> dict[str, Any]:
    identity = insights.get("identity", {}) or {}
    return {
        "name": [identity.get("full_name")] if identity.get("full_name") else [],
        "email": list(identity.get("emails", []) or []),
        "phone": list(identity.get("phones", []) or []),
        "location": [identity.get("location")] if identity.get("location") else [],
        "summary": [identity.get("summary")] if identity.get("summary") else [],
        "links": [item.get("url") for item in insights.get("public_profiles", []) if isinstance(item, dict) and item.get("url")],
        "skills": list(insights.get("skills", []) or []),
        "experience": list(insights.get("work_experience", []) or []),
        "education": list(insights.get("education", []) or []),
        "projects": list(insights.get("projects", []) or []),
        "certifications": list(insights.get("certifications", []) or []),
        "achievements": [],
    }


def _score_scalar_field(field: str, gold_value: Any, extracted_values: list[Any]) -> dict[str, Any]:
    if not gold_value:
        return {
            "field": field,
            "label": FIELD_LABELS[field],
            "status": "not_scored",
            "score": None,
            "gold_count": 0,
            "extracted_count": len(extracted_values),
            "matched_count": 0,
            "missing_count": 0,
            "unexpected_count": 0,
            "gold_preview": [],
            "extracted_preview": _nonempty_list(_string_preview(value) for value in extracted_values)[:5],
            "notes": ["Gold field is empty in the benchmark template."],
        }

    if field == "email":
        gold_norm = _normalize_text(str(gold_value))
        normalized_values = [_normalize_text(str(value)) for value in extracted_values if value]
        best_score = 1.0 if gold_norm and gold_norm in normalized_values else 0.0
    elif field == "phone":
        gold_norm = _normalize_phone(str(gold_value))
        normalized_values = [_normalize_phone(str(value)) for value in extracted_values if value]
        best_score = 1.0 if gold_norm and gold_norm in normalized_values else 0.0
    else:
        normalizer = _normalize_name if field == "name" else _normalize_text
        gold_norm = normalizer(str(gold_value))
        normalized_values = [normalizer(str(value)) for value in extracted_values if value]
        best_score = max((_similarity(gold_norm, candidate) for candidate in normalized_values), default=0.0)

    matched_count = 1 if best_score >= 0.95 else 0
    return {
        "field": field,
        "label": FIELD_LABELS[field],
        "status": _status_from_score(best_score),
        "score": _clamp_score(best_score),
        "gold_count": 1,
        "extracted_count": len(extracted_values),
        "matched_count": matched_count,
        "missing_count": 0 if matched_count else 1,
        "unexpected_count": max(0, len(extracted_values) - matched_count),
        "gold_preview": [_string_preview(gold_value)],
        "extracted_preview": _nonempty_list(_string_preview(value) for value in extracted_values)[:5],
        "notes": [],
    }


def _greedy_match(
    gold_items: list[str],
    extracted_items: list[str],
    *,
    threshold: float,
) -> tuple[int, float]:
    if not gold_items or not extracted_items:
        return 0, 0.0
    used_indices: set[int] = set()
    matched = 0
    score_total = 0.0
    for gold in gold_items:
        best_index = None
        best_score = 0.0
        for index, extracted in enumerate(extracted_items):
            if index in used_indices:
                continue
            score = _similarity(gold, extracted)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is not None and best_score >= threshold:
            used_indices.add(best_index)
            matched += 1
            score_total += best_score
    return matched, score_total


def _score_set_field(field: str, gold_values: list[Any], extracted_values: list[Any]) -> dict[str, Any]:
    if not gold_values:
        return {
            "field": field,
            "label": FIELD_LABELS[field],
            "status": "not_scored",
            "score": None,
            "gold_count": 0,
            "extracted_count": len(extracted_values),
            "matched_count": 0,
            "missing_count": 0,
            "unexpected_count": 0,
            "gold_preview": [],
            "extracted_preview": _nonempty_list(_link_preview(value) if field == "links" else _string_preview(value) for value in extracted_values)[:8],
            "notes": ["Gold field is empty in the benchmark template."],
        }

    if field == "links":
        gold_normalized = [_normalize_url(_link_preview(item)) for item in gold_values if _normalize_url(_link_preview(item))]
        extracted_normalized = [_normalize_url(_string_preview(item)) for item in extracted_values if _normalize_url(_string_preview(item))]
        matched_count = sum(1 for value in gold_normalized if value in set(extracted_normalized))
        precision = matched_count / len(extracted_normalized) if extracted_normalized else 0.0
        recall = matched_count / len(gold_normalized) if gold_normalized else 0.0
        score = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    else:
        gold_normalized = [_normalize_skill(_string_preview(item)) for item in gold_values if _normalize_skill(_string_preview(item))]
        extracted_normalized = [_normalize_skill(_string_preview(item)) for item in extracted_values if _normalize_skill(_string_preview(item))]
        matched_count, score_total = _greedy_match(gold_normalized, extracted_normalized, threshold=0.92)
        precision = matched_count / len(extracted_normalized) if extracted_normalized else 0.0
        recall = matched_count / len(gold_normalized) if gold_normalized else 0.0
        harmonic = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        similarity_boost = (score_total / matched_count) if matched_count else 0.0
        score = harmonic * 0.8 + similarity_boost * 0.2 if matched_count else harmonic

    return {
        "field": field,
        "label": FIELD_LABELS[field],
        "status": _status_from_score(score),
        "score": _clamp_score(score),
        "gold_count": len(gold_values),
        "extracted_count": len(extracted_values),
        "matched_count": matched_count,
        "missing_count": max(0, len(gold_values) - matched_count),
        "unexpected_count": max(0, len(extracted_values) - matched_count),
        "gold_preview": _nonempty_list(_link_preview(item) if field == "links" else _string_preview(item) for item in gold_values)[:8],
        "extracted_preview": _nonempty_list(_string_preview(item) for item in extracted_values)[:8],
        "notes": [],
    }


def _score_record_field(field: str, gold_values: list[Any], extracted_values: list[Any]) -> dict[str, Any]:
    if not gold_values:
        return {
            "field": field,
            "label": FIELD_LABELS[field],
            "status": "not_scored",
            "score": None,
            "gold_count": 0,
            "extracted_count": len(extracted_values),
            "matched_count": 0,
            "missing_count": 0,
            "unexpected_count": 0,
            "gold_preview": [],
            "extracted_preview": _nonempty_list(_record_preview(item, field) for item in extracted_values)[:6],
            "notes": ["Gold field is empty in the benchmark template."],
        }

    gold_signatures = [_record_signature(item, field) for item in gold_values if _record_signature(item, field)]
    extracted_signatures = [_record_signature(item, field) for item in extracted_values if _record_signature(item, field)]
    threshold = 0.72 if field in {"experience", "education"} else 0.82
    matched_count, score_total = _greedy_match(gold_signatures, extracted_signatures, threshold=threshold)
    precision = matched_count / len(extracted_signatures) if extracted_signatures else 0.0
    recall = matched_count / len(gold_signatures) if gold_signatures else 0.0
    harmonic = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    similarity_boost = (score_total / matched_count) if matched_count else 0.0
    score = harmonic * 0.75 + similarity_boost * 0.25 if matched_count else harmonic
    return {
        "field": field,
        "label": FIELD_LABELS[field],
        "status": _status_from_score(score),
        "score": _clamp_score(score),
        "gold_count": len(gold_values),
        "extracted_count": len(extracted_values),
        "matched_count": matched_count,
        "missing_count": max(0, len(gold_values) - matched_count),
        "unexpected_count": max(0, len(extracted_values) - matched_count),
        "gold_preview": _nonempty_list(_record_preview(item, field) for item in gold_values)[:6],
        "extracted_preview": _nonempty_list(_record_preview(item, field) for item in extracted_values)[:6],
        "notes": [],
    }


def _score_field(field: str, gold_value: Any, extracted_value: Any) -> dict[str, Any]:
    if field in SCALAR_FIELDS:
        return _score_scalar_field(field, gold_value, list(extracted_value or []))
    if field in SET_FIELDS:
        return _score_set_field(field, list(gold_value or []), list(extracted_value or []))
    return _score_record_field(field, list(gold_value or []), list(extracted_value or []))


def _case_overall_score(field_scores: list[dict[str, Any]]) -> float | None:
    weighted_total = 0.0
    weight_sum = 0.0
    for field_score in field_scores:
        score = field_score.get("score")
        if score is None:
            continue
        weight = FIELD_WEIGHTS.get(field_score["field"], 1.0)
        weighted_total += weight * float(score)
        weight_sum += weight
    if weight_sum == 0:
        return None
    return _clamp_score(weighted_total / weight_sum)


def _benchmark_settings(settings: Settings, allow_remote_models: bool) -> Settings:
    if allow_remote_models:
        return settings
    return settings.model_copy(
        update={
            "enable_llm_extractor": False,
            "enable_embedding_retrieval": False,
            "enable_correction_llm_arbiter": False,
            "enable_resume_gpt_formatter": False,
        }
    )


def _build_extracted_snapshot(insights: dict[str, Any]) -> dict[str, Any]:
    identity = insights.get("identity", {}) or {}
    return {
        "full_name": identity.get("full_name"),
        "headline": identity.get("headline"),
        "location": identity.get("location"),
        "emails": list(identity.get("emails", []) or []),
        "phones": list(identity.get("phones", []) or []),
        "skills_count": len(insights.get("skills", []) or []),
        "experience_count": len(insights.get("work_experience", []) or []),
        "education_count": len(insights.get("education", []) or []),
        "project_count": len(insights.get("projects", []) or []),
        "top_skills": list(insights.get("skills", []) or [])[:10],
        "top_experience": [_record_preview(item, "experience") for item in (insights.get("work_experience", []) or [])[:3]],
        "top_projects": [_record_preview(item, "projects") for item in (insights.get("projects", []) or [])[:3]],
    }


def _evaluate_case(
    case: dict[str, Any],
    settings: Settings,
    *,
    parser_backend: str,
    allow_remote_models: bool,
) -> dict[str, Any]:
    path = Path(case["file_path"]) if case.get("file_path") else None
    if path is None or not path.exists():
        return {
            "resume_id": case["resume_id"],
            "category": case["category"],
            "filename": case["filename"],
            "file_path": case.get("file_path") or "",
            "parser_backend": parser_backend,
            "status": "error",
            "overall_score": None,
            "gold_fields_available": sum(1 for field in FIELD_ORDER if _field_has_gold(field, case["gold"].get(field))),
            "warnings": [],
            "error": "Resume file was not found on disk.",
            "diagnostics": {},
            "extracted_snapshot": {},
            "field_scores": [],
        }

    extracted_text, parse_metadata = extract_text_from_path(path)
    document = Document(
        profile_id="benchmark-profile",
        filename=case["filename"],
        storage_path=str(path),
        source_type="benchmark",
        mime_type=detect_mime_type(path),
        checksum=compute_checksum(path),
        extracted_text=extracted_text,
        parse_metadata=parse_metadata,
    )
    document.id = f"benchmark-{case['resume_id']}"

    benchmark_settings = _benchmark_settings(settings, allow_remote_models)
    insights, extraction_mode, warnings, diagnostics = extract_document_profile_insights(
        document,
        benchmark_settings,
        parser_backend=parser_backend if parser_backend != PARSER_AUTO else None,
    )
    document.parse_metadata = {
        **document.parse_metadata,
        "profile_insights": insights,
        "profile_extraction_mode": extraction_mode,
        "profile_extraction_warnings": warnings,
        "profile_validation": diagnostics.get("validation", {}),
        "profile_parser_backend": diagnostics.get("parser_backend"),
    }
    metadata = annotate_document_profile_metadata(document, insights)
    extracted = _extract_case_inputs(insights)
    field_scores = [_score_field(field, case["gold"].get(field), extracted.get(field)) for field in FIELD_ORDER]
    overall_score = _case_overall_score(field_scores)

    return {
        "resume_id": case["resume_id"],
        "category": case["category"],
        "filename": case["filename"],
        "file_path": str(path),
        "parser_backend": diagnostics.get("parser_backend") or parser_backend,
        "extraction_mode": extraction_mode,
        "status": "ok",
        "overall_score": overall_score,
        "gold_fields_available": sum(1 for field in FIELD_ORDER if _field_has_gold(field, case["gold"].get(field))),
        "warnings": warnings,
        "error": None,
        "diagnostics": {
            "document_role": metadata.get("document_role"),
            "profile_focus": metadata.get("profile_focus"),
            "source_quality": metadata.get("source_quality"),
            "validation_status": diagnostics.get("validation", {}).get("status"),
            "validation_score": diagnostics.get("validation", {}).get("score"),
            "layout_parser": diagnostics.get("layout", {}).get("parser") or parse_metadata.get("parser"),
            "page_count": diagnostics.get("layout", {}).get("page_count") or parse_metadata.get("page_count"),
            "block_count": diagnostics.get("layout", {}).get("block_count") or parse_metadata.get("block_count"),
        },
        "extracted_snapshot": _build_extracted_snapshot(insights),
        "field_scores": field_scores,
    }


def _aggregate_field_metrics(case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for field in FIELD_ORDER:
        scores = []
        match_cases = 0
        close_cases = 0
        miss_cases = 0
        skipped_cases = 0
        for case in case_results:
            field_score = next((item for item in case.get("field_scores", []) if item["field"] == field), None)
            if not field_score or field_score.get("status") == "not_scored":
                skipped_cases += 1
                continue
            score = field_score.get("score")
            if score is not None:
                scores.append(float(score))
            if field_score["status"] == "match":
                match_cases += 1
            elif field_score["status"] == "close":
                close_cases += 1
            else:
                miss_cases += 1
        metrics.append(
            {
                "field": field,
                "label": FIELD_LABELS[field],
                "scored_cases": len(scores),
                "skipped_cases": skipped_cases,
                "average_score": _clamp_score(sum(scores) / len(scores)) if scores else None,
                "match_cases": match_cases,
                "close_cases": close_cases,
                "miss_cases": miss_cases,
            }
        )
    return metrics


def _json_ready_report(report: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(report, ensure_ascii=True, default=str))


def save_benchmark_report(report: dict[str, Any], settings: Settings) -> str:
    reports_dir = _benchmark_reports_dir(settings)
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    parser_backend = str(report.get("parser_backend") or "auto")
    report_path = reports_dir / f"benchmark-{timestamp}-{parser_backend}.json"
    latest_path = reports_dir / "latest.json"
    payload = _json_ready_report(report)
    payload["saved_report_path"] = str(report_path)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(report_path)


def load_latest_benchmark_report(settings: Settings) -> dict[str, Any] | None:
    latest_path = _benchmark_reports_dir(settings) / "latest.json"
    if not latest_path.exists():
        return None
    return _safe_jsonish(latest_path.read_text(encoding="utf-8"), None)


def benchmark_dataset_summary(settings: Settings) -> dict[str, Any]:
    dataset_dir, cases = load_benchmark_cases(settings)
    latest_report = load_latest_benchmark_report(settings)
    gold_path = dataset_dir / "gold_annotation_template.csv" if dataset_dir else None
    manifest_path = dataset_dir / "sample_pdf_manifest.csv" if dataset_dir else None
    field_coverage = {
        field: sum(1 for case in cases if _field_has_gold(field, case["gold"].get(field)))
        for field in FIELD_ORDER
    }
    review_status_counts: dict[str, int] = {}
    for case in cases:
        key = case.get("review_status") or "unknown"
        review_status_counts[key] = review_status_counts.get(key, 0) + 1
    summary = {
        "dataset_dir": str(dataset_dir) if dataset_dir else None,
        "available": bool(dataset_dir and gold_path and gold_path.exists()),
        "gold_template_path": str(gold_path) if gold_path and gold_path.exists() else None,
        "manifest_path": str(manifest_path) if manifest_path and manifest_path.exists() else None,
        "total_cases": len(cases),
        "categories": sorted({case["category"] for case in cases}),
        "review_status_counts": review_status_counts,
        "field_coverage": field_coverage,
        "latest_report_generated_at": latest_report.get("generated_at") if latest_report else None,
        "latest_report_parser_backend": latest_report.get("parser_backend") if latest_report else None,
        "latest_report_overall_score": latest_report.get("overall_score") if latest_report else None,
        "latest_report_path": latest_report.get("saved_report_path") if latest_report else None,
    }
    return summary


def run_resume_benchmark(
    settings: Settings,
    *,
    parser_backend: str = PARSER_AUTO,
    limit: int | None = None,
    categories: list[str] | None = None,
    resume_ids: list[str] | None = None,
    allow_remote_models: bool = False,
) -> dict[str, Any]:
    dataset_dir, cases = load_benchmark_cases(settings)
    if dataset_dir is None or not cases:
        raise FileNotFoundError("Benchmark dataset is not available. Configure BENCHMARK_DATASET_DIR or place the dataset in ~/Downloads/ragume_benchmark_gold_v0.")

    selected_categories = {item for item in (categories or []) if item}
    selected_resume_ids = {item for item in (resume_ids or []) if item}
    filtered_cases = [
        case
        for case in cases
        if (not selected_categories or case["category"] in selected_categories)
        and (not selected_resume_ids or case["resume_id"] in selected_resume_ids)
    ]
    applied_limit = limit if limit is not None else settings.benchmark_default_limit
    if applied_limit:
        filtered_cases = filtered_cases[:applied_limit]

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for case in filtered_cases:
        try:
            results.append(
                _evaluate_case(
                    case,
                    settings,
                    parser_backend=parser_backend,
                    allow_remote_models=allow_remote_models,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive catch for bad source files
            results.append(
                {
                    "resume_id": case["resume_id"],
                    "category": case["category"],
                    "filename": case["filename"],
                    "file_path": case.get("file_path") or "",
                    "parser_backend": parser_backend,
                    "extraction_mode": None,
                    "status": "error",
                    "overall_score": None,
                    "gold_fields_available": sum(1 for field in FIELD_ORDER if _field_has_gold(field, case["gold"].get(field))),
                    "warnings": [],
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "diagnostics": {},
                    "extracted_snapshot": {},
                    "field_scores": [],
                }
            )

    duration_seconds = round(time.perf_counter() - started, 3)
    successful = [case for case in results if case["status"] == "ok" and case.get("overall_score") is not None]
    overall_score = _clamp_score(sum(float(case["overall_score"]) for case in successful) / len(successful)) if successful else None
    field_metrics = _aggregate_field_metrics([case for case in results if case["status"] == "ok"])
    report = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "dataset_dir": str(dataset_dir),
        "parser_backend": parser_backend,
        "allow_remote_models": allow_remote_models,
        "limit": applied_limit,
        "categories": sorted(selected_categories),
        "resume_ids": sorted(selected_resume_ids),
        "total_cases": len(filtered_cases),
        "processed_cases": len(results),
        "success_cases": len([case for case in results if case["status"] == "ok"]),
        "failed_cases": len([case for case in results if case["status"] == "error"]),
        "overall_score": overall_score,
        "duration_seconds": duration_seconds,
        "saved_report_path": None,
        "field_metrics": field_metrics,
        "cases": sorted(
            results,
            key=lambda item: (item.get("status") != "ok", item.get("overall_score") if item.get("overall_score") is not None else -1.0),
        ),
    }
    report["saved_report_path"] = save_benchmark_report(report, settings)
    return report
