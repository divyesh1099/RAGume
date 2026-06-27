import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException, UploadFile

from app.config import Settings
from app.services.parsing import UnsupportedDocumentError, extract_text_from_path


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename).strip("._")
    return cleaned or "job_description"


def parse_uploaded_job_description(upload_file: UploadFile, settings: Settings) -> tuple[str, dict, str]:
    safe_filename = _sanitize_filename(upload_file.filename or "job_description.txt")

    with TemporaryDirectory() as temp_dir:
        destination = Path(temp_dir) / safe_filename
        with destination.open("wb") as handle:
            shutil.copyfileobj(upload_file.file, handle)

        size_bytes = destination.stat().st_size
        if size_bytes > settings.max_upload_size_bytes:
            size_mb = size_bytes / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{safe_filename} is {size_mb:.1f} MB, "
                    f"which exceeds the {settings.max_upload_size_mb} MB upload limit."
                ),
            )

        try:
            extracted_text, parse_metadata = extract_text_from_path(destination)
        except UnsupportedDocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not extracted_text.strip():
            raise HTTPException(status_code=422, detail="The uploaded job description did not produce any text.")

        return extracted_text, parse_metadata, safe_filename
