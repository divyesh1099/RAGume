import json
import re
from dataclasses import dataclass, field

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Claim, Chunk, Document
from app.services.claim_utils import (
    ACTION_VERBS,
    claims_are_duplicates,
    extract_skills,
    infer_category,
    merge_support_chunk_ids,
    normalize_claim,
)
from app.services.retrieval import RetrievedChunk, retrieve_claim_context

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class ClaimExtractionRun:
    extractor_mode: str
    claims: list[dict]
    warnings: list[str] = field(default_factory=list)


def split_candidate_sentences(text: str) -> list[str]:
    raw_parts = SENTENCE_SPLIT_PATTERN.split(text)
    candidates: list[str] = []
    for part in raw_parts:
        cleaned = part.strip().lstrip("-* ").strip()
        if cleaned:
            candidates.append(cleaned)
    return candidates


def is_claim_like(sentence: str) -> bool:
    if len(sentence) < 35 or len(sentence) > 280:
        return False

    lowered = sentence.lower()
    has_action = any(verb in lowered for verb in ACTION_VERBS)
    has_signal = any(character.isdigit() for character in sentence) or bool(extract_skills(sentence))
    if has_action and has_signal:
        return True
    return has_action and len(sentence.split()) >= 8


def estimate_confidence(sentence: str, skills: list[str], source_score: float) -> float:
    confidence = 0.45
    if any(character.isdigit() for character in sentence):
        confidence += 0.15
    if skills:
        confidence += min(0.2, len(skills) * 0.05)
    if sentence[:1].isupper():
        confidence += 0.05
    confidence += min(0.15, source_score * 0.03)
    return round(min(confidence, 0.95), 2)


def heuristic_claim_extraction(retrieved_chunks: list[RetrievedChunk], max_claims: int) -> list[dict]:
    ranked_claims: list[dict] = []

    for retrieved in retrieved_chunks:
        for sentence in split_candidate_sentences(retrieved.chunk.text):
            if not is_claim_like(sentence):
                continue
            skills = extract_skills(sentence)
            ranked_claims.append(
                {
                    "text": sentence,
                    "category": infer_category(sentence),
                    "skills": skills,
                    "confidence": estimate_confidence(sentence, skills, retrieved.score),
                    "support_chunk_ids": [retrieved.chunk.id],
                    "rationale": "Heuristic extraction from retrieved evidence chunk.",
                }
            )

    ranked_claims.sort(key=lambda item: item["confidence"], reverse=True)
    deduped: list[dict] = []
    for item in ranked_claims:
        merged_into_existing = False
        for existing in deduped:
            if claims_are_duplicates(item["text"], existing["text"], item["skills"], existing["skills"]):
                existing["support_chunk_ids"] = merge_support_chunk_ids(
                    existing["support_chunk_ids"],
                    item["support_chunk_ids"],
                )
                existing["confidence"] = max(existing["confidence"], item["confidence"])
                merged_into_existing = True
                break
        if merged_into_existing:
            continue
        deduped.append(item)
        if len(deduped) >= max_claims:
            break

    return deduped


def llm_claim_extraction(retrieved_chunks: list[RetrievedChunk], settings: Settings, max_claims: int) -> list[dict]:
    if not settings.enable_llm_extractor or not settings.openai_api_key:
        return []

    client = OpenAI(api_key=settings.openai_api_key)
    chunk_payload = [
        {"chunk_id": item.chunk.id, "chunk_index": item.chunk.chunk_index, "text": item.chunk.text}
        for item in retrieved_chunks
    ]

    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract resume-safe claims from evidence. Only use information explicitly present in the chunks. "
                    "Return JSON with a top-level 'claims' array. Each claim needs text, category, skills, "
                    "confidence, support_chunk_ids, and rationale."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "max_claims": max_claims,
                        "instructions": [
                            "Prefer quantifiable, implementation-heavy statements.",
                            "Do not invent missing metrics.",
                            "Keep each claim under 220 characters.",
                        ],
                        "chunks": chunk_payload,
                    }
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    claims = parsed.get("claims", [])

    cleaned: list[dict] = []
    valid_chunk_ids = {item.chunk.id for item in retrieved_chunks}
    for claim in claims:
        support_chunk_ids = [chunk_id for chunk_id in claim.get("support_chunk_ids", []) if chunk_id in valid_chunk_ids]
        text = (claim.get("text") or "").strip()
        if not text:
            continue
        cleaned.append(
            {
                "text": text,
                "category": claim.get("category") or infer_category(text),
                "skills": list(dict.fromkeys(claim.get("skills") or extract_skills(text))),
                "confidence": float(claim.get("confidence") or 0.7),
                "support_chunk_ids": support_chunk_ids or [retrieved_chunks[0].chunk.id],
                "rationale": claim.get("rationale") or "LLM extraction from retrieved evidence chunks.",
            }
        )
    return cleaned[:max_claims]


def extract_claims_for_document(
    session: Session,
    document: Document,
    settings: Settings,
    focus_areas: list[str] | None = None,
    max_claims: int | None = None,
) -> tuple[list[RetrievedChunk], list[Claim], str, list[str]]:
    retrieved_chunks = retrieve_claim_context(
        session,
        document_id=document.id,
        top_k=settings.claim_context_top_k,
        focus_areas=focus_areas or [],
        settings=settings,
    )

    limit = min(max_claims or settings.max_claims_per_run, settings.max_claims_per_run)
    warnings: list[str] = []
    extractor_mode = "heuristic"
    extracted: list[dict] = []

    if settings.enable_llm_extractor and settings.openai_api_key:
        try:
            extracted = llm_claim_extraction(retrieved_chunks, settings, limit)
            if extracted:
                extractor_mode = "llm"
            else:
                warnings.append("The LLM returned no usable claims, so heuristic extraction was used.")
        except Exception as exc:
            warnings.append(f"LLM extraction failed with {exc.__class__.__name__}; heuristic extraction was used instead.")

    if not extracted:
        extracted = heuristic_claim_extraction(retrieved_chunks, limit)
        extractor_mode = "heuristic"

    existing_claims = session.scalars(select(Claim).where(Claim.document_id == document.id)).all()
    saved_claims: list[Claim] = []

    for item in extracted:
        normalized = normalize_claim(item["text"])
        if not normalized:
            continue
        duplicate_claim = next(
            (
                claim
                for claim in existing_claims
                if claims_are_duplicates(item["text"], claim.text, item["skills"], claim.skills)
            ),
            None,
        )
        if duplicate_claim is not None:
            duplicate_claim.support_chunk_ids = merge_support_chunk_ids(
                duplicate_claim.support_chunk_ids,
                item["support_chunk_ids"],
            )
            duplicate_claim.confidence = max(duplicate_claim.confidence, item["confidence"])
            if duplicate_claim.rationale and item["rationale"] not in duplicate_claim.rationale:
                duplicate_claim.rationale = f"{duplicate_claim.rationale} | {item['rationale']}"
            elif not duplicate_claim.rationale:
                duplicate_claim.rationale = item["rationale"]
            continue
        claim = Claim(
            document_id=document.id,
            text=item["text"],
            normalized_text=normalized,
            category=item["category"],
            skills=item["skills"],
            confidence=item["confidence"],
            status="pending",
            support_chunk_ids=item["support_chunk_ids"],
            rationale=item["rationale"],
        )
        session.add(claim)
        saved_claims.append(claim)
        existing_claims.append(claim)

    session.commit()
    for claim in saved_claims:
        session.refresh(claim)

    return retrieved_chunks, saved_claims, extractor_mode, warnings


def fetch_chunk_evidence(session: Session, chunk_ids: list[str]) -> list[dict]:
    if not chunk_ids:
        return []
    chunks = session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids))).all()
    by_id = {
        chunk.id: {
            "chunk_id": chunk.id,
            "text": chunk.text,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
        }
        for chunk in chunks
    }
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
