import math

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, ChunkEmbedding


def embedding_available(settings: Settings) -> bool:
    return settings.enable_embedding_retrieval and bool(settings.openai_api_key)


def _client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = _client(settings).embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    return [list(item.embedding) for item in response.data]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def ensure_chunk_embeddings(session: Session, chunks: list[Chunk], settings: Settings) -> dict[str, ChunkEmbedding]:
    if not chunks or not embedding_available(settings):
        return {}

    chunk_ids = [chunk.id for chunk in chunks]
    existing_records = session.scalars(select(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids))).all()
    existing_by_id = {record.chunk_id: record for record in existing_records}

    stale_or_missing_chunks = [
        chunk
        for chunk in chunks
        if chunk.id not in existing_by_id or existing_by_id[chunk.id].model != settings.openai_embedding_model
    ]

    if stale_or_missing_chunks:
        vectors = embed_texts(settings, [chunk.text for chunk in stale_or_missing_chunks])
        for chunk, vector in zip(stale_or_missing_chunks, vectors, strict=True):
            existing = existing_by_id.get(chunk.id)
            if existing is None:
                existing = ChunkEmbedding(
                    chunk_id=chunk.id,
                    model=settings.openai_embedding_model,
                    dimensions=len(vector),
                    vector=vector,
                )
                session.add(existing)
                existing_by_id[chunk.id] = existing
            else:
                existing.model = settings.openai_embedding_model
                existing.dimensions = len(vector)
                existing.vector = vector
        session.flush()

    return existing_by_id
