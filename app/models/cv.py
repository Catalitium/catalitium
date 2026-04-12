"""CV extraction helpers for PDF and DOCX uploads (DB-adjacent parsing)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader

ALLOWED_EXTENSIONS = {"pdf", "docx"}
MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # 4MB safeguard for parser memory.
MAX_TEXT_CHARS = 50_000


@dataclass
class ExtractedCV:
    """Normalized extracted CV payload."""

    text: str
    filename: str
    extension: str
    byte_size: int
    original_chars: int
    truncated: bool


class CVExtractionError(ValueError):
    """Typed extraction error with API-friendly metadata."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def extract_cv_from_upload(upload: Any) -> ExtractedCV:
    """Extract and normalize CV text from a Werkzeug FileStorage object."""
    filename = (getattr(upload, "filename", "") or "").strip()
    if not filename:
        raise CVExtractionError("missing_file_name", "Please select a PDF or DOCX CV file.")
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise CVExtractionError("unsupported_file_type", "Only PDF and DOCX files are supported.")

    try:
        seek = getattr(upload, "seek", None)
        if callable(seek):
            seek(0)
    except Exception:
        pass
    raw = upload.read() or b""
    if not raw:
        raise CVExtractionError("empty_file", "The uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CVExtractionError("file_too_large", "CV file is too large. Keep it under 4MB.", 413)

    if extension == "pdf":
        parsed = _extract_pdf(raw)
    else:
        parsed = _extract_docx(raw)

    normalized = _normalize_text(parsed)
    if not normalized:
        raise CVExtractionError(
            "no_extractable_text",
            "Could not extract readable text from the file. Try a different CV export.",
        )

    original_chars = len(normalized)
    truncated = original_chars > MAX_TEXT_CHARS
    text = normalized[:MAX_TEXT_CHARS]
    return ExtractedCV(
        text=text,
        filename=filename,
        extension=extension,
        byte_size=len(raw),
        original_chars=original_chars,
        truncated=truncated,
    )


def normalize_cv_text(raw_text: str) -> str:
    """Normalize user-provided text fallback from textarea payloads."""
    text = _normalize_text(raw_text)
    if not text:
        raise CVExtractionError("empty_text", "Please paste CV text or upload a PDF/DOCX file.")
    original_chars = len(text)
    if original_chars > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def _extract_pdf(raw_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    except Exception as exc:  # pragma: no cover - parser internals
        raise CVExtractionError("pdf_parse_failed", "Unable to read this PDF CV.") from exc


def _extract_docx(raw_bytes: bytes) -> str:
    try:
        doc = Document(io.BytesIO(raw_bytes))
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs)
    except Exception as exc:  # pragma: no cover - parser internals
        raise CVExtractionError("docx_parse_failed", "Unable to read this DOCX CV.") from exc


def _normalize_text(text: str) -> str:
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
