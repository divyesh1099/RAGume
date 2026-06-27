"""Full NITRAG-style hybrid retrieval pipeline.

Stages (ported from NITRAG's rag_pipeline.py + semantic_retrievers.py):
  1. Query expansion (resume abbreviations)
  2. BM25 retrieval via pre-built inverted index
  3. Semantic retrieval via batch numpy cosine similarity
  4. RRF (Reciprocal Rank Fusion) to blend lexical + semantic ranked lists
  5. Two-signal reranking (keyword overlap + phrase proximity)
  6. Return top-k RetrievedChunk

Public API (backward-compatible):
  search_chunks(session, query, top_k, document_id, profile_id, settings) → list[RetrievedChunk]
  retrieve_claim_context(session, document_id, top_k, focus_areas, settings) → list[RetrievedChunk]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, Document
from app.services.bm25_index import BM25Index
from app.services.claim_utils import ACTION_VERBS, tokenize
from app.services.embeddings import (
    any_embedding_available,
    batch_cosine_similarity,
    embedding_available,
    embed_texts,
    embed_texts_for_retrieval,
    ensure_chunk_embeddings,
)
from app.services.query_manager import expand_query


@dataclass
class RetrievedChunk:
    chunk: Chunk
    document: Document
    score: float
    score_components: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BM25 index cache
# ---------------------------------------------------------------------------
# Keyed by a cheap fingerprint of the corpus to avoid rebuilding on every call.
# Cleared when it grows too large (documents are rarely added, so this is safe).
_bm25_cache: dict[str, BM25Index] = {}


def _corpus_fingerprint(scope_id: str, chunks: list[Chunk]) -> str:
    """Cheap fingerprint: scope + chunk count + lexicographically last chunk id."""
    if not chunks:
        return f"{scope_id}:0"
    last_id = max(c.id for c in chunks)
    return f"{scope_id}:{len(chunks)}:{last_id}"


def _get_or_build_bm25(scope_id: str, chunks: list[Chunk]) -> BM25Index:
    key = _corpus_fingerprint(scope_id, chunks)
    if key not in _bm25_cache:
        if len(_bm25_cache) > 128:
            _bm25_cache.clear()
        _bm25_cache[key] = BM25Index.build(
            [c.id for c in chunks],
            [c.text for c in chunks],
        )
    return _bm25_cache[key]


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------

def _rrf_fuse(
    bm25_ranked: list[tuple[str, float]],
    semantic_ranked: list[tuple[str, float]],
    k: float = 60.0,
    alpha: float = 0.5,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (NITRAG: semantic_retrievers.py:40-77).

    alpha=0.5  → equal weight between lexical and semantic.
    alpha→1.0  → pure semantic.
    alpha→0.0  → pure lexical.

    RRF score for chunk c = (1-α)/(k+rank_bm25) + α/(k+rank_sem)
    """
    scores: dict[str, float] = {}
    for rank, (chunk_id, _) in enumerate(bm25_ranked):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 - alpha) / (k + rank + 1)
    for rank, (chunk_id, _) in enumerate(semantic_ranked):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + alpha / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# Structural signal (legacy, used for claim extraction)
# ---------------------------------------------------------------------------

def _structural_score(chunk_text: str, focus_tokens: list[str]) -> float:
    score = 0.0
    text_lower = chunk_text.lower()
    for verb in ACTION_VERBS:
        if verb in text_lower:
            score += 1.2
    if any(c.isdigit() for c in chunk_text):
        score += 0.8
    if "-" in chunk_text or "*" in chunk_text or "\n" in chunk_text:
        score += 0.4
    if focus_tokens:
        chunk_token_set = set(tokenize(chunk_text))
        score += sum(0.9 for t in focus_tokens if t in chunk_token_set)
    return score


# ---------------------------------------------------------------------------
# Main retrieval entry points
# ---------------------------------------------------------------------------

def search_chunks(
    session: Session,
    query: str,
    top_k: int = 5,
    document_id: str | None = None,
    profile_id: str | None = None,
    settings: Settings | None = None,
    include_structural_signals: bool = False,
) -> list[RetrievedChunk]:
    """NITRAG-style retrieval pipeline.

    Steps
    -----
    1. Load corpus chunks for the given scope (document or profile).
    2. Build (or retrieve cached) BM25 inverted index.
    3. Expand query (abbreviation → full form) for improved recall.
    4. BM25 retrieval over all query variants; keep best score per chunk.
    5. Semantic retrieval via numpy batch cosine similarity (when API key present).
    6. RRF fusion of BM25 + semantic ranked lists.
    7. Two-signal reranking (keyword overlap + phrase proximity).
    8. Return top_k results.
    """
    # --- Load corpus ---
    stmt = select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
    if profile_id:
        stmt = stmt.where(Document.profile_id == profile_id)

    rows = session.execute(stmt).all()
    if not rows:
        return []

    chunks = [row[0] for row in rows]
    documents = [row[1] for row in rows]
    chunk_by_id: dict[str, Chunk] = {c.id: c for c in chunks}
    doc_by_chunk: dict[str, Document] = {c.id: d for c, d in zip(chunks, documents)}

    # --- Config ---
    top_k_fetch: int
    if settings is not None:
        top_k_fetch = settings.retrieval_top_k_fetch
        rrf_k = settings.rrf_k
        use_expansion = settings.use_query_expansion
        alpha = settings.retrieval_rrf_alpha
    else:
        top_k_fetch = max(top_k * 4, 20)
        rrf_k = 60.0
        use_expansion = True
        alpha = 0.5

    scope_id = document_id or profile_id or "global"

    # --- Query expansion ---
    query_variants = expand_query(query) if use_expansion and query.strip() else [query]

    # --- BM25 retrieval ---
    bm25_index = _get_or_build_bm25(scope_id, chunks)
    bm25_best: dict[str, float] = {}
    for variant in query_variants:
        for chunk_id, score in bm25_index.retrieve(tokenize(variant), top_k_fetch * 2):
            if score > bm25_best.get(chunk_id, 0.0):
                bm25_best[chunk_id] = score
    bm25_ranked = sorted(bm25_best.items(), key=lambda x: x[1], reverse=True)[:top_k_fetch]

    # --- Semantic retrieval (OpenAI or local SentenceTransformer) ---
    semantic_ranked: list[tuple[str, float]] = []
    if settings and query.strip() and any_embedding_available(settings):
        try:
            query_vector = embed_texts_for_retrieval(settings, [query])[0]
            chunk_embeddings = ensure_chunk_embeddings(session, chunks, settings)
            chunk_vectors = {
                cid: emb.vector
                for cid, emb in chunk_embeddings.items()
                if emb is not None
            }
            sim_scores = batch_cosine_similarity(query_vector, chunk_vectors)
            semantic_ranked = sorted(sim_scores.items(), key=lambda x: x[1], reverse=True)[:top_k_fetch]
        except Exception:
            semantic_ranked = []

    # --- RRF fusion ---
    if semantic_ranked:
        fused = _rrf_fuse(bm25_ranked, semantic_ranked, k=rrf_k, alpha=alpha)
    else:
        fused = bm25_ranked

    fused = fused[:top_k_fetch]

    # --- Normalise BM25 for score_components transparency ---
    bm25_vals = [s for _, s in bm25_ranked]
    bm25_min = min(bm25_vals) if bm25_vals else 0.0
    bm25_spread = max((max(bm25_vals) if bm25_vals else 1.0) - bm25_min, 1e-9)
    bm25_by_id = dict(bm25_ranked)
    semantic_by_id = dict(semantic_ranked)

    focus_tokens = tokenize(query) if include_structural_signals else []

    results: list[RetrievedChunk] = []
    for chunk_id, rrf_score in fused:
        chunk = chunk_by_id.get(chunk_id)
        doc = doc_by_chunk.get(chunk_id)
        if chunk is None or doc is None:
            continue

        raw_bm25 = bm25_by_id.get(chunk_id, 0.0)
        sem_raw = semantic_by_id.get(chunk_id, 0.0)

        components: dict[str, float] = {
            "lexical": round((raw_bm25 - bm25_min) / bm25_spread, 4),
            "semantic": round(max(0.0, min(1.0, (sem_raw + 1.0) / 2.0)), 4),
            "structural": 0.0,
            "rrf": round(rrf_score, 6),
        }

        if include_structural_signals and focus_tokens:
            components["structural"] = round(_structural_score(chunk.text, focus_tokens), 4)

        results.append(RetrievedChunk(chunk=chunk, document=doc, score=rrf_score, score_components=components))

    results.sort(key=lambda r: r.score, reverse=True)

    # --- Stage 1: keyword overlap + phrase proximity reranking ---
    from app.services.reranker import rerank as _rerank, cross_encoder_rerank, cross_encoder_available

    kw_w = settings.reranker_keyword_weight if settings else 0.6
    prox_w = settings.reranker_proximity_weight if settings else 0.4
    rerank_n = (settings.retrieval_top_k_rerank if settings else top_k) * 2

    candidates = results[:max(rerank_n, top_k * 2)]
    reranked = _rerank(candidates, query, keyword_weight=kw_w, proximity_weight=prox_w)

    # --- Stage 2: cross-encoder reranking (optional, much more accurate) ---
    if settings and cross_encoder_available(settings):
        # Only cross-encode the top candidates; model is accurate but not instant
        ce_candidates = reranked[:max(top_k * 3, 12)]
        reranked = cross_encoder_rerank(ce_candidates, query, settings)
        # Append any remaining candidates (below CE cutoff) unchanged
        ce_ids = {r.chunk.id for r in reranked}
        tail = [r for r in candidates if r.chunk.id not in ce_ids]
        reranked = reranked + tail

    selected = [r for r in reranked if r.score > 0][:top_k]
    return selected if selected else reranked[:top_k]


def retrieve_claim_context(
    session: Session,
    document_id: str,
    top_k: int,
    focus_areas: list[str] | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """Specialised retrieval for claim extraction — enables structural signals.

    Concatenates focus_areas as the search query so the BM25 + semantic
    retrievers home in on the sections most relevant to the claim type.
    """
    focus_query = " ".join(focus_areas or [])
    return search_chunks(
        session,
        query=focus_query,
        top_k=top_k,
        document_id=document_id,
        settings=settings,
        include_structural_signals=True,
    )
