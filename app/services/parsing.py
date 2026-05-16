import hashlib
import mimetypes
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.services.pdf_layout import extract_pdf_layout


TEXT_LIKE_SUFFIXES = {
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
}


class UnsupportedDocumentError(ValueError):
    pass


def detect_mime_type(path: Path) -> str | None:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed


def compute_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_text_from_path(path: Path) -> tuple[str, dict]:
    suffix = path.suffix.lower()

    if suffix in TEXT_LIKE_SUFFIXES:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return content, {"parser": "plain_text"}

    if suffix == ".pdf":
        try:
            layout = extract_pdf_layout(path)
            return layout["text"], {
                "parser": layout["parser"],
                "page_count": layout["page_count"],
                "block_count": layout["block_count"],
                "link_count": layout["link_count"],
            }
        except Exception:
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages), {"parser": "pypdf", "page_count": len(reader.pages)}

    if suffix == ".docx":
        document = DocxDocument(str(path))
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs), {"parser": "python-docx", "paragraph_count": len(paragraphs)}

    raise UnsupportedDocumentError(f"Unsupported document type: {suffix or 'unknown'}")
