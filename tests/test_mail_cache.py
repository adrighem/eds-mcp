"""Tests for Evolution mail cache lookup, MIME parsing, and quote stripping."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from eds_mcp import ValidationError
from eds_mcp.mail_cache import (
    MAX_ATTACHMENT_COUNT,
    clean_html,
    decode_mime_header,
    extract_email_addresses,
    extract_reply_headers,
    extract_text_from_message,
    get_cached_message_path,
    list_attachments_from_message,
    normalize_attachment_paths,
    normalize_recipients,
    normalize_subject,
    parse_message_envelope,
    read_cached_message,
    save_attachment_from_message,
    strip_quoted_text,
)
from eds_mcp.mail_db import resolve_folder_name, validate_safe_identifier


@pytest.fixture
def mock_evo_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect Evolution mail cache roots to tmp_path."""
    cache_root = tmp_path / "cache" / "evolution" / "mail"
    local_root = tmp_path / "local" / "evolution" / "mail"
    cache_root.mkdir(parents=True, exist_ok=True)
    local_root.mkdir(parents=True, exist_ok=True)

    def _fake_expanduser(path: str) -> str:
        if path.startswith("~/.cache/evolution/mail"):
            return path.replace("~/.cache/evolution/mail", str(cache_root))
        if path.startswith("~/.local/share/evolution/mail"):
            return path.replace("~/.local/share/evolution/mail", str(local_root))
        return os.path.abspath(path)

    monkeypatch.setattr(os.path, "expanduser", _fake_expanduser)
    return cache_root


def test_ews_sha256_uid_lookup(mock_evo_roots: Path) -> None:
    """EWS 160+ char base64 UID with /, +, = resolved via SHA-256 in cur/ and new/."""
    account_uid = "ews_account"
    ews_uid = "AAMkAGUy" + "a" * 150 + "/+="
    uid_hash = hashlib.sha256(ews_uid.encode("utf-8")).hexdigest()
    bucket = uid_hash[:2]

    folder_dir = mock_evo_roots / account_uid / "folders" / "Inbox"
    cur_bucket_dir = folder_dir / "cur" / bucket
    cur_bucket_dir.mkdir(parents=True, exist_ok=True)
    cur_file = cur_bucket_dir / uid_hash
    cur_file.write_text("From: alice@test.com\n\nCur payload", encoding="utf-8")

    resolved_cur = get_cached_message_path(account_uid, ews_uid, "Inbox")
    assert resolved_cur == str(cur_file)
    assert (
        read_cached_message(account_uid, ews_uid, "Inbox") == "From: alice@test.com\n\nCur payload"
    )

    cur_file.unlink()
    new_bucket_dir = folder_dir / "new" / bucket
    new_bucket_dir.mkdir(parents=True, exist_ok=True)
    new_file = new_bucket_dir / uid_hash
    new_file.write_text("From: bob@test.com\n\nNew payload", encoding="utf-8")

    resolved_new = get_cached_message_path(account_uid, ews_uid, "Inbox")
    assert resolved_new == str(new_file)
    assert read_cached_message(account_uid, ews_uid, "Inbox") == "From: bob@test.com\n\nNew payload"


def test_numeric_imap_uid_lookup(mock_evo_roots: Path) -> None:
    """Standard numeric IMAP UID lookup in cur/{uid} and cur/{sub}/{uid}."""
    account_uid = "imap_account"
    folder_dir = mock_evo_roots / account_uid / "folders" / "Inbox"

    cur_direct = folder_dir / "cur" / "12345"
    cur_direct.parent.mkdir(parents=True, exist_ok=True)
    cur_direct.write_text("Direct IMAP", encoding="utf-8")
    assert get_cached_message_path(account_uid, "12345", "Inbox") == str(cur_direct)

    cur_sub = folder_dir / "cur" / "sub" / "12346"
    cur_sub.parent.mkdir(parents=True, exist_ok=True)
    cur_sub.write_text("Subdir IMAP", encoding="utf-8")
    assert get_cached_message_path(account_uid, "12346", "Inbox") == str(cur_sub)


def test_nested_folder_and_case_insensitive_resolution(mock_evo_roots: Path) -> None:
    """Nested Inbox/subfolders/Projects lookup and case-insensitive resolution."""
    account_uid = "nested_account"
    acc_dir = mock_evo_roots / account_uid
    proj_dir = acc_dir / "folders" / "Inbox" / "subfolders" / "Projects"
    cur_dir = proj_dir / "cur"
    cur_dir.mkdir(parents=True, exist_ok=True)
    msg_file = cur_dir / "42"
    msg_file.write_text("Project note", encoding="utf-8")

    path = get_cached_message_path(account_uid, "42", "Inbox/Projects")
    assert path == str(msg_file)

    db_path = acc_dir / "folders.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE folders (folder_name TEXT)")
    cur.execute("INSERT INTO folders VALUES ('Inbox')")
    cur.execute("INSERT INTO folders VALUES ('Archive')")
    conn.commit()
    conn.close()

    assert resolve_folder_name(account_uid, "INBOX") == "Inbox"
    assert resolve_folder_name(account_uid, "archive") == "Archive"
    assert resolve_folder_name(account_uid, "inbox/projects") == "Inbox/Projects"


def test_path_traversal_and_nul_rejection() -> None:
    """Reject path traversal and NUL bytes with ValidationError."""
    with pytest.raises(ValidationError):
        validate_safe_identifier("..", "folder_name")
    with pytest.raises(ValidationError):
        validate_safe_identifier("Inbox/../Secret", "folder_name")
    with pytest.raises(ValidationError):
        validate_safe_identifier("Inbox\x00Bad", "folder_name")
    with pytest.raises(ValidationError):
        get_cached_message_path("acc", "uid", "../traversal")
    with pytest.raises(ValidationError):
        get_cached_message_path("acc", "uid", "folder\x00bad")
    with pytest.raises(ValidationError):
        get_cached_message_path("../acc", "uid", "Inbox")
    with pytest.raises(ValidationError):
        get_cached_message_path("acc/sub", "uid", "Inbox")
    assert get_cached_message_path("acc", "uid\x00bad", "Inbox") is None
    assert get_cached_message_path("acc", "", "Inbox") is None


def test_mime_decoding_and_subject_normalization() -> None:
    """RFC 2047 decoding, subject normalization, and header address extraction."""
    assert decode_mime_header("=?utf-8?b?VMOpc3Q=?=") == "Tést"
    assert decode_mime_header("=?utf-8?q?Hello=20World?=") == "Hello World"
    assert decode_mime_header("Plain text\n\tsecond line") == "Plain text second line"
    assert decode_mime_header(None) == ""

    assert normalize_subject("Re: Fwd: FW: AW: WG: VS: SV: antw: doorst: Project") == "Project"
    assert normalize_subject("Re[2]: Update") == "Update"
    assert normalize_subject(None) == ""

    addrs = extract_email_addresses(
        "Alice <Alice@Example.Com>, Bob <bob@example.com>",
        "CHARLIE@TEST.ORG",
        "invalid-address",
        None,
    )
    assert addrs == {"alice@example.com", "bob@example.com", "charlie@test.org"}

    raw = "Message-ID: <msg1@test>\nReferences: <root@test>\n\nBody"
    msg_id, refs = extract_reply_headers(raw)
    assert msg_id == "<msg1@test>"
    assert refs == "<root@test> <msg1@test>"

    assert normalize_recipients("a@b.com; c@d.com, e@f.com") == "a@b.com, c@d.com, e@f.com"
    assert normalize_recipients(["a@b.com", "c@d.com; e@f.com"]) == "a@b.com, c@d.com, e@f.com"
    assert normalize_recipients(None) == ""
    with pytest.raises(ValidationError):
        normalize_recipients(123)  # type: ignore[arg-type]


def test_normalize_attachment_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Validate attachment path bounds and reject non-regular or oversized files."""
    test_file = tmp_path / "doc.txt"
    test_file.write_bytes(b"hello world")
    normalized = normalize_attachment_paths([str(test_file)])
    assert len(normalized) == 1
    assert normalized[0] == str(test_file.resolve())

    with pytest.raises(ValidationError, match="At most 10 attachments"):
        normalize_attachment_paths([str(test_file)] * (MAX_ATTACHMENT_COUNT + 1))

    with pytest.raises(ValidationError, match="not a readable regular file"):
        normalize_attachment_paths([str(tmp_path / "nonexistent.txt")])

    real_stat = os.stat

    class FakeStat:
        st_size = 25 * 1024 * 1024
        st_mode = real_stat(test_file).st_mode

    monkeypatch.setattr(os, "stat", lambda _: FakeStat())
    with pytest.raises(ValidationError, match="exceed the 20 MiB"):
        normalize_attachment_paths([str(test_file)])


def test_strip_quoted_text_multilingual_and_inline() -> None:
    """Strip multilingual quoted text while preserving inline reply answers."""
    en_text = "My reply.\n\nOn Mon, Jan 1, 2026 at 10:00 AM Alice <alice@test.com> wrote:\n> Original text"
    assert strip_quoted_text(en_text) == "My reply."

    nl_text = "Mijn antwoord.\n\nOp ma 1 jan 2026 om 10:00 schreef Alice:\n> Oorspronkelijk bericht"
    assert strip_quoted_text(nl_text) == "Mijn antwoord."

    nl_header = (
        "Reactie.\n\nVan: Alice\nVerzonden: maandag 1 januari\nAan: Bob\nOnderwerp: Test\n\nOud"
    )
    assert strip_quoted_text(nl_header) == "Reactie."

    de_text = "Meine Antwort.\n\nAm Mo., 1. Jan. 2026 um 10:00 schrieb Alice:\n> Altes Zitat"
    assert strip_quoted_text(de_text) == "Meine Antwort."

    de_header = "Gelesen.\n\nVon: Alice\nGesendet: Montag, 1. Januar\nAn: Bob\nBetreff: Test\n\nAlt"
    assert strip_quoted_text(de_header) == "Gelesen."

    no_text = "Mitt svar.\n\nDen ma. 1. jan. 2026 skrev Alice:\n> Gammel melding"
    assert strip_quoted_text(no_text) == "Mitt svar."

    no_header = "Mottatt.\n\nFra: Alice\nSendt: mandag 1. januar\nTil: Bob\nEmne: Test\n\nGammel"
    assert strip_quoted_text(no_header) == "Mottatt."

    divider = "Direct reply.\n\n-----Original Message-----\nFrom: Alice\nTo: Bob\n\nHistory"
    assert strip_quoted_text(divider) == "Direct reply."

    inline = "> question\nInline answer\nOn Jan 1 wrote:\n> old"
    assert strip_quoted_text(inline) == "Inline answer"


def test_envelope_parsing_and_attachments() -> None:
    """Envelope parsing, plain/html conversion, and attachment saving with cleanup."""
    raw = (
        "From: Alice <alice@example.com>\r\n"
        "To: Bob <bob@example.com>\r\n"
        "Cc: Carol <carol@example.com>\r\n"
        "Subject: Project Update\r\n"
        "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
        "Message-ID: <msg-99@example.com>\r\n"
        'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
        "--BOUNDARY\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        "Hello Bob, status report attached.\r\n"
        "--BOUNDARY\r\n"
        'Content-Type: text/plain; name="report.txt"\r\n'
        'Content-Disposition: attachment; filename="report.txt"\r\n\r\n'
        "Report Data 2026\r\n"
        "--BOUNDARY--"
    )
    env = parse_message_envelope(raw)
    assert env["from"] == "Alice <alice@example.com>"
    assert env["to"] == "Bob <bob@example.com>"
    assert env["cc"] == "Carol <carol@example.com>"
    assert env["subject"] == "Project Update"
    assert env["message_id"] == "<msg-99@example.com>"
    assert "status report attached." in env["body"]
    assert env["truncated"] is False

    text_view = extract_text_from_message(raw)
    assert "From: Alice <alice@example.com>" in text_view
    assert "Hello Bob" in text_view

    assert clean_html("<p>Paragraph</p><script>bad()</script>") == "Paragraph"

    attachments = list_attachments_from_message(raw)
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "report.txt"

    saved_path = save_attachment_from_message(raw, "report.txt")
    assert saved_path is not None
    assert os.path.isfile(saved_path)
    try:
        with open(saved_path, "rb") as handle:
            assert handle.read() == b"Report Data 2026"
    finally:
        shutil.rmtree(os.path.dirname(saved_path), ignore_errors=True)


def test_save_attachment_cleans_temp_dir_on_write_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created_dirs: list[Path] = []

    def fake_mkdtemp(prefix: str = "") -> str:
        d = tmp_path / f"{prefix}err"
        d.mkdir()
        created_dirs.append(d)
        return str(d)

    def failing_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr("tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr("builtins.open", failing_open)
    raw = (
        'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        "--B\r\n"
        'Content-Type: text/plain; name="x.txt"\r\n'
        'Content-Disposition: attachment; filename="x.txt"\r\n\r\n'
        "payload\r\n--B--"
    )
    with pytest.raises(OSError, match="disk full"):
        save_attachment_from_message(raw, "x.txt")
    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()
