"""Tests for cross-folder email thread reconstruction and deduplication."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from eds_mcp.mail import get_email_thread_logic


@pytest.fixture(autouse=True)
def _isolate_mail_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "eds_mcp.mail_db.get_mail_roots",
        lambda uid: [str(tmp_path / "evo_mail" / uid)],
    )


@pytest.fixture
def thread_db(tmp_path: Path) -> Path:
    """Create isolated SQLite folders.db with Camel schema and test folders."""
    db_path = tmp_path / "folders.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE folders (folder_name TEXT, unread_count INTEGER, visible_count INTEGER)"
    )

    columns = (
        "uid TEXT, subject TEXT, mail_from TEXT, mail_to TEXT, mail_cc TEXT, "
        "dreceived INTEGER, dsent INTEGER, flags INTEGER, preview TEXT"
    )
    for folder in ("Inbox", "Archive", "Verzonden items", "Deleted Items"):
        cur.execute(f'CREATE TABLE "{folder}" ({columns})')
        cur.execute(
            "INSERT INTO folders (folder_name, unread_count, visible_count) VALUES (?, 0, 0)",
            (folder,),
        )
    conn.commit()
    conn.close()
    return db_path


def _populate_test_thread(db_path: Path) -> dict[tuple[str, str], str]:
    """Populate test rows in SQLite and return raw RFC822 message cache dict."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        'INSERT INTO "Inbox" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-1",
            "Re: Project Alpha",
            "alice@example.com",
            "bob@example.com",
            "",
            1700000100,
            1700000100,
            1,
            "Initial proposal",
        ),
    )
    cur.execute(
        'INSERT INTO "Verzonden items" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-2-sent",
            "AW: Project Alpha",
            "bob@example.com",
            "alice@example.com",
            "",
            1700000200,
            1700000200,
            1,
            "Sent reply",
        ),
    )
    cur.execute(
        'INSERT INTO "Archive" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-2-arc",
            "AW: Project Alpha",
            "bob@example.com",
            "alice@example.com",
            "",
            1700000200,
            1700000200,
            1,
            "Archived reply copy",
        ),
    )
    cur.execute(
        'INSERT INTO "Inbox" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-3",
            "SV: Project Alpha",
            "alice@example.com",
            "bob@example.com",
            "",
            1700000300,
            1700000300,
            1,
            "Follow-up",
        ),
    )
    cur.execute(
        'INSERT INTO "Deleted Items" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-del",
            "Re: Project Alpha",
            "spam@example.com",
            "bob@example.com",
            "",
            1700000400,
            1700000400,
            1,
            "Deleted spam message",
        ),
    )
    cur.execute(
        'INSERT INTO "Archive" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            "msg-uncached",
            "VS: Project Alpha",
            "alice@example.com",
            "bob@example.com",
            "",
            1700000500,
            1700000500,
            1,
            "Preview from sqlite index without raw cache",
        ),
    )
    conn.commit()
    conn.close()

    return {
        ("Inbox", "msg-1"): (
            "From: Alice <alice@example.com>\r\n"
            "To: Bob <bob@example.com>\r\n"
            "Subject: Re: Project Alpha\r\n"
            "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
            "Message-ID: <msg-1@example.com>\r\n\r\n"
            "Initial proposal body."
        ),
        ("Verzonden items", "msg-2-sent"): (
            "From: Bob <bob@example.com>\r\n"
            "To: Alice <alice@example.com>\r\n"
            "Subject: AW: Project Alpha\r\n"
            "Date: Mon, 1 Jan 2026 10:05:00 +0000\r\n"
            "Message-ID: <msg-2@example.com>\r\n"
            "In-Reply-To: <msg-1@example.com>\r\n"
            "References: <msg-1@example.com>\r\n\r\n"
            "Bob reply text.\n\nOn Mon, Jan 1, 2026 Alice wrote:\n> Initial proposal body."
        ),
        ("Archive", "msg-2-arc"): (
            "From: Bob <bob@example.com>\r\n"
            "To: Alice <alice@example.com>\r\n"
            "Subject: AW: Project Alpha\r\n"
            "Date: Mon, 1 Jan 2026 10:05:00 +0000\r\n"
            "Message-ID: <msg-2@example.com>\r\n"
            "In-Reply-To: <msg-1@example.com>\r\n"
            "References: <msg-1@example.com>\r\n\r\n"
            "Bob reply text.\n\nOn Mon, Jan 1, 2026 Alice wrote:\n> Initial proposal body."
        ),
        ("Inbox", "msg-3"): (
            "From: Alice <alice@example.com>\r\n"
            "To: Bob <bob@example.com>\r\n"
            "Subject: SV: Project Alpha\r\n"
            "Date: Mon, 1 Jan 2026 10:10:00 +0000\r\n"
            "Message-ID: <msg-3@example.com>\r\n"
            "In-Reply-To: <msg-2@example.com>\r\n"
            "References: <msg-1@example.com> <msg-2@example.com>\r\n\r\n"
            "Alice second response."
        ),
        ("Deleted Items", "msg-del"): (
            "From: Spam <spam@example.com>\r\n"
            "To: Bob <bob@example.com>\r\n"
            "Subject: Re: Project Alpha\r\n"
            "Date: Mon, 1 Jan 2026 10:15:00 +0000\r\n"
            "Message-ID: <msg-del@example.com>\r\n"
            "In-Reply-To: <msg-1@example.com>\r\n\r\n"
            "Should be excluded."
        ),
    }


@pytest.mark.asyncio
async def test_cross_folder_thread_reconstruction(thread_db: Path) -> None:
    """Reconstruct thread across Inbox, Verzonden items, Archive, deduplicating IDs."""
    cache = _populate_test_thread(thread_db)

    def _cache_reader(_acc: str, uid: str, folder: str) -> str | None:
        return cache.get((folder, uid))

    res_raw = await get_email_thread_logic(
        "acc1",
        message_uid="msg-1",
        folder_name="Inbox",
        db_path_getter=lambda _acc: str(thread_db),
        cache_reader=_cache_reader,
    )
    data: dict[str, Any] = json.loads(res_raw)
    assert data["subject"] == "Project Alpha"
    items = data["items"]

    # Verify msg-del from Deleted Items is not included
    uids = [item["uid"] for item in items]
    assert "msg-del" not in uids

    # Verify duplicate <msg-2@example.com> across Archive and Verzonden items is collapsed
    msg2_items = [it for it in items if it.get("message_id") == "<msg-2@example.com>"]
    assert len(msg2_items) == 1
    m2 = msg2_items[0]
    expected_other = "Archive" if m2["folder"] == "Verzonden items" else "Verzonden items"
    assert expected_other in m2["also_in"]

    # Verify uncached candidate falls back to index_preview
    uncached = next(it for it in items if it["uid"] == "msg-uncached")
    assert uncached["source"] == "index_preview"
    assert uncached["body"] == "Preview from sqlite index without raw cache"


@pytest.mark.asyncio
async def test_strip_quoted_behavior(thread_db: Path) -> None:
    """Verify strip_quoted=True strips reply history vs strip_quoted=False preserves it."""
    cache = _populate_test_thread(thread_db)

    def _cache_reader(_acc: str, uid: str, folder: str) -> str | None:
        return cache.get((folder, uid))

    stripped_raw = await get_email_thread_logic(
        "acc1",
        message_uid="msg-1",
        folder_name="Inbox",
        strip_quoted=True,
        db_path_getter=lambda _acc: str(thread_db),
        cache_reader=_cache_reader,
    )
    stripped_data: dict[str, Any] = json.loads(stripped_raw)
    m2_stripped = next(
        it for it in stripped_data["items"] if it.get("message_id") == "<msg-2@example.com>"
    )
    assert "Initial proposal body." not in m2_stripped["body"]
    assert "Bob reply text." in m2_stripped["body"]

    full_raw = await get_email_thread_logic(
        "acc1",
        message_uid="msg-1",
        folder_name="Inbox",
        strip_quoted=False,
        db_path_getter=lambda _acc: str(thread_db),
        cache_reader=_cache_reader,
    )
    full_data: dict[str, Any] = json.loads(full_raw)
    m2_full = next(it for it in full_data["items"] if it.get("message_id") == "<msg-2@example.com>")
    assert "> Initial proposal body." in m2_full["body"]


@pytest.mark.asyncio
async def test_thread_pagination(thread_db: Path) -> None:
    """Verify thread pagination bounds and metadata."""
    cache = _populate_test_thread(thread_db)

    def _cache_reader(_acc: str, uid: str, folder: str) -> str | None:
        return cache.get((folder, uid))

    page1_raw = await get_email_thread_logic(
        "acc1",
        message_uid="msg-1",
        folder_name="Inbox",
        max_messages=2,
        offset=0,
        db_path_getter=lambda _acc: str(thread_db),
        cache_reader=_cache_reader,
    )
    page1: dict[str, Any] = json.loads(page1_raw)
    assert len(page1["items"]) == 2
    assert page1["meta"]["total"] == 4
    assert page1["meta"]["has_more"] is True
    assert page1["meta"]["offset"] == 0

    page2_raw = await get_email_thread_logic(
        "acc1",
        message_uid="msg-1",
        folder_name="Inbox",
        max_messages=2,
        offset=2,
        db_path_getter=lambda _acc: str(thread_db),
        cache_reader=_cache_reader,
    )
    page2: dict[str, Any] = json.loads(page2_raw)
    assert len(page2["items"]) == 2
    assert page2["meta"]["total"] == 4
    assert page2["meta"]["offset"] == 2


@pytest.mark.asyncio
async def test_missing_database_error() -> None:
    """Verify missing database returns structured NOT_FOUND error envelope."""
    res_raw = await get_email_thread_logic(
        "nonexistent_acc",
        message_uid="msg-1",
        folder_name="Inbox",
        db_path_getter=lambda _acc: None,
    )
    data: dict[str, Any] = json.loads(res_raw)
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
