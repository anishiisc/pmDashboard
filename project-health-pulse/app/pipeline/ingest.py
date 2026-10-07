from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from app import settings

_HEADER_RE = re.compile(r"^(MEETING|DATE|ATTENDEES):\s*(.+)$")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _decode_bytes(raw: bytes) -> tuple[str, str]:
    """Try UTF-8 then latin-1. Return (text, encoding_used)."""
    # Strip BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text


def _parse_header(lines: list[str]) -> tuple[dict[str, str], int, list[str]]:
    """Return header dict, index of separator line, and warnings."""
    header: dict[str, str] = {}
    warnings: list[str] = []
    sep_idx = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            sep_idx = i
            break
        m = _HEADER_RE.match(line.strip())
        if m:
            header[m.group(1)] = m.group(2).strip()
    if "DATE" not in header:
        warnings.append("DATE field missing from header; date set to null")
    return header, sep_idx, warnings


def ingest_files(file_paths: list[dict]) -> tuple[list[dict], str]:
    """
    Ingest and normalise transcript files.

    Args:
        file_paths: list of {"filename": str, "path": str}

    Returns:
        (document_index, combined_prompt_text)
        document_index: list of dicts with doc_id, filename, date, meeting, line_count, warnings
        combined_prompt_text: the formatted <transcript> blocks for the LLM
    """
    if len(file_paths) > settings.MAX_FILES:
        raise ValueError(f"Too many files: {len(file_paths)} > {settings.MAX_FILES}")

    total_chars = 0
    parsed: list[dict] = []

    for item in file_paths:
        fname = item["filename"]
        path = Path(item["path"])

        if not fname.lower().endswith(".txt"):
            raise ValueError(f"Only .txt files accepted: {fname}")

        raw = path.read_bytes()
        size_kb = len(raw) / 1024
        if size_kb > settings.MAX_FILE_KB:
            raise ValueError(f"{fname} exceeds {settings.MAX_FILE_KB} KB limit ({size_kb:.1f} KB)")

        text, _enc = _decode_bytes(raw)
        text = _normalise(text)
        total_chars += len(text)
        if total_chars > settings.MAX_TOTAL_CHARS:
            raise ValueError(
                f"Total character limit ({settings.MAX_TOTAL_CHARS}) exceeded after adding {fname}"
            )

        lines = text.split("\n")
        header, sep_idx, warnings = _parse_header(lines)

        meeting_date: date | None = None
        if "DATE" in header:
            meeting_date = _parse_date(header["DATE"])
            if meeting_date is None:
                warnings.append(f"Could not parse DATE value: {header['DATE']!r}")

        body_lines = lines[sep_idx + 1 :]

        parsed.append(
            {
                "filename": fname,
                "meeting": header.get("MEETING", ""),
                "date": meeting_date,
                "attendees": header.get("ATTENDEES", ""),
                "body_lines": body_lines,
                "warnings": warnings,
            }
        )

    # Sort by date ascending; undated files go last
    parsed.sort(key=lambda x: (x["date"] is None, x["date"] or date.max))

    document_index: list[dict] = []
    prompt_blocks: list[str] = []

    for i, doc in enumerate(parsed):
        doc_id = f"D{i + 1}"
        date_str = doc["date"].isoformat() if doc["date"] else None

        # Build line-referenced body
        ref_lines: list[str] = []
        for j, line in enumerate(doc["body_lines"], start=1):
            ref = f"{doc_id}:L{j:03d}"
            ref_lines.append(f"{ref} | {line}")

        block = (
            f'<transcript doc_id="{doc_id}" filename="{doc["filename"]}"'
            f' date="{date_str or ""}" meeting="{doc["meeting"]}">\n'
            + "\n".join(ref_lines)
            + "\n</transcript>"
        )
        prompt_blocks.append(block)

        document_index.append(
            {
                "doc_id": doc_id,
                "filename": doc["filename"],
                "date": date_str,
                "meeting": doc["meeting"],
                "line_count": len(doc["body_lines"]),
                "warnings": doc["warnings"],
            }
        )

        # Store line map on doc for grounding
        doc["doc_id"] = doc_id
        doc["ref_lines"] = ref_lines  # kept in-memory for S2

    combined_text = "\n\n".join(prompt_blocks)
    return document_index, combined_text, parsed  # type: ignore[return-value]
