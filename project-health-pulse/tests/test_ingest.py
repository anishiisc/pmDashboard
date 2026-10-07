from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.pipeline.ingest import ingest_files


def _make_file(tmp_dir: Path, filename: str, content: str) -> dict:
    p = tmp_dir / filename
    p.write_text(content, encoding="utf-8")
    return {"filename": filename, "path": str(p)}


VALID_TRANSCRIPT = """\
MEETING: Test Meeting
DATE: 2026-09-01
ATTENDEES: Alice (PM, Delivery); Bob (Tech, Client)
---
[00:00:01] Alice (PM): Good morning.
[00:00:05] Bob (Tech): Morning.
[00:00:10] Alice (PM): Let's get started.
"""


def test_basic_parse():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [_make_file(tmp, "t1.txt", VALID_TRANSCRIPT)]
        index, prompt, parsed = ingest_files(files)

    assert len(index) == 1
    doc = index[0]
    assert doc["doc_id"] == "D1"
    assert doc["filename"] == "t1.txt"
    assert doc["date"] == "2026-09-01"
    assert doc["meeting"] == "Test Meeting"
    assert doc["warnings"] == []


def test_line_references_in_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [_make_file(tmp, "t1.txt", VALID_TRANSCRIPT)]
        index, prompt, parsed = ingest_files(files)

    assert "D1:L001" in prompt
    assert "D1:L002" in prompt


def test_missing_date_warning():
    content = """\
MEETING: Test Meeting
ATTENDEES: Alice (PM, Delivery)
---
[00:00:01] Alice (PM): Hello.
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [_make_file(tmp, "t1.txt", content)]
        index, prompt, parsed = ingest_files(files)

    assert index[0]["date"] is None
    assert any("DATE" in w for w in index[0]["warnings"])


def test_date_sorted_ascending():
    t1 = VALID_TRANSCRIPT  # 2026-09-01
    t2 = """\
MEETING: Later Meeting
DATE: 2026-09-08
ATTENDEES: Alice (PM, Delivery)
---
[00:00:01] Alice (PM): Hello again.
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Upload in reverse order
        files = [
            _make_file(tmp, "later.txt", t2),
            _make_file(tmp, "earlier.txt", t1),
        ]
        index, prompt, parsed = ingest_files(files)

    # Earlier date should be D1
    assert index[0]["date"] == "2026-09-01"
    assert index[1]["date"] == "2026-09-08"
    assert index[0]["doc_id"] == "D1"
    assert index[1]["doc_id"] == "D2"


def test_undated_file_goes_last():
    dated = VALID_TRANSCRIPT  # 2026-09-01
    undated = """\
MEETING: Undated Meeting
ATTENDEES: Alice (PM, Delivery)
---
[00:00:01] Alice (PM): No date here.
"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [
            _make_file(tmp, "undated.txt", undated),
            _make_file(tmp, "dated.txt", dated),
        ]
        index, prompt, parsed = ingest_files(files)

    assert index[0]["date"] == "2026-09-01"
    assert index[1]["date"] is None


def test_non_txt_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = tmp / "file.pdf"
        p.write_bytes(b"PDF content")
        with pytest.raises(ValueError, match="Only .txt"):
            ingest_files([{"filename": "file.pdf", "path": str(p)}])


def test_size_cap_rejected(monkeypatch):
    monkeypatch.setattr("app.settings.MAX_FILE_KB", 1)
    big_content = "x" * 2000  # 2 KB
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [_make_file(tmp, "big.txt", big_content)]
        with pytest.raises(ValueError, match="exceeds"):
            ingest_files(files)


def test_bom_stripped():
    content_bytes = b"\xef\xbb\xbf" + VALID_TRANSCRIPT.encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = tmp / "bom.txt"
        p.write_bytes(content_bytes)
        index, prompt, parsed = ingest_files([{"filename": "bom.txt", "path": str(p)}])

    assert index[0]["meeting"] == "Test Meeting"


def test_transcript_wrapped_in_tags():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [_make_file(tmp, "t1.txt", VALID_TRANSCRIPT)]
        index, prompt, parsed = ingest_files(files)

    assert '<transcript doc_id="D1"' in prompt
    assert "</transcript>" in prompt
