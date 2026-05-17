import hashlib
import math
from functools import lru_cache

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, ChunkEmbedding, CorrectionEmbedding

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional runtime dependency
    SentenceTransformer = None


def embedding_available(settings: Settings) -> bool:
    return settings.enable_embedding_retrieval and bool(settings.openai_api_key)


def _client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _coerce_float_vector(values) -> list[float]:
    return [float(value) for value in values]


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = _client(settings).embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    return [_coerce_float_vector(item.embedding) for item in response.data]


def correction_embedding_provider(settings: Settings) -> str:
    return (settings.correction_embedding_provider or "openai").lower()


def correction_embedding_model_name(settings: Settings) -> str:
    provider = correction_embedding_provider(settings)
    if provider == "local":
        return settings.correction_local_embedding_model
    return settings.openai_embedding_model


def correction_embedding_available(settings: Settings) -> bool:
    if not settings.enable_embedding_retrieval:
        return False
    provider = correction_embedding_provider(settings)
    if provider == "local":
        return SentenceTransformer is not None
    return bool(settings.openai_api_key)


@lru_cache(maxsize=4)
def _local_sentence_model(model_name: str, cache_dir: str | None) -> SentenceTransformer:
    if SentenceTransformer is None:  # pragma: no cover - guarded by correction_embedding_available
        raise RuntimeError("sentence-transformers is not installed")
    kwargs = {"model_name_or_path": model_name}
    if cache_dir:
        kwargs["cache_folder"] = cache_dir
    return SentenceTransformer(**kwargs)


def embed_correction_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    provider = correction_embedding_provider(settings)
    if provider == "local":
        model = _local_sentence_model(settings.correction_local_embedding_model, settings.correction_local_embedding_cache_dir)
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [_coerce_float_vector(vector) for vector in vectors]
    return embed_texts(settings, texts)


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


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_correction_embeddings(
    session: Session,
    *,
    profile_id: str,
    texts: list[str],
    settings: Settings,
    embedding_kind: str,
) -> tuple[list[list[float]], dict[str, int]]:
    if not texts or not correction_embedding_available(settings):
        return [], {"hits": 0, "misses": 0}

    provider = correction_embedding_provider(settings)
    model_name = correction_embedding_model_name(settings)

    unique_texts: list[str] = []
    seen_texts: set[str] = set()
    for text in texts:
        cleaned = text.strip()
        if not cleaned or cleaned in seen_texts:
            continue
        seen_texts.add(cleaned)
        unique_texts.append(cleaned)

    hashes = {_text_hash(text): text for text in unique_texts}
    existing_rows = list(
        session.scalars(
            select(CorrectionEmbedding).where(
                CorrectionEmbedding.profile_id == profile_id,
                CorrectionEmbedding.embedding_kind == embedding_kind,
                CorrectionEmbedding.provider == provider,
                CorrectionEmbedding.model == model_name,
                CorrectionEmbedding.text_hash.in_(list(hashes.keys())),
            )
        ).all()
    )
    existing_by_hash = {row.text_hash: row for row in existing_rows}

    missing_texts = [text for text in unique_texts if _text_hash(text) not in existing_by_hash]
    if missing_texts:
        vectors = embed_correction_texts(settings, missing_texts)
        for text, vector in zip(missing_texts, vectors, strict=True):
            row = CorrectionEmbedding(
                profile_id=profile_id,
                embedding_kind=embedding_kind,
                text_hash=_text_hash(text),
                text_value=text,
                provider=provider,
                model=model_name,
                dimensions=len(vector),
                vector=vector,
                hit_count=0,
            )
            session.add(row)
            existing_by_hash[row.text_hash] = row
        session.flush()

    ordered_vectors: list[list[float]] = []
    hit_count = 0
    miss_count = 0
    for text in texts:
        cleaned = text.strip()
        if not cleaned:
            ordered_vectors.append([])
            continue
        row = existing_by_hash.get(_text_hash(cleaned))
        if row is None:
            ordered_vectors.append([])
            miss_count += 1
            continue
        if cleaned not in missing_texts:
            row.hit_count += 1
            hit_count += 1
        else:
            miss_count += 1
        ordered_vectors.append(_coerce_float_vector(row.vector))

    session.flush()
    return ordered_vectors, {"hits": hit_count, "misses": miss_count}
