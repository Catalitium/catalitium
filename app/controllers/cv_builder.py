"""CV Builder — upload any CV, download a Harvard-format DOCX (session + CSRF on POST)."""
from __future__ import annotations

import io

from flask import Blueprint, render_template, request, send_file

from ..models.cv import CVExtractionError, extract_cv_from_upload, normalize_cv_text
from ..services.cv_filler import render_cv
from ..services.cv_mapper import extract_cv_structure
from ..utils import api_error_response, csrf_valid

bp = Blueprint("cv_builder", __name__)


@bp.get("/cv-builder")
def cv_builder_page():
    return render_template("cv_builder.html")


@bp.post("/cv-builder/generate")
def cv_builder_generate():
    """Accept CV upload or pasted text, return a Harvard-format .docx download."""
    if not csrf_valid():
        return api_error_response(
            "invalid_csrf", "Session expired. Please refresh and try again.", 400
        )

    upload = request.files.get("cv_file")
    text_fallback = (request.form.get("cv_text") or "").strip()
    has_file = bool(upload and (upload.filename or "").strip())

    if not has_file and not text_fallback:
        return api_error_response(
            "missing_input", "Upload a PDF or DOCX file, or paste your CV text.", 400
        )
    if has_file and text_fallback:
        return api_error_response(
            "conflicting_inputs",
            "Provide a file upload OR pasted text, not both.",
            400,
        )

    try:
        if has_file:
            extracted = extract_cv_from_upload(upload)
            cv_text = extracted.text
            stem = extracted.filename.rsplit(".", 1)[0]
            out_name = f"{stem}_harvard.docx"
        else:
            cv_text = normalize_cv_text(text_fallback)
            out_name = "cv_harvard.docx"
    except CVExtractionError as exc:
        return api_error_response(exc.code, exc.message, exc.status)

    try:
        data = extract_cv_structure(cv_text)
    except Exception as exc:  # pragma: no cover
        return api_error_response(
            "mapping_failed", f"CV structure extraction failed: {exc}", 500
        )

    try:
        docx_bytes = render_cv(data)
    except Exception as exc:  # pragma: no cover
        return api_error_response("render_failed", f"CV render failed: {exc}", 500)

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=out_name,
    )
