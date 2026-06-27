"""GLiNER-based zero-shot NER for resume/profile entity extraction.

GLiNER (Generalist and Lightweight Named Entity Recognition) uses a single
encoder with a span-detection head to extract arbitrary entity types given
plain-language labels — no task-specific fine-tuning required.

Why it outperforms ``oksomu/resume-ner`` for resume data:
  - Custom labels precisely match our schema (job title, university, degree…)
  - Not limited to PER/ORG/LOC — extracts SKILL, DEGREE, CERTIFICATION, etc.
  - Higher F1 on domain-specific entities due to instruction tuning

Model: urchade/gliner_small-v2.1 (~180 MB, Apache-2.0, CPU-friendly)
Alternative: gliner-community/gliner_small-v2.5 (newer, same size)

Feature flag: ENABLE_GLINER_NER  (default: false — requires ~180 MB download)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings


# Natural-language labels → GLiNER extracts entities matching each label.
# Order matters: GLiNER processes labels left-to-right; put the most
# discriminating / high-value labels first.
GLINER_LABELS: list[str] = [
    "person name",
    "job title",
    "company name",
    "university or college",
    "degree",
    "field of study",
    "programming language",
    "software framework",
    "technical skill",
    "tool or technology",
    "city or country",
    "date or date range",
    "certification or license",
    "award or honor",
]

# Map GLiNER label → internal entity type compatible with oksomu/resume-ner
_LABEL_TO_TYPE: dict[str, str] = {
    "person name": "NAME",
    "job title": "ROLE",
    "company name": "ORG",
    "university or college": "ORG",
    "degree": "DEGREE",
    "field of study": "MAJOR",
    "programming language": "SKILL",
    "software framework": "SKILL",
    "technical skill": "SKILL",
    "tool or technology": "SKILL",
    "city or country": "LOCATION",
    "date or date range": "DATE",
    "certification or license": "CERTIFICATION",
    "award or honor": "AWARD",
}

# GLiNER labels that map to SKILL (used for targeted skill extraction)
SKILL_LABELS: frozenset[str] = frozenset({
    "programming language",
    "software framework",
    "technical skill",
    "tool or technology",
})


def gliner_available(settings: "Settings") -> bool:
    if not getattr(settings, "enable_gliner_ner", False):
        return False
    try:
        import gliner  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=2)
def _load_gliner_model(model_id: str, cache_dir: str | None):
    import os
    from gliner import GLiNER

    if cache_dir:
        os.environ.setdefault("HF_HOME", str(cache_dir))
    return GLiNER.from_pretrained(model_id)


def run_gliner_ner(text: str, settings: "Settings") -> list[dict[str, Any]]:
    """Extract resume entities using GLiNER.

    Returns a list of dicts compatible with the oksomu/resume-ner schema:
        {"type": str, "text": str, "score": float, "label": str}
    Empty list on any failure (model unavailable, inference error).
    """
    if not text.strip() or not gliner_available(settings):
        return []

    model_id: str = getattr(settings, "gliner_model_id", "urchade/gliner_small-v2.1")
    cache_dir: str | None = getattr(settings, "gliner_cache_dir", "./data/model-cache")
    threshold: float = float(getattr(settings, "gliner_threshold", 0.35))

    try:
        model = _load_gliner_model(model_id, cache_dir)
    except Exception:
        return []

    all_entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for chunk_text, _offset in _split_for_gliner(text, max_chars=1200):
        try:
            raw = model.predict_entities(chunk_text, GLINER_LABELS, threshold=threshold)
        except Exception:
            continue
        for ent in raw:
            entity_type = _LABEL_TO_TYPE.get(ent["label"], ent["label"].upper())
            cleaned = ent["text"].strip()
            if not cleaned or len(cleaned) < 2:
                continue
            key = (entity_type, cleaned.lower())
            if key in seen:
                continue
            seen.add(key)
            all_entities.append({
                "type": entity_type,
                "text": cleaned,
                "score": round(float(ent.get("score", 0.5)), 4),
                "label": ent["label"],
            })

    return all_entities


def merge_ner_results(
    base: list[dict[str, Any]],
    supplemental: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge two NER result lists, keeping the higher-confidence entity per (type, text).

    ``base`` is the primary source (oksomu/resume-ner); ``supplemental`` fills gaps
    (GLiNER). When the same (type, text.lower()) appears in both, we keep whichever
    has the higher score so the best signal wins.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in [*base, *supplemental]:
        key = (entity["type"], entity["text"].lower())
        existing = merged.get(key)
        if existing is None or entity.get("score", 0.0) > existing.get("score", 0.0):
            merged[key] = entity
    return list(merged.values())


def _split_for_gliner(text: str, max_chars: int = 1200) -> list[tuple[str, int]]:
    """Split long text into paragraph-boundary segments for GLiNER inference.

    GLiNER has a context window limit; splitting at paragraph boundaries keeps
    entities intact while fitting within the limit.
    """
    if len(text) <= max_chars:
        return [(text, 0)]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    result: list[tuple[str, int]] = []
    current_parts: list[str] = []
    current_len = 0
    global_offset = 0

    for para in paragraphs:
        if current_len + len(para) > max_chars and current_parts:
            chunk = "\n\n".join(current_parts)
            result.append((chunk, global_offset))
            global_offset += len(chunk)
            current_parts = []
            current_len = 0
        current_parts.append(para)
        current_len += len(para)

    if current_parts:
        result.append(("\n\n".join(current_parts), global_offset))

    return result or [(text, 0)]
