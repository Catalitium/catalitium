#!/usr/bin/env python3
"""Validate Market Research report quality requirements.

Checks each report declared in app/factory.py for:
- template file exists
- methodology section present
- sources section present
- visual content markers present
- downloadable PDF configured and file exists in app/static

Exit code is non-zero when any report fails.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "app" / "factory.py"
TEMPLATES_DIR = ROOT / "app" / "views" / "templates"
STATIC_DIR = ROOT / "app" / "static"


def _extract_reports_literal(app_py: str) -> str:
    marker = "REPORTS = ["
    start = app_py.find(marker)
    if start == -1:
        raise ValueError("Could not find REPORTS declaration in app/factory.py")
    cursor = start + len("REPORTS = ")
    text = app_py[cursor:]
    depth = 0
    end = None
    for idx, ch in enumerate(text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        raise ValueError("Could not parse REPORTS list boundaries")
    return text[:end]


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def _has_visuals(text: str) -> bool:
    markers = r"<img|<svg|<canvas|chart|plot"
    return len(re.findall(markers, text, flags=re.IGNORECASE)) >= 1


def main() -> int:
    app_source = APP_FILE.read_text(encoding="utf-8")
    reports_literal = _extract_reports_literal(app_source)
    reports = ast.literal_eval(reports_literal)

    failures: list[str] = []

    print(f"Validating {len(reports)} market research reports...\n")
    for report in reports:
        slug = report.get("slug", "<missing-slug>")
        template_rel = report.get("template", "reports/report.html")
        template_path = TEMPLATES_DIR / template_rel
        pdf_rel = report.get("pdf_path", "")
        pdf_path = STATIC_DIR / pdf_rel if pdf_rel else None

        template_exists = template_path.exists()
        template_text = template_path.read_text(encoding="utf-8") if template_exists else ""
        has_methodology = _has(r"\bmethodology\b", template_text)
        has_sources = _has(r"\bsources?\b", template_text)
        has_visuals = _has_visuals(template_text)
        has_pdf = bool(pdf_rel) and bool(pdf_path and pdf_path.exists())

        report_issues: list[str] = []
        if not template_exists:
            report_issues.append(f"template missing: {template_rel}")
        if not has_methodology:
            report_issues.append("missing methodology section")
        if not has_sources:
            report_issues.append("missing sources section")
        if not has_visuals:
            report_issues.append("missing visual markers (svg/img/canvas/chart/plot)")
        if not pdf_rel:
            report_issues.append("missing pdf_path")
        elif not has_pdf:
            report_issues.append(f"pdf file missing: app/static/{pdf_rel}")

        if report_issues:
            failures.append(slug)
            print(f"[FAIL] {slug}")
            for issue in report_issues:
                print(f"  - {issue}")
        else:
            print(f"[OK]   {slug}")
        print()

    if failures:
        print(f"Validation failed: {len(failures)} report(s) need fixes.")
        return 1

    print("Validation passed: all reports meet baseline requirements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
