"""Tests for mail compose, draft creation, and interactive composer tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from eds_mcp import BridgeUnavailableError
from eds_mcp.mail import (
    create_draft_logic,
    delete_message_logic,
    mark_as_read_logic,
    move_email_logic,
    open_composer_logic,
    send_mail_logic,
)


@pytest.fixture(autouse=True)
def _isolate_mail_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "eds_mcp.mail_db.get_mail_roots",
        lambda uid: [str(tmp_path / "evo_mail" / uid)],
    )


@pytest.mark.asyncio
async def test_create_draft_success_and_empty_recipient(mocker: Any) -> None:
    """SaveDraft called with 9-element tuple, allows empty recipient, returns draft_saved."""
    mock_bridge = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "Drafts", "draft-42"),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)

    raw_res = await create_draft_logic(
        account_uid="acc1",
        to="",
        subject="Draft subject",
        body="Draft body text",
    )
    data: dict[str, Any] = json.loads(raw_res)
    assert data["status"] == "draft_saved"
    assert data["folder"] == "Drafts"
    assert data["draft_uid"] == "draft-42"

    mock_bridge.assert_called_once_with(
        "SaveDraft",
        "(ssssasssss)",
        ("acc1", "", "Draft subject", "Draft body text", [], "", "", "", ""),
    )


@pytest.mark.asyncio
async def test_create_draft_with_reply_headers(mocker: Any) -> None:
    """Propagate In-Reply-To and References from reply_to_message_uid into SaveDraft."""
    mock_bridge = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "Drafts", "draft-99"),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mocker.patch(
        "eds_mcp.mail.read_cached_message",
        return_value=(
            "Message-ID: <parent-msg@example.com>\r\n"
            "References: <root-msg@example.com>\r\n\r\n"
            "Parent body"
        ),
    )

    raw_res = await create_draft_logic(
        account_uid="acc1",
        to="alice@example.com",
        subject="Re: Topic",
        body="Reply draft",
        reply_to_message_uid="msg-parent-42",
        reply_to_folder="Inbox",
    )
    data: dict[str, Any] = json.loads(raw_res)
    assert data["status"] == "draft_saved"
    assert data["draft_uid"] == "draft-99"
    assert data["in_reply_to"] == "<parent-msg@example.com>"

    mock_bridge.assert_called_once_with(
        "SaveDraft",
        "(ssssasssss)",
        (
            "acc1",
            "alice@example.com",
            "Re: Topic",
            "Reply draft",
            [],
            "<parent-msg@example.com>",
            "<root-msg@example.com> <parent-msg@example.com>",
            "",
            "",
        ),
    )


@pytest.mark.asyncio
async def test_create_draft_bridge_failure(mocker: Any) -> None:
    """Failed bridge SaveDraft call returns structured BRIDGE_CALL_FAILED error."""
    mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(False, "Failed to save draft: Disk full", ""),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)

    raw_res = await create_draft_logic("acc1", subject="Test", body="Body")
    data: dict[str, Any] = json.loads(raw_res)
    assert "error" in data
    assert data["error"]["code"] == "BRIDGE_CALL_FAILED"
    assert "Disk full" in data["error"]["message"]


@pytest.mark.asyncio
async def test_open_composer_success(tmp_path: Path, mocker: Any) -> None:
    """OpenComposer called with 9-element tuple, reply headers, and attachments."""
    mock_bridge = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "Composer window opened"),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mocker.patch(
        "eds_mcp.mail.read_cached_message",
        return_value="Message-ID: <orig-100@example.com>\r\n\r\nPrior text",
    )

    doc_file = tmp_path / "attachment.pdf"
    doc_file.write_bytes(b"%PDF-test")

    raw_res = await open_composer_logic(
        account_uid="acc1",
        to=["bob@example.com", "carol@example.com"],
        subject="Discussion",
        body="Opening interactive compose",
        attachment_paths=[str(doc_file)],
        reply_to_message_uid="msg-orig-100",
        reply_to_folder="Inbox",
    )
    data: dict[str, Any] = json.loads(raw_res)
    assert data["status"] == "composer_opened"
    assert data["message"] == "Composer window opened"

    expected_path = str(doc_file.resolve())
    mock_bridge.assert_called_once_with(
        "OpenComposer",
        "(ssssasssss)",
        (
            "acc1",
            "bob@example.com, carol@example.com",
            "Discussion",
            "Opening interactive compose",
            [expected_path],
            "<orig-100@example.com>",
            "<orig-100@example.com>",
            "",
            "",
        ),
    )


@pytest.mark.asyncio
async def test_open_composer_bridge_errors(mocker: Any) -> None:
    """Return BRIDGE_CALL_FAILED on failed bridge call and BRIDGE_UNAVAILABLE on exception."""
    mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(False, "GUI process not found"),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)

    failed_raw = await open_composer_logic("acc1", subject="Fail")
    failed_data: dict[str, Any] = json.loads(failed_raw)
    assert failed_data["error"]["code"] == "BRIDGE_CALL_FAILED"

    mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        side_effect=BridgeUnavailableError("Session D-Bus unavailable"),
    )
    unavail_raw = await open_composer_logic("acc1", subject="Unavail")
    unavail_data: dict[str, Any] = json.loads(unavail_raw)
    assert unavail_data["error"]["code"] == "BRIDGE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_send_mail_logic(mocker: Any) -> None:
    """SendMail succeeds and returns structured sent status."""
    mock_bridge = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "Message delivered"),
    )
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)

    raw_res = await send_mail_logic(
        account_uid="acc1",
        to="dest@example.com",
        subject="Important",
        body="Message content",
    )
    data: dict[str, Any] = json.loads(raw_res)
    assert data["status"] == "sent"
    assert data["message"] == "Message delivered"

    mock_bridge.assert_called_once_with(
        "SendMail",
        "(ssss)",
        ("acc1", "dest@example.com", "Important", "Message content"),
    )


@pytest.mark.asyncio
async def test_move_mark_and_delete_actions(mocker: Any) -> None:
    """MoveMessage, MarkAsRead, and DeleteMessage return structured success payloads."""
    mock_bridge = MagicMock()
    mock_bridge.side_effect = [
        (True, "Message moved"),
        (True, "Marked as read"),
        (True, "Message deleted"),
    ]
    mocker.patch("eds_mcp.mail.call_bridge_method", mock_bridge)
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)

    move_raw = await move_email_logic("acc1", "msg1", "Inbox", "Archive")
    move_data: dict[str, Any] = json.loads(move_raw)
    assert move_data["status"] == "moved"
    assert move_data["uid"] == "msg1"

    read_raw = await mark_as_read_logic("acc1", "msg1", "Inbox", read=True)
    read_data: dict[str, Any] = json.loads(read_raw)
    assert read_data["status"] == "updated"
    assert read_data["read"] is True

    delete_raw = await delete_message_logic("acc1", "msg1", "Inbox")
    delete_data: dict[str, Any] = json.loads(delete_raw)
    assert delete_data["status"] == "deleted"
    assert delete_data["uid"] == "msg1"
