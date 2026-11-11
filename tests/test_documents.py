"""Unit tests for document parsing and context truncation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eds_mcp import documents


def test_supported_document_formats_are_sorted_and_complete():
    assert documents.supported_document_formats() == (".csv, .docx, .json, .md, .pdf, .txt, .xlsx")


def test_truncate_for_context_keeps_short_content():
    assert documents.truncate_for_context("short", max_chars=10) == "short"


def test_truncate_for_context_marks_long_content():
    result = documents.truncate_for_context("abcdef", max_chars=3)
    assert result == "abc\n\n[... content truncated due to length ...]"


def test_parse_text_reads_utf8_with_replacement(tmp_path):
    path = tmp_path / "message.txt"
    path.write_bytes("hello \xff world".encode("latin-1"))
    assert documents.parse_text(str(path)) == "hello \ufffd world"


@pytest.mark.asyncio
async def test_parse_document_rejects_missing_file(tmp_path):
    result = await documents.parse_document_logic(str(tmp_path / "missing.txt"))
    res = json.loads(result)
    assert "error" in res
    assert res["error"]["code"] == "NOT_FOUND"
    assert "File not found" in res["error"]["message"]


@pytest.mark.asyncio
async def test_parse_document_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "archive.zip"
    path.write_text("not a document")

    result = await documents.parse_document_logic(str(path))
    res = json.loads(result)
    assert "error" in res
    assert res["error"]["code"] == "VALIDATION_ERROR"
    assert "Unsupported document format '.zip'" in res["error"]["message"]
    assert documents.supported_document_formats() in res["error"]["message"]


@pytest.mark.asyncio
async def test_parse_document_rejects_oversized_file(tmp_path, monkeypatch):
    path = tmp_path / "large.txt"
    path.write_text("dummy")

    # Mock file size > MAX_FILE_SIZE_MB
    monkeypatch.setattr(documents, "MAX_FILE_SIZE_MB", 0.000001)
    result = await documents.parse_document_logic(str(path))
    res = json.loads(result)
    assert "error" in res
    assert res["error"]["code"] == "VALIDATION_ERROR"
    assert "too large" in res["error"]["message"]


@pytest.mark.asyncio
async def test_parse_document_uses_registered_parser(tmp_path, monkeypatch):
    path = tmp_path / "sample.custom"
    path.write_text("content")

    monkeypatch.setitem(
        documents.DOCUMENT_PARSERS,
        ".custom",
        lambda file_path: f"parsed {Path(file_path).name}",
    )

    result = await documents.parse_document_logic(str(path))
    res = json.loads(result)
    assert res["file"] == "sample.custom"
    assert res["content"] == "parsed sample.custom"
    assert res["truncated"] is False
    assert res["chars"] == len("parsed sample.custom")


@pytest.mark.asyncio
async def test_parse_document_truncates_parser_output(tmp_path, monkeypatch):
    path = tmp_path / "sample.custom"
    path.write_text("content")

    monkeypatch.setattr(documents, "MAX_CONTENT_CHARS", 4)
    monkeypatch.setitem(documents.DOCUMENT_PARSERS, ".custom", lambda _: "abcdef")

    result = await documents.parse_document_logic(str(path))
    res = json.loads(result)
    assert res["file"] == "sample.custom"
    assert res["chars"] == 6
    assert res["truncated"] is True
    assert res["content"] == "abcd\n\n[... content truncated due to length ...]"


@pytest.mark.asyncio
async def test_parse_document_handles_parser_error(tmp_path, monkeypatch):
    path = tmp_path / "sample.custom"
    path.write_text("content")

    monkeypatch.setitem(
        documents.DOCUMENT_PARSERS, ".custom", lambda _: "Error: corrupted file header"
    )
    result = await documents.parse_document_logic(str(path))
    res = json.loads(result)
    assert "error" in res
    assert res["error"]["code"] == "PARSE_ERROR"
    assert "corrupted file header" in res["error"]["message"]
