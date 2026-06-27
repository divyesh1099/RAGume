"""Multi-stage reranking pipeline.

Stage 1 (always): keyword overlap + phrase proximity (lightweight, no model load).
Stage 2 (optional, ENABLE_CROSS_ENCODER_RERANKER=true): cross-encoder reranking
  via ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (~80 MB, CPU-friendly).

Cross-encoder reranking is dramatically more accurate than keyword overlap because
it evaluates query-document relevance jointly rather than independently.  It runs
after stage 1 so it only scores the top ~16 candidates, keeping latency low.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import numpy as np

from app.services.claim_utils import tokenize

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.retrieval import RetrievedChunk

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
except Exception:  # pragma: no cover
    _CrossEncoder = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Cross-encoder support
# ---------------------------------------------------------------------------

def cross_encoder_available(settings: "Settings") -> bool:
    return (
        getattr(settings, "enable_cross_encoder_reranker", False)
        and _CrossEncoder is not None
    )


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str, cache_dir: str | None) -> Any:
    if _CrossEncoder is None:
        raise RuntimeError("sentence-transformers not installed")
    kwargs: dict = {}
    if cache_dir:
        kwargs["cache_folder"] = cache_dir
    return _CrossEncoder(model_name, **kwargs)


def cross_encoder_rerank(
    results: "list[RetrievedChunk]",
    query: str,
    settings: "Settings",
) -> "list[RetrievedChunk]":
    """Rerank ``results`` using a cross-encoder relevance model.

    The cross-encoder sees (query, passage) jointly, so it captures semantic
    entailment and subtle paraphrasing that bag-of-words methods miss.

    Scoring strategy: logistic-transform the raw logit to [0,1], then blend
    60 % cross-encoder + 40 % existing RRF score so strong BM25/semantic
    signals are not discarded entirely.
    """
    if not results or not query.strip() or not cross_encoder_available(settings):
        return results

    model_name: str = getattr(settings, "cross_encoder_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    cache_dir: str | None = getattr(settings, "local_embedding_cache_dir", "./data/model-cache")

    try:
        model = _load_cross_encoder(model_name, cache_dir)
    except Exception:
        return results

    pairs = [(query, r.chunk.text) for r in results]
    try:
        raw_scores = model.predict(pairs, show_progress_bar=False)
    except Exception:
        return results

    # ms-marco models output raw logits; sigmoid maps to [0, 1]
    scores_arr = np.array(raw_scores, dtype=np.float32)
    sigmoid_scores = (1.0 / (1.0 + np.exp(-scores_arr))).tolist()

    for result, ce_score in zip(results, sigmoid_scores):
        result.score_components["cross_encoder"] = round(ce_score, 4)
        # Blend: cross-encoder dominates but preserves retrieval signal
        result.score = round(0.6 * ce_score + 0.4 * result.score, 6)

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _keyword_overlap_score(query_tokens: list[str], chunk_text: str) -> float:
    """Coverage fraction × 5  +  log(1 + total frequency).

    Rewards chunks where most query terms appear AND appear often.
    Matches NITRAG's KeywordOverlapReranker formula (reranker_manager.py:84-110).
    """
    if not query_tokens:
        return 0.0

    chunk_tokens = set(tokenize(chunk_text))
    text_lower = chunk_text.lower()
    q_token_set = set(query_tokens)

    matched = sum(1 for t in q_token_set if t in chunk_tokens)
    coverage = matched / max(len(q_token_set), 1)
    frequency = sum(text_lower.count(t) for t in q_token_set)
    return coverage * 5.0 + math.log1p(frequency)


def _phrase_proximity_score(
    query_tokens: list[str],
    chunk_text: str,
    proximity_window: int = 20,
) -> float:
    """Minimum window spanning all matched query terms in the chunk.

    Matches NITRAG's PhraseProximityReranker (reranker_manager.py:113-187).
    score = coverage * 4.0 + 1/(1+min_span) + proximity_bonus
    """
    if not query_tokens:
        return 0.0

    chunk_tokens = tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0

    q_token_set = set(query_tokens)

    # Collect positions of each matched query term
    positions: dict[str, list[int]] = {}
    for i, token in enumerate(chunk_tokens):
        if token in q_token_set:
            positions.setdefault(token, []).append(i)

    if not positions:
        return 0.0

    coverage = len(positions) / max(len(q_token_set), 1)

    if len(positions) < 2:
        # Only one distinct term matched — can't measure span
        return coverage * 4.0

    # Find minimum window in chunk_tokens that contains at least one occurrence
    # of every matched query term, using a sorted-events sliding approach.
    found_terms = list(positions.keys())
    events: list[tuple[int, str]] = []
    for term in found_terms:
        for pos in positions[term]:
            events.append((pos, term))
    events.sort()

    term_count = len(found_terms)
    # rightmost position seen for each term in the current window
    rightmost: dict[str, int] = {}
    # how many distinct terms are currently covered
    covered = 0
    left = 0
    min_span = float("inf")

    for right_pos, right_term in events:
        if right_term not in rightmost:
            covered += 1
        rightmost[right_term] = right_pos

        if covered < term_count:
            continue

        # All terms present — try to shrink from the left
        while left < len(events):
            left_pos, left_term = events[left]
            if rightmost.get(left_term) != left_pos:
                # left entry is stale (a later occurrence covers this term)
                left += 1
                continue
            span = right_pos - left_pos
            if span < min_span:
                min_span = span
            break

    if min_span == float("inf"):
        min_span = len(chunk_tokens)

    proximity = 1.0 / (1.0 + min_span)
    phrase_bonus = 1.5 if min_span <= proximity_window else 0.0
    return coverage * 4.0 + proximity + phrase_bonus


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]; returns all-zeros when constant."""
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum
    if spread < 1e-9:
        return [0.0 if maximum < 1e-9 else 1.0] * len(values)
    return [(v - minimum) / spread for v in values]


def rerank(
    results: "list[RetrievedChunk]",
    query: str,
    keyword_weight: float = 0.6,
    proximity_weight: float = 0.4,
) -> "list[RetrievedChunk]":
    """Rerank ``results`` in-place using keyword overlap + phrase proximity.

    Blends the normalised rerank signal (70 %) with the existing retrieval score
    (30 %) so that strong RRF winners are not discarded by reranking noise.
    The original score_components are preserved; rerank_* keys are added.
    """
    if not results or not query.strip():
        return results

    query_tokens = tokenize(query)

    kw_scores: list[float] = []
    prox_scores: list[float] = []
    for result in results:
        kw_scores.append(_keyword_overlap_score(query_tokens, result.chunk.text))
        prox_scores.append(_phrase_proximity_score(query_tokens, result.chunk.text))

    norm_kw = _normalize(kw_scores)
    norm_prox = _normalize(prox_scores)

    for result, nkw, nprox in zip(results, norm_kw, norm_prox):
        combined = keyword_weight * nkw + proximity_weight * nprox
        result.score_components["rerank_keyword"] = round(nkw, 4)
        result.score_components["rerank_proximity"] = round(nprox, 4)
        result.score_components["rerank"] = round(combined, 4)
        # Blend: rerank dominates but preserves retrieval signal
        result.score = round(0.7 * combined + 0.3 * result.score, 6)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
