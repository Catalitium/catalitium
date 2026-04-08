#!/usr/bin/env python3
"""Replace em dashes (U+2014 / &mdash;) in user-facing copy with commas, pipes (titles), hyphens, or en dashes (ranges)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "app" / "views" / "templates",
    ROOT / "app" / "static" / "manifest.json",
    ROOT / "app" / "static" / "js" / "chat-widget.js",
    ROOT / "scripts" / "send_welcome_backfill.py",
]

TITLE_MARKERS = (
    "block title",
    'property="og:title"',
    'name="twitter:title"',
    "property='og:title'",
    "name='twitter:title'",
)


def fix_content(raw: str) -> str:
    lines = raw.split("\n")
    out_lines: list[str] = []
    for line in lines:
        if any(m in line for m in TITLE_MARKERS):
            line = line.replace(" — ", " | ")
            line = line.replace("&mdash;", " | ")
        out_lines.append(line)
    text = "\n".join(out_lines)

    # Numeric / currency ranges: keep a single en dash (not em)
    text = re.sub(r"([\d$%])&mdash;([\d$%\d])", r"\1–\2", text)
    text = re.sub(r"(\d)—(\d)", r"\1–\2", text)

    # Clause-style em dash with spaces → comma
    text = text.replace(" &mdash; ", ", ")
    text = text.replace(" — ", ", ")

    # Remaining entities / characters → hyphen (placeholders, tight punctuation, cites)
    text = text.replace("&mdash;", "-")
    text = text.replace("—", "-")

    # Titles may now contain " | " doubled if original had tight &mdash;; normalize " |  | " → " | "
    text = re.sub(r" \| +\| ", " | ", text)

    return text


def main() -> int:
    changed = 0
    for base in TARGETS:
        if not base.exists():
            continue
        paths = [base] if base.is_file() else sorted(base.rglob("*.html"))
        for path in paths:
            raw = path.read_text(encoding="utf-8")
            new = fix_content(raw)
            if new != raw:
                path.write_text(new, encoding="utf-8")
                print(path.relative_to(ROOT))
                changed += 1
    print(f"Updated {changed} files.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
