import re
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Chunk, Document, Profile
from app.services.chunking import chunk_text
from app.services.embeddings import ensure_chunk_embeddings
from app.services.parsing import (
    UnsupportedDocumentError,
    compute_checksum,
    detect_mime_type,
    extract_text_from_path,
)


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename).strip("._")
    return cleaned or "document"


def ingest_uploaded_document(
    session: Session,
    upload_file: UploadFile,
    settings: Settings,
    profile: Profile,
) -> tuple[Document, int]:
    uploads_dir = Path(settings.uploads_dir) / profile.id
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = _sanitize_filename(upload_file.filename or "document")
    destination = uploads_dir / safe_filename
    stem = destination.stem
    suffix = destination.suffix
    sequence = 1
    while destination.exists():
        destination = uploads_dir / f"{stem}_{sequence}{suffix}"
        sequence += 1

    with destination.open("wb") as handle:
        shutil.copyfileobj(upload_file.file, handle)

    try:
        extracted_text, parse_metadata = extract_text_from_path(destination)
    except UnsupportedDocumentError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not extracted_text.strip():
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The uploaded document did not produce any text.")

    checksum = compute_checksum(destination)
    mime_type = upload_file.content_type or detect_mime_type(destination)
    document = Document(
        profile_id=profile.id,
        filename=safe_filename,
        storage_path=str(destination),
        source_type="upload",
        mime_type=mime_type,
        checksum=checksum,
        extracted_text=extracted_text,
        parse_metadata=parse_metadata,
    )
    session.add(document)
    session.flush()

    chunks = chunk_text(
        extracted_text,
        max_chars=settings.max_chunk_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )

    chunk_records: list[Chunk] = []
    for index, item in enumerate(chunks):
        chunk_record = Chunk(
            document_id=document.id,
            chunk_index=index,
            text=item["text"],
            token_count=item["token_count"],
            start_char=item["start_char"],
            end_char=item["end_char"],
            chunk_metadata={"source": "document_ingestion"},
        )
        session.add(chunk_record)
        chunk_records.append(chunk_record)

    session.flush()

    if chunk_records:
        try:
            ensure_chunk_embeddings(session, chunk_records, settings)
            document.parse_metadata = {
                **document.parse_metadata,
                "embedding_status": "indexed" if settings.enable_embedding_retrieval and settings.openai_api_key else "disabled",
                "embedding_model": settings.openai_embedding_model if settings.enable_embedding_retrieval and settings.openai_api_key else None,
            }
        except Exception as exc:
            document.parse_metadata = {
                **document.parse_metadata,
                "embedding_status": f"failed:{exc.__class__.__name__}",
                "embedding_model": settings.openai_embedding_model,
            }

    session.commit()
    session.refresh(document)
    return document, len(chunks)


def delete_document_evidence(session: Session, document: Document) -> str | None:
    storage_path = document.storage_path
    session.delete(document)
    session.flush()
    return storage_path


def cleanup_document_storage(storage_path: str | None) -> None:
    if not storage_path:
        return

    path = Path(storage_path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return

    parent = path.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return
