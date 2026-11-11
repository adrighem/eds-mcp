from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from eds_mcp import BridgeUnavailableError
from eds_mcp.mail import (
    BRIDGE_CALL_TIMEOUT_MS,
    BRIDGE_READ_FALLBACK_ENV,
    call_bridge_method,
    get_email_body_logic,
    list_attachments_logic,
    save_attachment_logic,
    search_emails_logic,
)
from eds_mcp.mail_bridge import (
    bridge_read_fallback_enabled,
    is_bridge_reachable,
)


@pytest.fixture(autouse=True)
def _isolate_mail_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(
        "eds_mcp.mail_db.get_mail_roots",
        lambda uid: [str(tmp_path / "evo_mail" / uid)],
    )


SAMPLE_RFC822_ATTACHMENT = """From: me@example.com
Subject: Attachment
Content-Type: multipart/mixed; boundary="boundary"

--boundary
Content-Type: text/plain

hello
--boundary
Content-Type: text/plain
Content-Disposition: attachment; filename="notes.txt"

attachment content
--boundary--
"""


def _create_mock_proxy(name_owner: str | None = ":1.42") -> MagicMock:
    proxy = MagicMock()
    proxy.get_name_owner.return_value = name_owner
    return proxy


def test_bridge_fallback_auto_enabled_when_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    proxy = _create_mock_proxy(":1.100")
    assert is_bridge_reachable(proxy_getter=lambda: proxy) is True
    assert bridge_read_fallback_enabled(proxy_getter=lambda: proxy) is True


def test_bridge_fallback_disabled_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    proxy = _create_mock_proxy(None)
    assert is_bridge_reachable(proxy_getter=lambda: proxy) is False
    assert bridge_read_fallback_enabled(proxy_getter=lambda: proxy) is False


def test_bridge_fallback_disabled_when_proxy_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)

    def _failing_getter() -> Any:
        raise BridgeUnavailableError("D-Bus down")

    assert is_bridge_reachable(proxy_getter=_failing_getter) is False
    assert bridge_read_fallback_enabled(proxy_getter=_failing_getter) is False


def test_bridge_fallback_explicit_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BRIDGE_READ_FALLBACK_ENV, "0")
    proxy = _create_mock_proxy(":1.100")
    assert is_bridge_reachable(proxy_getter=lambda: proxy) is True
    assert bridge_read_fallback_enabled(proxy_getter=lambda: proxy) is False


def test_bridge_fallback_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BRIDGE_READ_FALLBACK_ENV, "1")
    proxy = _create_mock_proxy(None)
    assert bridge_read_fallback_enabled(proxy_getter=lambda: proxy) is True


@pytest.mark.asyncio
async def test_get_email_body_cache_miss_without_fallback(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    mocker.patch("eds_mcp.mail.bridge_read_fallback_enabled", return_value=False)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    raw_result = await get_email_body_logic("test_account", "test_msg", "Inbox")
    payload = json.loads(raw_result)

    assert payload["error"]["code"] == "CACHE_MISS"
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_email_body_dbus_fallback_when_enabled(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BRIDGE_READ_FALLBACK_ENV, "1")
    raw_msg = "From: me@example.com\nSubject: Test\n\ndbus fetched content"
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    mocker.patch("eds_mcp.mail.bridge_read_fallback_enabled", return_value=True)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method", return_value=(True, raw_msg))

    raw_result = await get_email_body_logic("test_account", "test_msg", "Inbox")
    payload = json.loads(raw_result)

    assert payload["source"] == "bridge"
    assert payload["from"] == "me@example.com"
    assert payload["body"] == "dbus fetched content"
    assert payload["truncated"] is False
    bridge_call.assert_called_once_with(
        "GetMessage", "(sss)", ("test_account", "test_msg", "Inbox")
    )


@pytest.mark.asyncio
async def test_get_email_body_dbus_fallback_truncation(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BRIDGE_READ_FALLBACK_ENV, "1")
    long_body = "x" * 200
    raw_msg = f"From: me@example.com\nSubject: Test\n\n{long_body}"
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    mocker.patch("eds_mcp.mail.bridge_read_fallback_enabled", return_value=True)
    mocker.patch("eds_mcp.mail.call_bridge_method", return_value=(True, raw_msg))

    raw_result = await get_email_body_logic("test_account", "test_msg", "Inbox", max_chars=100)
    payload = json.loads(raw_result)

    assert payload["source"] == "bridge"
    assert payload["truncated"] is True
    assert len(payload["body"]) <= 100


@pytest.mark.asyncio
async def test_list_attachments_cache_and_bridge(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Source: cache
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=SAMPLE_RFC822_ATTACHMENT)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    cache_res = json.loads(await list_attachments_logic("acc1", "msg1", "Inbox"))
    assert cache_res["meta"]["source"] == "cache"
    assert cache_res["items"][0]["filename"] == "notes.txt"
    bridge_call.assert_not_called()

    # 2. Source: bridge
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    mocker.patch("eds_mcp.mail.bridge_read_fallback_enabled", return_value=True)
    bridge_payload = json.dumps([{"filename": "remote.pdf", "mime_type": "application/pdf"}])
    bridge_call.return_value = (True, bridge_payload)

    bridge_res = json.loads(await list_attachments_logic("acc1", "msg2", "Inbox"))
    assert bridge_res["meta"]["source"] == "bridge"
    assert bridge_res["items"][0]["filename"] == "remote.pdf"
    bridge_call.assert_called_once_with("ListAttachments", "(sss)", ("acc1", "msg2", "Inbox"))


@pytest.mark.asyncio
async def test_save_attachment_cache_and_bridge(
    mocker: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # 1. Source: cache
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=SAMPLE_RFC822_ATTACHMENT)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    # save_attachment_logic(account_uid, message_uid, folder_name, attachment_name)
    cache_res = json.loads(await save_attachment_logic("acc1", "msg1", "Inbox", "notes.txt"))
    assert cache_res["source"] == "cache"
    assert cache_res["filename"] == "notes.txt"
    with open(cache_res["path"], "rb") as f:
        assert f.read() == b"attachment content"
    bridge_call.assert_not_called()

    # 2. Source: bridge
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    mocker.patch("eds_mcp.mail.bridge_read_fallback_enabled", return_value=True)
    bridge_call.return_value = (True, "Saved successfully")

    bridge_res = json.loads(await save_attachment_logic("acc1", "msg2", "Inbox", "report.pdf"))
    assert bridge_res["source"] == "bridge"
    assert bridge_res["filename"] == "report.pdf"
    assert "report.pdf" in bridge_res["path"]
    bridge_call.assert_called_once()
    call_args = bridge_call.call_args[0]
    assert call_args[0] == "SaveAttachment"
    assert call_args[2][:4] == ("acc1", "msg2", "Inbox", "report.pdf")


@pytest.fixture
def fake_mail_db(tmp_path: Any) -> str:
    db_file = tmp_path / "folders.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE folders (folder_name TEXT PRIMARY KEY, unread_count INTEGER, visible_count INTEGER)"
    )
    cur.execute("INSERT INTO folders VALUES ('Inbox', 2, 5)")
    cur.execute(
        """CREATE TABLE "Inbox" (
            uid TEXT PRIMARY KEY,
            subject TEXT,
            mail_from TEXT,
            mail_to TEXT,
            mail_cc TEXT,
            dsent INTEGER,
            dreceived INTEGER,
            preview TEXT,
            read INTEGER,
            attachment INTEGER,
            deleted INTEGER
        )"""
    )
    emails = [
        (
            "u1",
            "Sveiki Ádám",
            "Kárpáti János <karpati@example.com>",
            "Akvilė Narkevičiūtė <akvile@example.com>",
            "cc@example.com",
            1700000000,
            1700000000,
            "Gera diena Ádám",
            0,
            0,
            0,
        ),
        (
            "u2",
            "Re: Project Roadmap",
            "boss@example.com",
            "team@example.com",
            None,
            1700100000,
            1700100000,
            "Updated timeline",
            1,
            0,
            0,
        ),
        (
            "u3",
            "Project Roadmap",
            "boss@example.com",
            "team@example.com",
            None,
            1700050000,
            1700050000,
            "Initial timeline",
            1,
            0,
            0,
        ),
        (
            "u4",
            "Secret discussion",
            "alice@example.com",
            "bob@example.com",
            None,
            1700200000,
            1700200000,
            "Nothing here",
            0,
            0,
            0,
        ),
    ]
    cur.executemany('INSERT INTO "Inbox" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', emails)
    conn.commit()
    conn.close()
    return str(db_file)


@pytest.mark.asyncio
async def test_search_emails_unicode_case_insensitive(mocker: Any, fake_mail_db: str) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=fake_mail_db)

    # Search for "ádám" -> matches "Ádám" in subject and preview of u1
    res1 = json.loads(await search_emails_logic("acc1", query="ádám"))
    assert len(res1["items"]) == 1
    assert res1["items"][0]["uid"] == "u1"

    # Search for "kárpáti" -> matches "Kárpáti" in mail_from of u1
    res2 = json.loads(await search_emails_logic("acc1", query="kárpáti"))
    assert len(res2["items"]) == 1
    assert res2["items"][0]["uid"] == "u1"

    # Search for "akvilė" -> matches "Akvilė" in mail_to of u1
    res3 = json.loads(await search_emails_logic("acc1", query="akvilė"))
    assert len(res3["items"]) == 1
    assert res3["items"][0]["uid"] == "u1"


@pytest.mark.asyncio
async def test_search_emails_optional_filters(mocker: Any, fake_mail_db: str) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=fake_mail_db)

    # from_query & to_query
    from_res = json.loads(await search_emails_logic("acc1", from_query="karpati"))
    assert len(from_res["items"]) == 1
    assert from_res["items"][0]["uid"] == "u1"

    to_res = json.loads(await search_emails_logic("acc1", to_query="akvile"))
    assert len(to_res["items"]) == 1
    assert to_res["items"][0]["uid"] == "u1"

    # date filters since / until (1700000000 is 2023-11-14)
    date_res = json.loads(
        await search_emails_logic(
            "acc1",
            from_query="boss",
            since="2023-11-14",
            until="2023-11-16",
        )
    )
    assert len(date_res["items"]) == 2

    # unread_only=True
    unread_res = json.loads(await search_emails_logic("acc1", unread_only=True))
    assert {item["uid"] for item in unread_res["items"]} == {"u1", "u4"}

    # dedupe_threads=True collapses "Re: Project Roadmap" and "Project Roadmap"
    dedup_res = json.loads(await search_emails_logic("acc1", query="Roadmap", dedupe_threads=True))
    assert len(dedup_res["items"]) == 1
    assert dedup_res["items"][0]["thread_count"] == 2

    # search_body=True with bounded max_scanned and cache misses
    # u4 has subject "Secret discussion" without needle in headers
    def fake_cache_reader(acc: str, uid: str, f: str) -> str | None:
        if uid == "u4":
            return "From: alice@example.com\n\nDeep confidential secret text."
        return None  # cache miss for others

    mocker.patch("eds_mcp.mail.read_cached_message", side_effect=fake_cache_reader)
    body_res = json.loads(
        await search_emails_logic(
            "acc1",
            query="confidential",
            search_body=True,
            max_scanned=5,
        )
    )
    assert len(body_res["items"]) == 1
    assert body_res["items"][0]["uid"] == "u4"
    assert body_res["meta"]["scanned_count"] > 0
    assert body_res["meta"]["cache_misses"] > 0


def test_call_bridge_method_uses_timeout(mocker: Any) -> None:
    proxy = mocker.patch("eds_mcp.mail_bridge.get_dbus_proxy").return_value
    result = mocker.MagicMock()
    result.unpack.return_value = (True, "ok")
    proxy.call_sync.return_value = result

    assert call_bridge_method("MoveMessage", "(ssss)", ("a", "b", "c", "d")) == (True, "ok")

    args = proxy.call_sync.call_args[0]
    assert args[3] == BRIDGE_CALL_TIMEOUT_MS
