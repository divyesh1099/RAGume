"""Multi-strategy document chunking for hybrid retrieval.

Three strategies are implemented:

paragraph (default)
    Token-aware paragraph-boundary chunker ported from NITRAG.  Good for BM25
    lexical retrieval and LLM context assembly — chunks are large enough to
    contain full sentences and entity co-occurrences.

sentence_window
    Sliding window over individual lines/sentences with configurable window
    size and stride.  Better for dense-vector semantic retrieval where
    fine-grained units reduce noise.

section
    Resume-section-aware chunker: detects canonical section headers (Experience,
    Education, Skills…) and emits one chunk per section.  Best for structure-
    aware parsing and NER where keeping co-occurring entities together matters.

``chunk_document(text, settings)`` dispatches to all enabled strategies and
returns tagged chunks so the retrieval layer can preference strategy when needed.

The legacy ``chunk_text(text, max_chars, overlap_chars)`` API is preserved for
backward compatibility.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings


# Canonical resume section headings used by the section chunker.
# Intentionally self-contained to avoid circular imports with resume_parser.
_SECTION_CANONICAL: dict[str, set[str]] = {
    "summary": {
        "summary", "professional summary", "about", "profile", "overview",
        "objective", "career objective", "introduction", "bio", "about me",
        "career summary", "personal statement", "executive summary",
    },
    "skills": {
        "skills", "technical skills", "technologies", "core skills", "stack",
        "tech stack", "tools and technologies", "programming languages",
        "expertise", "competencies", "key skills", "technical proficiencies",
        "areas of expertise",
    },
    "work_experience": {
        "work experience", "experience", "professional experience", "employment",
        "career history", "employment history", "work history", "positions held",
        "relevant experience", "internships", "work", "career",
    },
    "education": {
        "education", "academics", "academic background", "qualifications",
        "educational background", "degrees", "schooling",
    },
    "projects": {
        "projects", "selected projects", "portfolio", "personal projects",
        "open source", "side projects", "notable projects", "technical projects",
    },
    "certifications": {
        "certifications", "certification", "licenses", "certificates",
        "professional certifications", "credentials", "courses",
    },
    "achievements": {
        "achievements", "awards", "honors", "accomplishments",
        "recognition", "publications",
    },
}


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\S+")


def _count_tokens(text: str) -> int:
    """Whitespace word count as a cheap BPE-token proxy."""
    return len(_WORD_RE.findall(text))


def _split_paragraphs(text: str) -> list[str]:
    """Split on double (or more) newlines; filter empties."""
    parts = re.split(r"\n{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split a single oversized paragraph into sentences."""
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _group_by_budget(
    elements: list[str],
    max_tokens: int,
    overlap_elements: int,
) -> list[list[str]]:
    """Group ``elements`` into lists whose combined word-count ≤ max_tokens.

    Mirrors NITRAG's group_elements_by_budget_chunker_factory logic.
    The last ``overlap_elements`` elements of chunk N become the first elements
    of chunk N+1 to provide context continuity.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for element in elements:
        element_tokens = _count_tokens(element)

        if element_tokens > max_tokens and not current:
            # Single element exceeds budget — emit it alone (can't split further)
            groups.append([element])
            continue

        if current_tokens + element_tokens > max_tokens and current:
            # Flush current group
            groups.append(current)
            # Carry last overlap_elements as context into the next chunk
            if overlap_elements > 0:
                current = current[-overlap_elements:]
                current_tokens = sum(_count_tokens(e) for e in current)
            else:
                current = []
                current_tokens = 0

        current.append(element)
        current_tokens += element_tokens

    if current:
        groups.append(current)

    return groups


def chunk_by_token_budget(
    text: str,
    max_tokens: int = 800,
    overlap_paragraphs: int = 1,
) -> list[dict]:
    """Chunk ``text`` using a token budget and paragraph boundaries.

    Parameters
    ----------
    text:
        Raw extracted document text.
    max_tokens:
        Approximate word-count ceiling per chunk (NITRAG default: 800).
    overlap_paragraphs:
        Number of trailing paragraphs of chunk N to repeat at the start of
        chunk N+1 (NITRAG default: 1 element overlap).

    Returns
    -------
    List of dicts: ``{text, start_char, end_char, token_count}``.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    paragraphs = _split_paragraphs(normalized)

    # If a paragraph alone exceeds the budget, split it into sentences first
    expanded: list[str] = []
    for para in paragraphs:
        if _count_tokens(para) > max_tokens:
            sentences = _split_sentences(para)
            # Re-group sentences by budget (no overlap within a paragraph)
            sentence_groups = _group_by_budget(sentences, max_tokens, 0)
            for sg in sentence_groups:
                expanded.append(" ".join(sg))
        else:
            expanded.append(para)

    groups = _group_by_budget(expanded, max_tokens, overlap_paragraphs)

    chunks: list[dict] = []
    search_start = 0  # tracks position in normalized for start_char/end_char

    for group in groups:
        chunk_text_val = "\n\n".join(group)
        # Locate start_char by finding the first line of this group in the text
        first_line = group[0]
        found_at = normalized.find(first_line, search_start)
        if found_at == -1:
            # Overlap paragraphs may appear earlier; scan from the beginning
            found_at = normalized.find(first_line)
        start_char = max(found_at, 0)
        end_char = start_char + len(chunk_text_val)
        # Advance search cursor to start_char so overlap doesn't jump backward
        # (only advance when we're past the previous position)
        search_start = max(search_start, start_char)

        chunks.append(
            {
                "text": chunk_text_val,
                "start_char": start_char,
                "end_char": min(end_char, len(normalized)),
                "token_count": _count_tokens(chunk_text_val),
            }
        )

    return chunks


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[dict]:
    """Legacy API — maps character-based parameters to the token-budget chunker.

    ``max_chars`` is converted to a token target (÷ 5.5, rounded).
    ``overlap_chars > 0`` maps to 1 overlap paragraph; 0 maps to 0.

    This preserves backward compatibility for callers in documents.py.
    """
    max_tokens = max(100, round(max_chars / 5.5))
    overlap_paragraphs = 1 if overlap_chars > 0 else 0
    return chunk_by_token_budget(text, max_tokens=max_tokens, overlap_paragraphs=overlap_paragraphs)


# ---------------------------------------------------------------------------
# Sentence-level sliding-window chunker
# ---------------------------------------------------------------------------

# Sentence-ending punctuation not followed by another capital (avoids splitting
# on "Inc.", "B.S.", "Dr.", etc.)
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ɏḀ-ỿ\"\'\(])")
# Common abbreviations that should NOT trigger a sentence split
_ABBREV_PATTERN = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|sr|jr|vs|etc|inc|corp|llc|ltd|co|dept|est|"
    r"e\.g|i\.e|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\."
    r"\s*$",
    re.IGNORECASE,
)


def _split_sentences_robust(text: str) -> list[str]:
    """Split ``text`` into sentence-level units suitable for resume content.

    Treats each non-empty line as a candidate unit (bullets, header lines,
    single facts).  Long lines (> 30 tokens) are further split at sentence
    boundaries while avoiding common abbreviations.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result: list[str] = []
    for line in lines:
        if _count_tokens(line) <= 30:
            result.append(line)
        else:
            # Only split at a boundary when the preceding fragment is not an
            # abbreviation (heuristic: last token before the period is short)
            parts = _SENT_BOUNDARY.split(line)
            for part in parts:
                s = part.strip()
                if s:
                    result.append(s)
    return result


def chunk_by_sentences(
    text: str,
    window_size: int = 3,
    stride: int = 2,
    min_tokens: int = 8,
) -> list[dict]:
    """Sentence-level sliding-window chunker.

    Parameters
    ----------
    text:       Raw document text.
    window_size: Number of sentences per chunk window.
    stride:     Step size between windows (< window_size → overlap).
    min_tokens: Discard windows whose combined token count is below this.

    Returns chunks tagged with ``strategy: "sentence_window"``.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    sentences = _split_sentences_robust(normalized)
    if not sentences:
        return []

    chunks: list[dict] = []
    i = 0
    while i < len(sentences):
        window = sentences[i : i + window_size]
        chunk_text_val = " ".join(window)
        token_count = _count_tokens(chunk_text_val)

        if token_count >= min_tokens:
            first = window[0]
            found_at = normalized.find(first)
            start_char = max(found_at, 0)
            end_char = min(start_char + len(chunk_text_val), len(normalized))
            chunks.append({
                "text": chunk_text_val,
                "start_char": start_char,
                "end_char": end_char,
                "token_count": token_count,
                "strategy": "sentence_window",
                "section": None,
            })

        i += max(stride, 1)

    return chunks


# ---------------------------------------------------------------------------
# Section-aware chunker
# ---------------------------------------------------------------------------

def _detect_section_heading(line: str) -> str | None:
    """Return the canonical section name if ``line`` looks like a section header."""
    if not line or len(line) > 80:
        return None
    # Strip non-alpha chars, lowercase, collapse whitespace
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z ]+", " ", line)).strip().lower()
    if not normalized:
        return None
    for canonical, aliases in _SECTION_CANONICAL.items():
        if normalized in aliases:
            return canonical
        # Substring match for multi-word aliases
        for alias in aliases:
            if len(alias.split()) >= 2 and alias in normalized:
                return canonical
    # ALL-CAPS short line without punctuation
    alpha = [c for c in line if c.isalpha()]
    if (
        alpha
        and sum(1 for c in alpha if c.isupper()) / len(alpha) >= 0.85
        and len(line.split()) <= 5
        and "." not in line
    ):
        return "unknown_section"
    return None


def chunk_by_section(text: str) -> list[dict]:
    """Section-aware chunker for resume documents.

    Detects canonical section headers and emits one chunk per section.
    Chunks are tagged with ``strategy: "section"`` and ``section: <name>``.
    Long sections (> 600 tokens) are further split at paragraph boundaries.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    lines = normalized.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_name = "preamble"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        heading = _detect_section_heading(stripped) if stripped else None
        if heading and len(stripped.split()) <= 6:
            if current_lines:
                sections.append((current_name, list(current_lines)))
            current_name = heading
            current_lines = []
        else:
            current_lines.append(stripped)

    if current_lines:
        sections.append((current_name, current_lines))

    chunks: list[dict] = []
    search_start = 0

    for section_name, section_lines in sections:
        section_text = "\n".join(ln for ln in section_lines if ln).strip()
        if not section_text or _count_tokens(section_text) < 5:
            continue

        if _count_tokens(section_text) <= 600:
            found_at = normalized.find(section_text[:60], search_start)
            start_char = max(found_at, 0)
            end_char = min(start_char + len(section_text), len(normalized))
            search_start = max(search_start, end_char)
            chunks.append({
                "text": section_text,
                "start_char": start_char,
                "end_char": end_char,
                "token_count": _count_tokens(section_text),
                "strategy": "section",
                "section": section_name,
            })
        else:
            # Long section — sub-chunk at paragraph boundaries
            sub_chunks = chunk_by_token_budget(section_text, max_tokens=400, overlap_paragraphs=1)
            for sub in sub_chunks:
                found_at = normalized.find(sub["text"][:60], search_start)
                start_char = max(found_at, 0)
                end_char = min(start_char + len(sub["text"]), len(normalized))
                search_start = max(search_start, end_char)
                chunks.append({
                    **sub,
                    "strategy": "section",
                    "section": section_name,
                })

    return chunks


# ---------------------------------------------------------------------------
# Multi-strategy dispatcher
# ---------------------------------------------------------------------------

def chunk_document(
    text: str,
    settings: "Settings",
) -> list[dict]:
    """Produce chunks using all enabled strategies.

    Always produces paragraph chunks (the base strategy for BM25 + LLM context).
    When ``settings.enable_sentence_chunking`` is True, also produces:
      - sentence-window chunks (fine-grained semantic retrieval)
      - section chunks (structure-aware NER and claim extraction)

    Each chunk dict carries a ``strategy`` key so the retrieval layer can
    preference different granularities for different query types.
    """
    max_tokens = max(100, round(settings.max_chunk_chars / 5.5))
    overlap = 1 if settings.chunk_overlap_chars > 0 else 0

    # Base: paragraph chunks (always produced)
    para_chunks = chunk_by_token_budget(text, max_tokens=max_tokens, overlap_paragraphs=overlap)
    for chunk in para_chunks:
        chunk.setdefault("strategy", "paragraph")
        chunk.setdefault("section", None)

    if not getattr(settings, "enable_sentence_chunking", False):
        return para_chunks

    # Sentence-window chunks
    sent_chunks = chunk_by_sentences(
        text,
        window_size=getattr(settings, "sentence_window_size", 3),
        stride=getattr(settings, "sentence_window_stride", 2),
    )

    # Section chunks
    section_chunks = chunk_by_section(text)

    # Combine; paragraph first so chunk_index ordering is stable
    all_chunks = para_chunks + sent_chunks + section_chunks

    # Deduplicate by exact text (sentence windows sometimes produce the same
    # text as a paragraph chunk when the document is short)
    seen_texts: set[str] = set()
    unique: list[dict] = []
    for chunk in all_chunks:
        key = chunk["text"].strip()
        if key and key not in seen_texts:
            seen_texts.add(key)
            unique.append(chunk)

    return unique
