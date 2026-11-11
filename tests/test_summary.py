"""Unit tests for daily summary, memos, and shared calendar orchestration."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

import pytest

from eds_mcp import calendar
from eds_mcp.mail import get_emails_logic
from eds_mcp.summary import (
    format_daily_summary,
    get_daily_summary_logic,
    resolve_primary_mail_account_uid,
)


def test_format_daily_summary_uses_stable_markdown_sections():
    result = format_daily_summary(
        "Calendar body",
        "Task body",
        "Mail body",
        now=datetime(2026, 6, 17, 9, 30),
    )

    assert result == "\n".join(
        [
            "# Daily Summary",
            "Date: Wednesday, 17 June 2026",
            "",
            "## \N{CALENDAR} Calendar",
            "Calendar body",
            "",
            "## \N{WHITE HEAVY CHECK MARK} Tasks",
            "Task body",
            "",
            "Mail body",
        ]
    )


@pytest.mark.asyncio
async def test_resolve_primary_mail_account_uid_selects_first_account_from_list():
    async def list_mail_accounts():
        return json.dumps(
            [
                {"uid": "primary", "name": "Primary"},
                {"uid": "secondary", "name": "Secondary"},
            ]
        )

    assert await resolve_primary_mail_account_uid(list_mail_accounts) == "primary"


@pytest.mark.asyncio
async def test_resolve_primary_mail_account_uid_selects_first_account_from_envelope():
    async def list_mail_accounts():
        return json.dumps(
            {
                "items": [
                    {"uid": "primary-env", "name": "Primary Env"},
                    {"uid": "secondary-env", "name": "Secondary Env"},
                ],
                "meta": {"returned": 2, "total": 2, "offset": 0, "has_more": False},
            }
        )

    assert await resolve_primary_mail_account_uid(list_mail_accounts) == "primary-env"


@pytest.mark.asyncio
async def test_resolve_primary_mail_account_uid_handles_invalid_resource_payload():
    async def list_mail_accounts():
        return "Error: account registry unavailable"

    assert await resolve_primary_mail_account_uid(list_mail_accounts) is None


@pytest.mark.asyncio
async def test_get_daily_summary_uses_provided_account_uid():
    calls: list[tuple[Any, ...]] = []

    async def get_calendar_events(**kwargs):
        calls.append(("calendar", kwargs))
        return "Today calendar"

    async def get_tasks(**kwargs):
        calls.append(("tasks", kwargs))
        return "Today tasks"

    async def list_mail_accounts():
        raise AssertionError("account lookup should be skipped")

    async def get_emails(account_uid, **kwargs):
        calls.append(("mail", account_uid, kwargs))
        return "Inbox summary"

    result = await get_daily_summary_logic(
        get_calendar_events,
        get_tasks,
        list_mail_accounts,
        get_emails,
        account_uid="explicit-account",
        now=datetime(2026, 6, 17),
    )

    assert "Today calendar" in result
    assert "Today tasks" in result
    assert "Inbox summary" in result
    assert calls == [
        ("calendar", {"date": "today", "summary_only": True}),
        ("tasks", {"date": "today", "summary_only": True}),
        ("mail", "explicit-account", {"limit": 10, "format": "summary"}),
    ]


@pytest.mark.asyncio
async def test_get_daily_summary_falls_back_when_no_mail_account_exists():
    async def get_calendar_events(**kwargs):
        return "Today calendar"

    async def get_tasks(**kwargs):
        return "Today tasks"

    async def list_mail_accounts():
        return "[]"

    async def get_emails(account_uid, **kwargs):
        raise AssertionError("mail lookup should be skipped")

    result = await get_daily_summary_logic(
        get_calendar_events,
        get_tasks,
        list_mail_accounts,
        get_emails,
        now=datetime(2026, 6, 17),
    )

    assert "_No mail account identified for summary._" in result


@pytest.mark.asyncio
async def test_get_memos_forwards_summary_only(mocker):
    get_items = mocker.patch.object(calendar, "get_items_logic", return_value="[]")

    result = await calendar.get_memos_logic(
        query="planning",
        memo_list_uid="memo-list",
        summary_only=True,
    )

    assert result == "[]"
    get_items.assert_awaited_once_with(
        calendar.ECal.ClientSourceType.MEMOS,
        days_ahead=365,
        days_back=365,
        query="planning",
        uid="memo-list",
        summary_only=True,
        limit=50,
        offset=0,
    )


@pytest.mark.asyncio
async def test_shared_calendar_resolves_contact_email_and_calendar_uid(mocker):
    mocker.patch(
        "eds_mcp.contacts.search_contacts_logic",
        return_value=json.dumps(
            {
                "items": [{"name": "Ada", "emails": ["ada@example.com"]}],
                "meta": {"returned": 1, "total": 1, "offset": 0, "has_more": False},
            }
        ),
    )
    mocker.patch.object(
        calendar.asyncio,
        "to_thread",
        return_value=("calendar-uid", None),
    )
    get_free_busy = mocker.patch.object(
        calendar,
        "get_free_busy_logic",
        return_value=[{"type": "Busy"}],
    )

    result = json.loads(
        await calendar.get_shared_calendar_events_logic(
            "Ada",
            days_ahead=14,
            days_back=2,
        )
    )

    assert result["email"] == "ada@example.com"
    assert result["items"] == [{"type": "Busy"}]
    assert result["meta"]["total"] == 1
    assert result["meta"]["returned"] == 1
    assert result["meta"]["offset"] == 0
    assert result["meta"]["has_more"] is False
    get_free_busy.assert_awaited_once_with(
        "ada@example.com",
        14,
        2,
        "calendar-uid",
    )


@pytest.mark.asyncio
async def test_shared_calendar_resolves_legacy_contact_book_format(mocker):
    mocker.patch(
        "eds_mcp.contacts.search_contacts_logic",
        return_value=json.dumps(
            {
                "Personal": [{"name": "Ada", "emails": ["ada@example.com"]}],
            }
        ),
    )
    mocker.patch.object(
        calendar.asyncio,
        "to_thread",
        return_value=("calendar-uid", None),
    )
    mocker.patch.object(
        calendar,
        "get_free_busy_logic",
        return_value=[],
    )

    result = json.loads(
        await calendar.get_shared_calendar_events_logic(
            "Ada",
            days_ahead=7,
            days_back=0,
        )
    )

    assert result["email"] == "ada@example.com"
    assert result["items"] == []
    assert result["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_mail_summary_formatting(mocker, tmp_path):
    db_file = tmp_path / "folders.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE folders (folder_name TEXT, unread_count INTEGER, visible_count INTEGER)"
    )
    conn.execute("INSERT INTO folders VALUES ('Inbox', 1, 2)")
    conn.execute(
        'CREATE TABLE "Inbox" ('
        "uid TEXT, subject TEXT, mail_from TEXT, mail_to TEXT, mail_cc TEXT, "
        "dreceived INTEGER, flags INTEGER, preview TEXT, attachment INTEGER)"
    )
    conn.execute(
        'INSERT INTO "Inbox" VALUES '
        "('uid1', 'Subject 1', 'Sender <sender@example.com>', 'me@example.com', '', 1714896000, 0, 'First preview', 0)"
    )
    conn.execute(
        'INSERT INTO "Inbox" VALUES '
        "('uid2', 'Subject 2', 'Other <other@example.com>', 'me@example.com', '', 1714896001, 16, 'Second preview', 1)"
    )
    conn.commit()
    conn.close()

    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=str(db_file))

    summary_res = await get_emails_logic(
        "fake_account", folder_name="Inbox", limit=2, format="summary"
    )
    assert "## Recent emails in Inbox" in summary_res
    assert "Subject 1" in summary_res
    assert "Sender" in summary_res
    assert "First preview" in summary_res
    assert "Subject 2" in summary_res

    json_res = json.loads(
        await get_emails_logic("fake_account", folder_name="Inbox", limit=2, format="json")
    )
    assert json_res["meta"]["total"] == 2
    by_uid = {item["uid"]: item for item in json_res["items"]}
    assert by_uid["uid1"]["unread"] is True
    assert "unread" not in by_uid["uid2"]
    assert by_uid["uid2"]["has_attachments"] is True
