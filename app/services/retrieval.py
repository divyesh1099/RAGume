import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, Document
from app.services.embeddings import cosine_similarity, embedding_available, embed_texts, ensure_chunk_embeddings
from app.services.claim_utils import ACTION_VERBS, tokenize


@dataclass
class RetrievedChunk:
    chunk: Chunk
    document: Document
    score: float
    score_components: dict[str, float]


def _bm25_score(query_tokens: list[str], chunk_tokens: list[str], document_frequencies: dict[str, int], total_docs: int, average_length: float) -> float:
    if not query_tokens or not chunk_tokens:
        return 0.0

    term_frequencies: dict[str, int] = {}
    for token in chunk_tokens:
        term_frequencies[token] = term_frequencies.get(token, 0) + 1

    k1 = 1.5
    b = 0.75
    score = 0.0
    doc_length = len(chunk_tokens)

    for token in query_tokens:
        df = document_frequencies.get(token, 0)
        if df == 0:
            continue
        idf = math.log(1 + ((total_docs - df + 0.5) / (df + 0.5)))
        tf = term_frequencies.get(token, 0)
        if tf == 0:
            continue
        denominator = tf + k1 * (1 - b + b * (doc_length / max(average_length, 1)))
        score += idf * ((tf * (k1 + 1)) / denominator)

    return score


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if math.isclose(minimum, maximum):
        if math.isclose(maximum, 0.0):
            return {key: 0.0 for key in scores}
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}


def _structural_claim_score(chunk_text: str, focus_tokens: list[str]) -> float:
    score = 0.0
    text_lower = chunk_text.lower()
    for verb in ACTION_VERBS:
        if verb in text_lower:
            score += 1.2
    if any(character.isdigit() for character in chunk_text):
        score += 0.8
    if "-" in chunk_text or "*" in chunk_text or "\n" in chunk_text:
        score += 0.4
    if focus_tokens:
        chunk_tokens = set(tokenize(chunk_text))
        score += sum(0.9 for token in focus_tokens if token in chunk_tokens)
    return score


def search_chunks(
    session: Session,
    query: str,
    top_k: int = 5,
    document_id: str | None = None,
    profile_id: str | None = None,
    settings: Settings | None = None,
    include_structural_signals: bool = False,
) -> list[RetrievedChunk]:
    statement = select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
    if document_id:
        statement = statement.where(Chunk.document_id == document_id)
    if profile_id:
        statement = statement.where(Document.profile_id == profile_id)

    rows = session.execute(statement).all()
    if not rows:
        return []

    chunks = [row[0] for row in rows]
    documents = [row[1] for row in rows]

    tokenized_chunks = [tokenize(chunk.text) for chunk in chunks]
    document_frequencies: dict[str, int] = {}
    for token_list in tokenized_chunks:
        for token in set(token_list):
            document_frequencies[token] = document_frequencies.get(token, 0) + 1

    query_tokens = tokenize(query)
    average_length = sum(len(tokens) for tokens in tokenized_chunks) / max(len(tokenized_chunks), 1)
    lexical_scores: dict[str, float] = {}
    structural_scores: dict[str, float] = {}
    semantic_scores: dict[str, float] = {}

    for chunk, token_list in zip(chunks, tokenized_chunks, strict=True):
        lexical_scores[chunk.id] = _bm25_score(
            query_tokens,
            token_list,
            document_frequencies,
            len(tokenized_chunks),
            average_length,
        )
        if include_structural_signals:
            structural_scores[chunk.id] = _structural_claim_score(chunk.text, query_tokens)

    if settings and query.strip() and embedding_available(settings):
        try:
            query_vector = embed_texts(settings, [query])[0]
            chunk_embeddings = ensure_chunk_embeddings(session, chunks, settings)
            for chunk in chunks:
                embedding = chunk_embeddings.get(chunk.id)
                if embedding is None:
                    continue
                semantic_scores[chunk.id] = cosine_similarity(query_vector, embedding.vector)
        except Exception:
            semantic_scores = {}

    normalized_lexical = _normalize_scores(lexical_scores)
    normalized_structural = _normalize_scores(structural_scores)
    normalized_semantic = {
        key: max(0.0, min(1.0, (value + 1.0) / 2.0))
        for key, value in semantic_scores.items()
    }

    ranked: list[RetrievedChunk] = []
    for chunk, document in zip(chunks, documents, strict=True):
        components = {
            "lexical": round(normalized_lexical.get(chunk.id, 0.0), 4),
            "semantic": round(normalized_semantic.get(chunk.id, 0.0), 4),
            "structural": round(normalized_structural.get(chunk.id, 0.0), 4),
        }
        available_weights: list[tuple[str, float]] = []
        if components["lexical"] > 0 or query.strip():
            available_weights.append(("lexical", settings.hybrid_lexical_weight if settings else 0.7))
        if chunk.id in normalized_semantic:
            available_weights.append(("semantic", settings.hybrid_semantic_weight if settings else 0.3))
        if include_structural_signals:
            available_weights.append(("structural", settings.hybrid_structural_weight if settings else 0.2))

        if not available_weights:
            available_weights = [("lexical", 1.0)]

        weight_total = sum(weight for _, weight in available_weights) or 1.0
        score = sum(components[name] * (weight / weight_total) for name, weight in available_weights)
        ranked.append(RetrievedChunk(chunk=chunk, document=document, score=score, score_components=components))

    ranked.sort(key=lambda item: item.score, reverse=True)
    selected = [item for item in ranked if item.score > 0][:top_k]
    return selected if selected else ranked[:top_k]


def retrieve_claim_context(
    session: Session,
    document_id: str,
    top_k: int,
    focus_areas: list[str] | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    focus_query = " ".join(focus_areas or [])
    return search_chunks(
        session,
        query=focus_query,
        top_k=top_k,
        document_id=document_id,
        settings=settings,
        include_structural_signals=True,
    )
