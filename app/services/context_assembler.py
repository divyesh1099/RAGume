"""Context assembly: dedup, token budget, citation numbering, formatted evidence.

Ported from NITRAG's context_assembler.py.

Turns a ranked list of retrieved chunks into a numbered evidence block that
a generation model (or the user) can read and cite precisely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.retrieval import RetrievedChunk


def _count_tokens(text: str) -> int:
    """Whitespace-split word count as a cheap token proxy (no tiktoken dep)."""
    return len(re.findall(r"\S+", text))


@dataclass
class AssembledContext:
    """Fully assembled context ready to pass to an LLM or display in the UI."""

    chunks: list["RetrievedChunk"]
    # chunk_id → 1-based citation number
    citation_map: dict[str, int] = field(default_factory=dict)
    # Formatted evidence string for LLM consumption
    formatted_text: str = ""
    total_tokens: int = 0
    truncated: bool = False
    dropped_count: int = 0


def assemble_context(
    results: "list[RetrievedChunk]",
    query: str = "",
    max_tokens: int = 3500,
    ordering: str = "score",
) -> AssembledContext:
    """Deduplicate, budget, number, and format retrieved chunks.

    Parameters
    ----------
    results:
        Ranked list from ``search_chunks()`` or ``retrieve_claim_context()``.
    query:
        Original query (unused here, reserved for future relevance-based ordering).
    max_tokens:
        Approximate word-count ceiling for the assembled context.
    ordering:
        ``"score"`` (default) — highest-score first.
        ``"document"`` — chronological by document upload time, then chunk index.
        ``"mixed"`` — top half by score, rest chronological.

    Returns
    -------
    AssembledContext with citation_map and formatted_text ready for the LLM.
    """
    if not results:
        return AssembledContext(chunks=[])

    # --- 1. Deduplicate by chunk_id, keep highest score ---
    seen: dict[str, "RetrievedChunk"] = {}
    for result in results:
        cid = result.chunk.id
        if cid not in seen or result.score > seen[cid].score:
            seen[cid] = result
    deduped = list(seen.values())

    # --- 2. Order ---
    if ordering == "document":
        deduped.sort(
            key=lambda r: (r.document.created_at, r.chunk.chunk_index)
        )
    elif ordering == "mixed":
        deduped.sort(key=lambda r: r.score, reverse=True)
        half = max(len(deduped) // 2, 1)
        top_half = deduped[:half]
        rest = sorted(
            deduped[half:],
            key=lambda r: (r.document.created_at, r.chunk.chunk_index),
        )
        deduped = top_half + rest
    else:
        deduped.sort(key=lambda r: r.score, reverse=True)

    # --- 3. Apply token budget ---
    selected: list["RetrievedChunk"] = []
    total_tokens = 0
    truncated = False
    dropped_count = 0

    for result in deduped:
        chunk_tokens = _count_tokens(result.chunk.text)
        if total_tokens + chunk_tokens > max_tokens:
            truncated = True
            dropped_count += 1
            continue
        selected.append(result)
        total_tokens += chunk_tokens

    # --- 4. Assign 1-based citation numbers ---
    citation_map: dict[str, int] = {}
    for i, result in enumerate(selected, start=1):
        citation_map[result.chunk.id] = i

    # --- 5. Format as numbered evidence blocks (NITRAG style) ---
    sep = "─" * 64
    lines: list[str] = []
    for result in selected:
        n = citation_map[result.chunk.id]
        score_str = f"{result.score:.4f}"
        header = f"[{n}] {result.document.filename} | chunk {result.chunk.chunk_index} | score {score_str}"
        lines.append(sep)
        lines.append(header)
        lines.append(result.chunk.text.strip())

    if lines:
        lines.append(sep)

    return AssembledContext(
        chunks=selected,
        citation_map=citation_map,
        formatted_text="\n".join(lines),
        total_tokens=total_tokens,
        truncated=truncated,
        dropped_count=dropped_count,
    )
