from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import numpy as np
import onnxruntime as ort
from huggingface_hub import snapshot_download
from openai import OpenAI
from transformers import AutoConfig, AutoTokenizer

from app.config import Settings
from app.models import Document
from app.services.claim_utils import extract_skills
from app.services.pdf_layout import extract_pdf_layout

EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d()\s.-]{7,}\d)")
URL_PATTERN = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+")
DATE_PATTERN = re.compile(
    r"(?:(?:0?[1-9]|[12]\d|3[01])\s+)?"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+)?\d{4}",
    flags=re.IGNORECASE,
)
DATE_RANGE_PATTERN = re.compile(
    r"(?:(?:0?[1-9]|[12]\d|3[01])\s+)?"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+)?\d{4}"
    r"(?:\s*[-–to]+\s*(?:(?:present|current|now)|(?:(?:0?[1-9]|[12]\d|3[01])\s+)?"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+)?\d{4}))?",
    flags=re.IGNORECASE,
)
DEGREE_PATTERN = re.compile(
    r"\b(?:"
    r"b\.?\s?tech|m\.?\s?tech|"
    r"b\.?\s?sc\.?|m\.?\s?sc\.?|b\.?\s?s\.?|m\.?\s?s\.?|"
    r"b\.?\s?e\.?|m\.?\s?e\.?|b\.?\s?a\.?|m\.?\s?a\.?|"
    r"b\.?\s?com|m\.?\s?com|"
    r"b\.?\s?c\.?\s?a\.?|m\.?\s?c\.?\s?a\.?|bca|mca|"
    r"bachelor(?:'?s)?(?:\s+of)?|master(?:'?s)?(?:\s+of)?|"
    r"ph\.?\s?d\.?|d\.?\s?phil|"
    r"mba|m\.?\s?b\.?\s?a\.?|"
    r"associate(?:'?s)?|diploma|hnd|hnc|"
    r"doctorate|postgraduate|undergraduate"
    r")\b",
    flags=re.IGNORECASE,
)
INSTITUTION_PATTERN = re.compile(
    r"\b(?:"
    r"university|college|institute|school|academy|polytechnic|"
    r"iit|nit|bits|iiit|iim|iise|iisc|"              # Indian premier institutions
    r"mit|caltech|stanford|harvard|oxford|cambridge|"  # globally-known abbreviations
    r"hochschule|fachhochschule|universidad|università|université"  # non-English
    r")\b",
    flags=re.IGNORECASE,
)
ROLE_WORD_PATTERN = re.compile(
    r"\b(?:"
    r"engineer|developer|scientist|analyst|intern|consultant|researcher|"
    r"manager|lead|architect|specialist|designer|freelancer|freelancing|"
    r"principal|senior|junior|staff|director|officer|vp|"
    r"administrator|technician|executive|president|"
    r"head|chief|associate|assistant|coordinator|"
    r"programmer|founder|co-founder|"
    r"expert|strategist|advisor|mentor|trainer|"
    r"devops|sre|mlops|fullstack|frontend|backend"
    r")\b",
    flags=re.IGNORECASE,
)
BULLET_LINE_PATTERN = re.compile(r"^(?:[•\-*]\s*)+")
SECTION_ALIASES = {
    "summary": {
        "summary", "professional summary", "about", "profile", "overview",
        "objective", "career objective", "professional profile", "executive summary",
        "introduction", "bio", "about me", "who i am", "professional overview",
        "career summary", "personal statement", "professional statement",
    },
    "skills": {
        "skills", "technical skills", "technologies", "core skills", "stack",
        "tech stack", "tools technologies", "tools and technologies",
        "programming languages", "languages and technologies", "expertise",
        "competencies", "core competencies", "key skills", "proficiencies",
        "technical proficiencies", "skills tools", "tools frameworks",
        "frameworks and tools", "software", "technical expertise",
        "languages frameworks", "skills expertise", "tools and frameworks",
        "areas of expertise", "key technologies", "technical stack",
    },
    "work_experience": {
        "work experience", "experience", "professional experience", "employment",
        "career history", "employment history", "work history", "positions held",
        "professional background", "relevant experience", "industry experience",
        "internship experience", "internships", "work", "job history",
        "career", "professional history", "work and experience",
    },
    "education": {
        "education", "academics", "academic background", "academic history",
        "educational background", "qualifications", "academic qualifications",
        "degrees", "schooling", "training and education", "education training",
        "academic credentials",
    },
    "projects": {
        "projects", "selected projects", "portfolio", "personal projects",
        "open source", "open source projects", "side projects", "notable projects",
        "academic projects", "key projects", "recent projects", "technical projects",
        "project work", "project experience", "featured projects",
    },
    "certifications": {
        "certifications", "certification", "licenses", "certificates",
        "professional certifications", "credentials", "licenses certifications",
        "training certifications", "courses certifications", "courses",
        "online courses", "professional development",
    },
    "achievements": {
        "achievements", "awards", "honors", "accomplishments",
        "recognition", "awards honors", "achievements awards",
        "scholarships", "publications", "research publications", "honors awards",
        "accolades", "distinctions",
    },
    "leadership": {
        "leadership", "open source", "open source leadership",
        "community leadership", "volunteering", "volunteer experience",
        "extracurricular", "activities", "leadership activities",
        "community", "community involvement",
    },
    "languages": {"languages", "spoken languages", "language skills", "human languages"},
}
GENERIC_HEADINGS = set().union(*SECTION_ALIASES.values())
ROLE_SEPARATORS = (" | ", " at ", " @ ", " in ")
DEFAULT_SCHEMA = {
    "identity": {
        "full_name": None,
        "headline": None,
        "summary": None,
        "location": None,
        "emails": [],
        "phones": [],
    },
    "skills": [],
    "public_profiles": [],
    "education": [],
    "work_experience": [],
    "projects": [],
    "certifications": [],
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
    "backend",
    "frontend",
    "front end",
}
SKILL_WHITELIST = {
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
}


def _clean_text(value: str) -> str:
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value.strip())


def _clean_multiline_text(value: str) -> str:
    return "\n".join(line for line in (_clean_text(line) for line in value.splitlines()) if line)


def _normalize_url(url: str) -> str:
    cleaned = url.strip().rstrip(".,);")
    if cleaned.startswith("www."):
        cleaned = f"https://{cleaned}"
    return cleaned


def _canonical_url_key(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _url_path_segments(url: str) -> list[str]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return [segment for segment in parsed.path.split("/") if segment]


def _looks_like_project_repository_url(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    segments = _url_path_segments(url)
    if host in {"github.com", "gitlab.com", "bitbucket.org"}:
        return len(segments) >= 2
    if host == "huggingface.co":
        if not segments:
            return False
        if segments[0] in {"spaces", "datasets", "models"}:
            return True
        return len(segments) >= 2
    return False


def _project_link_keys(projects: Iterable[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for project in projects:
        for link in project.get("links", []) or []:
            normalized = _normalize_url(str(link))
            if normalized:
                keys.add(_canonical_url_key(normalized))
    return keys


def _filter_public_profile_links(
    links: Iterable[dict[str, str]],
    projects: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    project_keys = _project_link_keys(projects or [])
    filtered: list[dict[str, str]] = []
    for item in links:
        url = _normalize_url(item.get("url", ""))
        if not url:
            continue
        if _canonical_url_key(url) in project_keys:
            continue
        if _looks_like_project_repository_url(url):
            continue
        filtered.append({"label": _clean_text(item.get("label") or "Link"), "url": url})
    return _unique_links(filtered)


def _is_valid_public_url(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if not host:
        return False
    if "." not in host and not host.startswith("localhost"):
        return False
    return not host.endswith("-")


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw_value in values:
        cleaned = _clean_text(str(raw_value))
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        unique.append(cleaned)
        seen.add(lowered)
    return unique


def _clean_skill_candidate(value: str) -> str | None:
    cleaned = _clean_text(value).strip(" ,.;:|")
    cleaned = cleaned.replace("Scikit Learn", "Scikit-Learn")
    if not cleaned:
        return None
    if cleaned in SKILL_WHITELIST:
        return cleaned
    if cleaned.lower() in SKILL_HEADING_BLACKLIST:
        return None
    alnum = re.sub(r"[^A-Za-z0-9+#./-]", "", cleaned)
    if len(alnum) < 3 and cleaned not in {"C", "C#", "C++", "JS"}:
        return None
    if len(cleaned) > 40:
        return None
    if cleaned.lower() in {"mo", "as", "end", "gma", "ular"}:
        return None
    return cleaned


def _unique_skill_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = _clean_skill_candidate(str(value))
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        unique.append(cleaned)
        seen.add(lowered)
    if "scikit" in seen and "learn" in seen:
        unique = [item for item in unique if item.lower() not in {"scikit", "learn"}]
        unique.append("Scikit-Learn")
    return unique


def _unique_links(links: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in links:
        url = _normalize_url(item.get("url", ""))
        if not url or not _is_valid_public_url(url):
            continue
        canonical = _canonical_url_key(url)
        if canonical in seen:
            continue
        unique.append({"label": _clean_text(item.get("label") or "Link"), "url": url})
        seen.add(canonical)
    return unique


def _normalize_heading(text: str) -> str:
    # Strip non-alpha chars (including &, +, |, /, –) then collapse spaces
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z ]+", " ", text)).strip().lower()


def _canonical_section_heading(text: str) -> str | None:
    normalized = _normalize_heading(text)
    # First pass: exact matches — checked across all sections before any substring logic.
    # This ensures "open source leadership" (exact in leadership) beats
    # "open source" (substring in projects).
    for canonical, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return canonical
    # Second pass: substring matches for multi-word aliases only.
    # Single-word aliases must match exactly to avoid false positives like
    # "software" matching "Software Developer".
    for canonical, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            if len(alias.split()) < 2:
                continue
            if alias in normalized and len(normalized.split()) <= max(4, len(alias.split()) + 2):
                return canonical
    return None


def _looks_like_heading(text: str, *, body_font_size: float, max_font_size: float, is_bold: bool) -> bool:
    cleaned = _clean_text(text)
    if not cleaned or len(cleaned) > 90:
        return False
    # Known canonical heading — always accept
    if _canonical_section_heading(cleaned):
        return True
    alpha_chars = [c for c in cleaned if c.isalpha()]
    if not alpha_chars:
        return False
    uppercase_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
    # ALL-CAPS short line without punctuation → treat as heading even without bold/font bump
    # (common in plain-text and ATS-export resumes)
    if uppercase_ratio >= 0.85 and len(cleaned.split()) <= 5 and "." not in cleaned:
        return True
    return is_bold and (max_font_size >= body_font_size + 2.5 or uppercase_ratio > 0.75)


def _iter_text_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    preamble_blocks: list[list[str]] = []
    preamble_current: list[str] = []
    current: dict[str, Any] | None = None
    current_block_lines: list[str] = []

    def flush_current_block() -> None:
        nonlocal current_block_lines, preamble_current
        if current is None:
            if preamble_current:
                preamble_blocks.append(preamble_current)
                preamble_current = []
            return
        if not current_block_lines:
            return
        current["blocks"].append(
            {
                "text": "\n".join(current_block_lines),
                "lines": list(current_block_lines),
                "page": 0,
                "column": 0,
                "x0": 0.0,
                "y0": 0.0,
                "link_uris": [],
                "max_font_size": 11.0,
                "avg_font_size": 11.0,
                "is_bold": False,
            }
        )
        current_block_lines = []

    for raw_line in text.splitlines():
        line = _clean_text(raw_line)
        if not line:
            if current is None:
                if preamble_current:
                    preamble_blocks.append(preamble_current)
                    preamble_current = []
            else:
                flush_current_block()
            continue
        canonical = _canonical_section_heading(line)
        if canonical:
            flush_current_block()
            current = {"heading": canonical, "blocks": []}
            sections.append(current)
            continue
        if current is None:
            preamble_current.append(line)
            continue
        current_block_lines.append(line)

    if current is None and preamble_current:
        preamble_blocks.append(preamble_current)
    else:
        flush_current_block()

    return [
        {"heading": "__header__", "blocks": [{"text": "\n".join(block), "lines": block, "page": 0, "column": None, "x0": 0.0, "y0": 0.0, "link_uris": [], "max_font_size": 12.0, "avg_font_size": 12.0, "is_bold": False} for block in preamble_blocks]}
        if preamble_blocks
        else None,
        *sections,
    ]


def _detect_sections_from_layout(layout: dict[str, Any]) -> list[dict[str, Any]]:
    page_groups: dict[tuple[int, int | None], list[dict[str, Any]]] = {}
    for page in layout.get("pages", []):
        for block in page.get("blocks", []):
            key = (block["page"], block.get("column"))
            page_groups.setdefault(key, []).append(block)

    ordered_keys = sorted(page_groups.keys(), key=lambda item: (item[0], -1 if item[1] is None else item[1]))
    sections: list[dict[str, Any]] = []
    header_blocks: list[dict[str, Any]] = []
    body_font_size = float(layout.get("body_font_size") or 11.0)

    for key in ordered_keys:
        blocks = sorted(page_groups[key], key=lambda item: (item["y0"], item["x0"]))
        current: dict[str, Any] | None = None
        for block in blocks:
            heading = None
            if _looks_like_heading(
                block["text"],
                body_font_size=body_font_size,
                max_font_size=float(block.get("max_font_size") or body_font_size),
                is_bold=bool(block.get("is_bold")),
            ):
                heading = _canonical_section_heading(block["text"])

            if heading:
                current = {"heading": heading, "blocks": []}
                sections.append(current)
                continue

            if current is None:
                header_blocks.append(block)
                continue
            current["blocks"].append(block)

    detected_sections: list[dict[str, Any]] = []
    if header_blocks:
        detected_sections.append({"heading": "__header__", "blocks": header_blocks})
    detected_sections.extend(section for section in sections if section["blocks"])
    return detected_sections


def _classify_link(url: str) -> str:
    lowered = url.lower()
    if lowered.startswith("mailto:"):
        return "Email"
    if lowered.startswith("tel:"):
        return "Phone"
    if "linkedin" in lowered:
        return "LinkedIn"
    if "github" in lowered:
        return "GitHub"
    if "leetcode" in lowered:
        return "LeetCode"
    if "huggingface" in lowered:
        return "Hugging Face"
    if "hackerrank" in lowered:
        return "HackerRank"
    return "Portfolio"


def _looks_like_name(value: str) -> bool:
    if "," in value:
        return False
    words = [word.strip(".,") for word in re.split(r"\s+", value) if word]
    # Allow up to 6 words to capture compound names ("Jean Pierre Marie Dupont")
    if len(words) < 2 or len(words) > 6:
        return False
    if any(any(character.isdigit() for character in word) for word in words):
        return False
    if any("@" in word or "http" in word.lower() for word in words):
        return False
    # Accept Unicode letters, apostrophes, hyphens, and dots (handles José, François, O'Brien, etc.)
    _NAME_WORD_RE = re.compile(r"[^\W\d_][\w'.‐‑‒–—\-]*", re.UNICODE)
    return all(_NAME_WORD_RE.fullmatch(word) is not None for word in words)


def _visible_url_links(
    document: Document,
    layout: dict[str, Any],
    *,
    projects: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for item in layout.get("links", []):
        uri = item.get("uri")
        if not uri:
            continue
        label = _classify_link(uri)
        if label in {"Email", "Phone"}:
            continue
        links.append({"label": label, "url": uri})
    links.extend({"label": _classify_link(match.group(0)), "url": match.group(0)} for match in URL_PATTERN.finditer(document.extracted_text))
    return _filter_public_profile_links(links, projects=projects)


def _normalized_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10 or len(digits) > 14:
        return None
    if len(digits) == 10:
        return digits
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if value.strip().startswith("+"):
        return f"+{digits}"
    return digits


def _extract_phones(text: str, layout: dict[str, Any]) -> list[str]:
    numbers: list[str] = []
    for item in layout.get("links", []):
        uri = item.get("uri") or ""
        if uri.startswith("tel:"):
            candidate = _normalized_phone(uri.removeprefix("tel:"))
            if candidate:
                numbers.append(candidate)
    for match in PHONE_PATTERN.finditer(text):
        candidate = _normalized_phone(match.group(0))
        if candidate:
            numbers.append(candidate)
    return _unique_strings(numbers)


def _extract_emails(text: str, layout: dict[str, Any]) -> list[str]:
    emails = [match.group(0) for match in EMAIL_PATTERN.finditer(text)]
    for item in layout.get("links", []):
        uri = item.get("uri") or ""
        if uri.startswith("mailto:"):
            emails.append(uri.removeprefix("mailto:"))
    return _unique_strings(emails)


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values, axis=-1, keepdims=True)
    exponent = np.exp(shifted)
    return exponent / np.sum(exponent, axis=-1, keepdims=True)


@lru_cache(maxsize=2)
def _load_resume_ner_model(model_id: str, cache_dir: str | None) -> tuple[Any, ort.InferenceSession, dict[int, str]]:
    local_dir = snapshot_download(
        repo_id=model_id,
        cache_dir=cache_dir,
        allow_patterns=[
            "config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "tokenizer.model",
            "vocab.txt",
            "vocab.json",
            "merges.txt",
            "*.onnx",
        ],
    )
    tokenizer = AutoTokenizer.from_pretrained(local_dir)
    config = AutoConfig.from_pretrained(local_dir)
    model_path = Path(local_dir) / "model_quantized.onnx"
    if not model_path.exists():
        candidates = sorted(Path(local_dir).rglob("*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"No ONNX model found for {model_id}.")
        model_path = candidates[0]
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    id2label = dict(getattr(config, "id2label", {}))
    return tokenizer, session, id2label


def _merge_ner_tokens(text: str, offsets: np.ndarray, labels: list[str], scores: list[float]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for offset, label, score in zip(offsets, labels, scores, strict=False):
        start, end = int(offset[0]), int(offset[1])
        if start == end or label == "O":
            if current is not None:
                entities.append(current)
                current = None
            continue

        prefix, entity_type = label.split("-", 1)
        snippet = text[start:end]
        if prefix == "B" or current is None or current["type"] != entity_type or start > current["end"] + 1:
            if current is not None:
                entities.append(current)
            current = {"type": entity_type, "start": start, "end": end, "text": snippet, "scores": [score]}
            continue

        current["end"] = end
        current["text"] = text[current["start"] : end]
        current["scores"].append(score)

    if current is not None:
        entities.append(current)

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        cleaned = _clean_text(entity["text"])
        if not cleaned or len(cleaned) == 1:
            continue
        key = (entity["type"], cleaned.lower())
        if key in seen:
            continue
        normalized.append(
            {
                "type": entity["type"],
                "text": cleaned,
                "score": round(sum(entity["scores"]) / len(entity["scores"]), 4),
            }
        )
        seen.add(key)
    return normalized


def _run_resume_ner(text: str, settings: Settings) -> list[dict[str, Any]]:
    if not settings.enable_resume_ner or not text.strip():
        return []

    tokenizer, session, id2label = _load_resume_ner_model(settings.resume_ner_model_id, settings.resume_ner_cache_dir)
    encoded = tokenizer(
        text,
        truncation=True,
        return_offsets_mapping=True,
        max_length=min(settings.resume_ner_max_tokens, 512),
        return_tensors="np",
    )
    offsets = encoded.pop("offset_mapping")[0]
    feed = {}
    for model_input in session.get_inputs():
        value = encoded[model_input.name]
        feed[model_input.name] = value.astype(np.int64) if value.dtype != np.int64 else value

    logits = session.run(None, feed)[0][0]
    probabilities = _softmax(logits)
    predicted_ids = np.argmax(probabilities, axis=-1)
    labels = [id2label.get(int(index), "O") for index in predicted_ids]
    scores = [float(probabilities[token_index][label_id]) for token_index, label_id in enumerate(predicted_ids)]
    return _merge_ner_tokens(text, offsets, labels, scores)


def _entities_by_type(entities: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        grouped.setdefault(entity["type"], []).append(entity)
    return grouped


def _best_entity(grouped: dict[str, list[dict[str, Any]]], entity_type: str) -> str | None:
    items = grouped.get(entity_type) or []
    if not items:
        return None
    return sorted(items, key=lambda item: (-item["score"], -len(item["text"])))[0]["text"]


def _block_id(block: dict[str, Any]) -> str:
    return (
        f"p{int(block.get('page') or 0)}:"
        f"c{block.get('column') if block.get('column') is not None else 'x'}:"
        f"y{int(float(block.get('y0') or 0.0))}:"
        f"x{int(float(block.get('x0') or 0.0))}"
    )


def _visual_group_id(block: dict[str, Any]) -> str:
    return (
        f"p{int(block.get('page') or 0)}:"
        f"c{block.get('column') if block.get('column') is not None else 'x'}:"
        f"g{int(float(block.get('y0') or 0.0) // 36)}"
    )


def _extract_date_range(text: str) -> tuple[str | None, str | None]:
    match = DATE_RANGE_PATTERN.search(text)
    if not match:
        single = DATE_PATTERN.search(text)
        return (single.group(0).strip(), None) if single else (None, None)
    value = match.group(0)
    parts = re.split(r"\s*[-–to]+\s*", value, maxsplit=1)
    if len(parts) == 2:
        return _clean_text(parts[0]), _clean_text(parts[1])
    return _clean_text(value), None


def _split_header_and_body(block: dict[str, Any]) -> tuple[str, list[str]]:
    lines = [line for line in (_clean_text(line) for line in block.get("lines", [])) if line]
    if not lines:
        return "", []
    first = lines[0]
    if len(lines) >= 2 and not DATE_RANGE_PATTERN.search(first):
        second = lines[1]
        if DATE_RANGE_PATTERN.search(second) or first.endswith("(") or second.startswith("(") or second.lower().startswith("months"):
            return _clean_text(f"{first} {second}"), lines[2:]
    if ":" in first and len(first) < 120:
        left, right = [part.strip() for part in first.split(":", 1)]
        if left and right:
            body_lines = [right, *lines[1:]]
            return left, body_lines
    return first, lines[1:]


def _normalize_highlights(lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        cleaned = BULLET_LINE_PATTERN.sub("", _clean_text(line))
        if cleaned:
            normalized.append(cleaned)
    return _unique_strings(normalized)


def _entry_summary(highlights: list[str]) -> str | None:
    if not highlights:
        return None
    joined = " ".join(highlights[:2]).strip()
    return joined or None


def _title_and_company_from_header(header: str, grouped_entities: dict[str, list[dict[str, Any]]]) -> tuple[str | None, str | None]:
    cleaned = _clean_text(header)
    if not cleaned:
        return None, None

    for separator in ROLE_SEPARATORS:
        if separator in cleaned:
            left, right = [part.strip() for part in cleaned.split(separator, 1)]
            right = DATE_RANGE_PATTERN.sub("", right).strip("() -|")
            if "(" in right:
                suffix = right.split("(", 1)[1]
                if re.search(r"\d|month|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", suffix, flags=re.IGNORECASE):
                    right = right.split("(", 1)[0].strip()
            if ROLE_WORD_PATTERN.search(left):
                return left, right or None
            if ROLE_WORD_PATTERN.search(right):
                return right, left or None

    title = _best_entity(grouped_entities, "TITLE")
    company = _best_entity(grouped_entities, "COMPANY")
    return title, company


def _parse_work_experience(
    blocks: list[dict[str, Any]],
    document_id: str,
    ner_for_text,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finalize() -> None:
        nonlocal current
        if not current:
            return
        highlights = _normalize_highlights(current.get("body_lines", []))
        current["highlights"] = highlights
        current["summary"] = _entry_summary(highlights)
        current["technologies"] = _unique_skill_strings([*current.get("technologies", []), *extract_skills(" ".join(highlights))])
        if current.get("title") or current.get("organization"):
            entries.append(
                {
                    "title": current.get("title"),
                    "organization": current.get("organization"),
                    "location": current.get("location"),
                    "start_date": current.get("start_date"),
                    "end_date": current.get("end_date"),
                    "summary": current.get("summary"),
                    "highlights": highlights,
                    "technologies": current.get("technologies", []),
                    "source_page": current.get("source_page"),
                    "visual_group_id": current.get("visual_group_id"),
                    "title_block_id": current.get("title_block_id"),
                    "org_block_id": current.get("org_block_id"),
                    "date_block_id": current.get("date_block_id"),
                    "bullet_block_ids": current.get("bullet_block_ids", []),
                    "source_document_ids": [document_id],
                }
            )
        current = None

    for block in blocks:
        text = block["text"]
        header, body_lines = _split_header_and_body(block)
        grouped = _entities_by_type(ner_for_text(text))
        header_title, header_company = _title_and_company_from_header(header or text, grouped)
        header_is_short = len(_clean_text(header or text.splitlines()[0])) <= 110
        inline_header_entry = bool(
            header_is_short
            and not BULLET_LINE_PATTERN.match(header or "")
            and DATE_RANGE_PATTERN.search(header or "")
            and ROLE_WORD_PATTERN.search(header or "")
        )
        # Bold blocks with any title/company/role signal → entry header
        bold_entry = bool(
            block.get("is_bold")
            and header_is_short
            and (header_title or header_company or ROLE_WORD_PATTERN.search(header or text) or DATE_RANGE_PATTERN.search(text))
        )
        # Non-bold blocks: accept if they have both an identified title/company AND a date range
        # (many modern / ATS-exported resumes omit bold markup)
        non_bold_entry = bool(
            not block.get("is_bold")
            and header_is_short
            and not BULLET_LINE_PATTERN.match(header or "")
            and (header_title or header_company)
            and DATE_RANGE_PATTERN.search(text)
        )
        looks_like_entry = bold_entry or non_bold_entry or inline_header_entry
        if looks_like_entry:
            finalize()
            start_date, end_date = _extract_date_range(text)
            location = _best_entity(grouped, "LOCATION")
            if location and location.lower() in {"github", "linkedin", "leetcode"}:
                location = None
            block_identifier = _block_id(block)
            current = {
                "title": header_title,
                "organization": header_company,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "body_lines": body_lines,
                "technologies": _unique_skill_strings(entity["text"] for entity in grouped.get("SKILL", [])),
                "source_page": int(block.get("page") or 0),
                "visual_group_id": _visual_group_id(block),
                "title_block_id": block_identifier,
                "org_block_id": block_identifier if header_company else None,
                "date_block_id": block_identifier if start_date or end_date else None,
                "bullet_block_ids": [],
            }
            if not current["title"] and ROLE_WORD_PATTERN.search(header or text):
                current["title"] = header or text
            continue

        if current is not None:
            current["body_lines"].extend(block.get("lines", []))
            current["bullet_block_ids"].append(_block_id(block))

    finalize()
    return entries


def _parse_education(
    blocks: list[dict[str, Any]],
    document_id: str,
    ner_for_text,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in blocks:
        text = block["text"]
        grouped = _entities_by_type(ner_for_text(text))
        institution = _best_entity(grouped, "INSTITUTION")
        degree = _best_entity(grouped, "DEGREE")
        field = _best_entity(grouped, "FIELD")
        start_date, end_date = _extract_date_range(text)
        lines = [line for line in (_clean_text(line) for line in block.get("lines", [])) if line]
        if not institution:
            institution = next((line for line in lines if INSTITUTION_PATTERN.search(line)), lines[0] if lines else None)
        elif lines:
            institution_line = next((line for line in lines if INSTITUTION_PATTERN.search(line)), None)
            if institution_line and len(institution_line) > len(institution):
                institution = institution_line
        if not degree:
            degree = next((line for line in lines if DEGREE_PATTERN.search(line)), None)
        if degree:
            degree = _clean_text(DATE_RANGE_PATTERN.sub("", degree)).strip(" |") or degree
        if not field and degree:
            field_match = re.search(r"\b(?:in|with a focus on)\s+(.+)$", degree, flags=re.IGNORECASE)
            if field_match:
                field = _clean_text(field_match.group(1))
        summary_lines = [line for line in lines if line not in {institution, degree}]
        if institution or degree:
            items.append(
                {
                    "institution": institution,
                    "degree": degree,
                    "field_of_study": field,
                    "start_date": start_date,
                    "end_date": end_date,
                    "summary": _clean_text(" ".join(summary_lines)) or None,
                    "source_document_ids": [document_id],
                }
            )
    return items


def _parse_projects(
    blocks: list[dict[str, Any]],
    document_id: str,
    ner_for_text,
) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finalize() -> None:
        nonlocal current
        if not current:
            return
        highlights = _normalize_highlights(current.get("body_lines", []))
        summary = _entry_summary(highlights) or current.get("inline_summary")
        technologies = _unique_skill_strings([*current.get("technologies", []), *extract_skills(" ".join(highlights))])
        discovered_links = [
            _normalize_url(match.group(0))
            for match in URL_PATTERN.finditer(
                " ".join(
                    part
                    for part in [
                        current.get("name", ""),
                        current.get("inline_summary", ""),
                        *current.get("body_lines", []),
                    ]
                    if part
                )
            )
        ]
        if current.get("name"):
            projects.append(
                {
                    "name": current.get("name"),
                    "summary": summary,
                    "technologies": technologies,
                    "links": _unique_strings([*current.get("links", []), *discovered_links]),
                    "source_document_ids": [document_id],
                }
            )
        current = None

    for block in blocks:
        text = block["text"]
        header, body_lines = _split_header_and_body(block)
        grouped = _entities_by_type(ner_for_text(text))
        maybe_name = header or text.splitlines()[0]
        maybe_name = _clean_text(maybe_name).rstrip(":")
        short_header = bool(maybe_name and len(maybe_name) <= 100)
        first_line = _clean_text((block.get("lines") or [""])[0])
        looks_like_project = bool(block.get("is_bold") and short_header) or (
            first_line.endswith(":") and short_header and not BULLET_LINE_PATTERN.match(first_line)
        ) or (
            bool(body_lines)
            and short_header
            and not BULLET_LINE_PATTERN.match(first_line)
            and not ROLE_WORD_PATTERN.search(first_line)
        )

        if looks_like_project:
            finalize()
            inline_summary = None
            if ":" in (header or text):
                parts = (header or text).split(":", 1)
                if len(parts) == 2 and _clean_text(parts[1]):
                    inline_summary = _clean_text(parts[1])
            initial_technologies = (
                _unique_skill_strings(entity["text"] for entity in grouped.get("SKILL", []))
                if body_lines or inline_summary
                else []
            )
            current = {
                "name": maybe_name,
                "body_lines": body_lines,
                "inline_summary": inline_summary,
                "technologies": initial_technologies,
                "links": [
                    *_unique_strings(list(block.get("link_uris", []))),
                    *[_normalize_url(match.group(0)) for match in URL_PATTERN.finditer(text)],
                ],
            }
            continue

        if current is not None:
            current["body_lines"].extend(block.get("lines", []))
            current["links"].extend(block.get("link_uris", []))

    finalize()
    return projects


def _parse_certifications(
    blocks: list[dict[str, Any]],
    document_id: str,
    ner_for_text,
) -> list[dict[str, Any]]:
    certifications: list[dict[str, Any]] = []
    for block in blocks:
        text = block["text"]
        grouped = _entities_by_type(ner_for_text(text))
        cert_name = _best_entity(grouped, "CERT") or _clean_text(block.get("lines", [""])[0])
        issuer = _best_entity(grouped, "COMPANY")
        start_date, _ = _extract_date_range(text)
        if cert_name:
            certifications.append(
                {
                    "name": cert_name,
                    "issuer": issuer,
                    "start_date": start_date,
                    "credential_id": None,
                    "summary": _clean_text(" ".join(block.get("lines", [])[1:])) or None,
                    "source_document_ids": [document_id],
                }
            )
    return certifications


def _identity_from_header(
    header_blocks: list[dict[str, Any]],
    layout: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
    work_experience: list[dict[str, Any]],
    ner_for_text,
) -> dict[str, Any]:
    header_text = "\n".join(block["text"] for block in header_blocks if block.get("text"))
    header_entities = _entities_by_type(ner_for_text(header_text))
    full_name = _best_entity(header_entities, "NAME")
    if not full_name:
        for block in header_blocks:
            for line in block.get("lines", []):
                for segment in [part.strip() for part in line.split("|") if part.strip()]:
                    if _looks_like_name(segment):
                        full_name = segment
                        break
                if full_name:
                    break
            if full_name:
                break

    headline_candidates: list[str] = []
    location = _best_entity(header_entities, "LOCATION")
    if location and location.lower() in {"github", "linkedin", "leetcode"}:
        location = None
    for block in header_blocks:
        for line in block.get("lines", []):
            cleaned = _clean_text(line)
            if not cleaned:
                continue
            if EMAIL_PATTERN.search(cleaned) or URL_PATTERN.search(cleaned) or PHONE_PATTERN.search(cleaned):
                continue
            if "|" in cleaned:
                pipe_parts = [_clean_text(part) for part in cleaned.split("|") if _clean_text(part)]
                headline_from_pipe = next(
                    (
                        part
                        for part in pipe_parts
                        if ROLE_WORD_PATTERN.search(part)
                        and not DATE_RANGE_PATTERN.search(part)
                        and not EMAIL_PATTERN.search(part)
                        and not URL_PATTERN.search(part)
                    ),
                    None,
                )
                if headline_from_pipe:
                    headline_candidates.append(headline_from_pipe)
                continue
            if full_name and cleaned.upper() == full_name.upper():
                continue
            if DATE_RANGE_PATTERN.search(cleaned):
                continue
            if _canonical_section_heading(cleaned):
                continue
            if len(cleaned.split()) <= 12:
                headline_candidates.append(cleaned)

    summary = None
    if sections.get("summary"):
        summary_lines = []
        for block in sections["summary"]:
            summary_lines.extend(block.get("lines", []))
        # No artificial line cap — capture the full summary section
        # but guard against accidentally including subsequent section content (>600 chars)
        raw_summary = _clean_text(" ".join(summary_lines))
        summary = raw_summary[:600] if raw_summary else None

    headline = next((candidate for candidate in headline_candidates if candidate), None)

    return {
        "full_name": full_name,
        "headline": headline,
        "summary": summary,
        "location": location,
        "emails": _extract_emails(header_text, layout),
        "phones": _extract_phones(header_text, layout),
    }


def _collect_skills(
    document: Document,
    sections: dict[str, list[dict[str, Any]]],
    work_experience: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    ner_for_text,
) -> list[str]:
    explicit_skills: list[str] = []
    for block in sections.get("skills", []):
        for line in block.get("lines", []):
            # Wider set of separators including ;, &, tab, and em-dashes used in skill lists
            explicit_skills.extend(part.strip() for part in re.split(r"[|,/·•;\t]+|\s+&\s+|\s+and\s+", line) if part.strip())

    ner_skills = [entity["text"] for entity in ner_for_text(document.extracted_text) if entity["type"] == "SKILL"]
    derived = []
    for item in [*work_experience, *projects]:
        derived.extend(item.get("technologies", []))
    # Only add derived/NER skills that are NOT already covered by explicit section skills
    # (avoids NER noise dominating when an explicit skills section is present)
    explicit_lower = {s.lower() for s in _unique_skill_strings(explicit_skills)}
    ner_new = [s for s in ner_skills if s.lower() not in explicit_lower]
    if not explicit_lower:
        # No explicit section — add regex-derived skills from full text too
        derived.extend(extract_skills(document.extracted_text))
    return _unique_skill_strings([*explicit_skills, *ner_new, *derived])


def _coerce_schema(payload: dict[str, Any], document_id: str) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_SCHEMA))
    merged.update({key: value for key, value in payload.items() if key in merged})

    identity = merged.get("identity") or {}
    merged["identity"] = {
        "full_name": _clean_text(identity.get("full_name") or "") or None,
        "headline": _clean_text(identity.get("headline") or "") or None,
        "summary": _clean_text(identity.get("summary") or "") or None,
        "location": _clean_text(identity.get("location") or "") or None,
        "emails": _unique_strings(identity.get("emails", [])),
        "phones": _unique_strings(identity.get("phones", [])),
    }
    merged["skills"] = _unique_strings(merged.get("skills", []))
    merged["public_profiles"] = _unique_links(merged.get("public_profiles", []))

    for key in ("education", "work_experience", "projects", "certifications"):
        normalized_items = []
        for item in merged.get(key, []):
            normalized_item = dict(item)
            normalized_item["source_document_ids"] = _unique_strings([*normalized_item.get("source_document_ids", []), document_id])
            normalized_items.append(normalized_item)
        merged[key] = normalized_items
    merged["public_profiles"] = _filter_public_profile_links(merged.get("public_profiles", []), projects=merged.get("projects", []))
    return merged


def _gpt_format_resume_json(
    draft: dict[str, Any],
    section_map: dict[str, str],
    settings: Settings,
    document: Document,
) -> dict[str, Any]:
    """LLM-powered gap-fill: fix only the fields that the rule-based parser got wrong or left empty."""
    client = OpenAI(api_key=settings.openai_api_key)

    # Identify weak fields to focus the LLM on — avoids reprocessing already-good data
    identity = draft.get("identity", {})
    weak_fields: list[str] = []
    if not identity.get("full_name"):
        weak_fields.append("identity.full_name")
    if not identity.get("headline"):
        weak_fields.append("identity.headline")
    if not identity.get("summary"):
        weak_fields.append("identity.summary")
    if not draft.get("work_experience"):
        weak_fields.append("work_experience")
    if not draft.get("education"):
        weak_fields.append("education")
    if len(draft.get("skills", [])) < 3:
        weak_fields.append("skills")
    if not draft.get("projects"):
        weak_fields.append("projects")

    # Only truncate large sections to keep the prompt focused
    compact_sections = {key: value[:3000] for key, value in section_map.items() if value}

    system_prompt = (
        "You are a precise resume parser assistant. "
        "Your job is to CORRECT and COMPLETE the structured resume output from an automated parser.\n\n"
        "RULES:\n"
        "1. Return the COMPLETE corrected JSON — same schema as the draft.\n"
        "2. Fix ONLY what is wrong or missing. Do NOT change fields that already look correct.\n"
        "3. Use ONLY information explicitly present in the raw section text provided. NEVER invent or hallucinate.\n"
        "4. For work_experience and education, preserve all items already in the draft; only ADD missing ones.\n"
        "5. For skills, merge with the draft list; remove obvious noise (single letters, prepositions).\n"
        "6. If evidence for a field is genuinely absent, keep it null/empty — do not guess.\n"
        "7. Dates: use the format found in the text (e.g. 'Jan 2021', '2021', 'June 2019 - Present').\n"
        "8. Return valid JSON only. No markdown, no prose outside the JSON.\n\n"
        f"Weak/missing fields that NEED attention: {', '.join(weak_fields) if weak_fields else 'none — general quality pass only'}."
    )

    response = client.chat.completions.create(
        model=settings.resume_formatter_model or settings.openai_model,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "filename": document.filename,
                        "current_parsed_draft": draft,
                        "raw_sections": compact_sections,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _build_validation(
    insights: dict[str, Any],
    section_blocks: dict[str, list[dict[str, Any]]],
    mode: str,
) -> dict[str, Any]:
    identity = insights.get("identity", {})
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    def add_check(field: str, value: Any, minimum: int = 1) -> None:
        present = len(value) >= minimum if isinstance(value, list) else bool(value)
        checks.append({"field": field, "status": "ok" if present else "missing", "value": value})
        if not present:
            warnings.append(f"{field.replace('_', ' ').title()} is missing or weak.")

    add_check("full_name", identity.get("full_name"))
    add_check("emails", identity.get("emails", []))
    add_check("phones", identity.get("phones", []))
    add_check("work_experience", insights.get("work_experience", []))
    add_check("education", insights.get("education", []))
    add_check("projects", insights.get("projects", []))

    if not section_blocks.get("skills") and len(insights.get("skills", [])) < 4:
        warnings.append("No explicit skills section was detected, so skills were inferred from the document text.")
    if mode.endswith("local"):
        warnings.append("GPT formatter was not used for this parse.")

    satisfied = sum(1 for item in checks if item["status"] == "ok")
    score = round((satisfied / max(1, len(checks))) * 100)
    if score >= 85:
        status = "strong"
    elif score >= 65:
        status = "usable"
    else:
        status = "needs_review"

    return {
        "score": score,
        "status": status,
        "warnings": _unique_strings(warnings),
        "checks": checks,
        "detected_sections": {
            key: len(value)
            for key, value in section_blocks.items()
            if key != "__header__"
        },
    }


def parse_resume_document(document: Document, settings: Settings) -> tuple[dict[str, Any], str, list[str], dict[str, Any]]:
    path = Path(document.storage_path)
    warnings: list[str] = []

    if path.suffix.lower() == ".pdf":
        layout = extract_pdf_layout(path)
        sections = _detect_sections_from_layout(layout)
    else:
        layout = {
            "parser": document.parse_metadata.get("parser") or "plain_text",
            "page_count": document.parse_metadata.get("page_count"),
            "block_count": 0,
            "link_count": 0,
            "body_font_size": 11.0,
            "text": document.extracted_text,
            "pages": [],
            "links": [],
        }
        sections = [section for section in _iter_text_sections(document.extracted_text) if section]

    section_blocks = {
        section["heading"]: section["blocks"]
        for section in sections
    }
    ner_cache: dict[str, list[dict[str, Any]]] = {}
    gliner_cache: dict[str, list[dict[str, Any]]] = {}

    def ner_for_text(text: str) -> list[dict[str, Any]]:
        cleaned = _clean_multiline_text(text)
        if not cleaned:
            return []

        # --- oksomu/resume-ner (ONNX, BIO token classification) ---
        if cleaned not in ner_cache:
            try:
                ner_cache[cleaned] = _run_resume_ner(cleaned, settings)
            except Exception as exc:
                warnings.append(f"Local resume NER failed with {exc.__class__.__name__}.")
                ner_cache[cleaned] = []

        # --- GLiNER (zero-shot span extraction, optional) ---
        if cleaned not in gliner_cache:
            from app.services.gliner_ner import gliner_available, run_gliner_ner
            if gliner_available(settings):
                try:
                    gliner_cache[cleaned] = run_gliner_ner(cleaned, settings)
                except Exception as exc:
                    warnings.append(f"GLiNER NER failed with {exc.__class__.__name__}.")
                    gliner_cache[cleaned] = []
            else:
                gliner_cache[cleaned] = []

        # Merge: keep highest-confidence entity when both models agree on (type, text)
        if gliner_cache[cleaned]:
            from app.services.gliner_ner import merge_ner_results
            return merge_ner_results(ner_cache[cleaned], gliner_cache[cleaned])

        return ner_cache[cleaned]

    work_experience = _parse_work_experience(section_blocks.get("work_experience", []), document.id, ner_for_text)
    education = _parse_education(section_blocks.get("education", []), document.id, ner_for_text)
    projects = _parse_projects(section_blocks.get("projects", []), document.id, ner_for_text)
    certifications = _parse_certifications(section_blocks.get("certifications", []), document.id, ner_for_text)

    draft = {
        "identity": _identity_from_header(
            section_blocks.get("__header__", []),
            layout,
            section_blocks,
            work_experience,
            ner_for_text,
        ),
        "skills": _collect_skills(document, section_blocks, work_experience, projects, ner_for_text),
        "public_profiles": _visible_url_links(document, layout, projects=projects),
        "education": education,
        "work_experience": work_experience,
        "projects": projects,
        "certifications": certifications,
    }
    draft = _coerce_schema(draft, document.id)

    mode = "openresume_ner_local"
    if settings.enable_resume_gpt_formatter and settings.openai_api_key:
        section_text_map = {
            key: "\n\n".join(block["text"] for block in value)
            for key, value in section_blocks.items()
            if value
        }
        try:
            refined = _gpt_format_resume_json(draft, section_text_map, settings, document)
            draft = _coerce_schema(refined, document.id)
            mode = "openresume_ner_gpt"
        except Exception as exc:
            warnings.append(f"GPT resume formatter failed with {exc.__class__.__name__}; local formatter was used instead.")

    validation = _build_validation(draft, section_blocks, mode)
    diagnostics = {
        "section_order": [section["heading"] for section in sections],
        "section_counts": {
            key: len(value)
            for key, value in section_blocks.items()
        },
        "layout": {
            "parser": layout.get("parser"),
            "page_count": layout.get("page_count"),
            "block_count": layout.get("block_count"),
            "link_count": layout.get("link_count"),
        },
        "validation": validation,
        "ner_entities": {
            label.lower(): [entity["text"] for entity in entities]
            for label, entities in _entities_by_type(ner_for_text(document.extracted_text)).items()
        },
    }
    return draft, mode, _unique_strings([*warnings, *validation["warnings"]]), diagnostics
