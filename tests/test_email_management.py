from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from eds_mcp.mail import (
    delete_message_logic,
    mark_as_read_logic,
    move_email_logic,
    normalize_recipients,
    send_mail_logic,
)
from eds_mcp.mail_parser import MAX_ATTACHMENT_TOTAL_BYTES


@pytest.fixture(autouse=True)
def _isolate_mail_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(
        "eds_mcp.mail_db.get_mail_roots",
        lambda uid: [str(tmp_path / "evo_mail" / uid)],
    )


@pytest.fixture
def mock_dbus_proxy(mocker: Any) -> MagicMock:
    mock_proxy = MagicMock()
    mocker.patch("eds_mcp.mail_bridge.get_dbus_proxy", return_value=mock_proxy)
    return mock_proxy


@pytest.mark.asyncio
async def test_move_email_success(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "Success")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(await move_email_logic("acc1", "msg1", "Inbox", "Archive"))

    assert payload["status"] == "moved"
    assert payload["uid"] == "msg1"
    assert payload["source_folder"] == "Inbox"
    assert payload["dest_folder"] == "Archive"
    mock_dbus_proxy.call_sync.assert_called_once()
    assert mock_dbus_proxy.call_sync.call_args[0][0] == "MoveMessage"


@pytest.mark.asyncio
async def test_move_email_failure(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_result = MagicMock()
    mock_result.unpack.return_value = (False, "Folder not found")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(await move_email_logic("acc1", "msg1", "Inbox", "NonExistent"))

    assert payload["error"]["code"] == "BRIDGE_CALL_FAILED"
    assert "Folder not found" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_delete_email_success(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "Success")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(await delete_message_logic("acc1", "msg1", "Inbox"))

    assert payload["status"] == "deleted"
    assert payload["uid"] == "msg1"
    mock_dbus_proxy.call_sync.assert_called_once()


@pytest.mark.asyncio
async def test_delete_email_failure(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_result = MagicMock()
    mock_result.unpack.return_value = (False, "Message not found")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(await delete_message_logic("acc1", "msg1", "Inbox"))

    assert payload["error"]["code"] == "BRIDGE_CALL_FAILED"
    assert "Message not found" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_mark_email_as_read_success(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "Message marked as read")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(await mark_as_read_logic("acc1", "msg1", "Inbox", True))

    assert payload["status"] == "updated"
    assert payload["read"] is True
    mock_dbus_proxy.call_sync.assert_called_once()
    assert mock_dbus_proxy.call_sync.call_args[0][0] == "MarkAsRead"


@pytest.mark.asyncio
async def test_dbus_exception_handling(mock_dbus_proxy: MagicMock, mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mock_dbus_proxy.call_sync.side_effect = RuntimeError("D-Bus error")

    payload = json.loads(await move_email_logic("acc1", "msg1", "Inbox", "Archive"))

    assert payload["error"]["code"] == "BRIDGE_CALL_FAILED"
    assert "D-Bus error" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_send_mail_success(mocker: Any) -> None:
    bridge_call = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "queued"),
    )

    payload = json.loads(await send_mail_logic("acc1", "to@example.test", "Subject", "Body"))

    assert payload["status"] == "sent"
    assert payload["message"] == "queued"
    bridge_call.assert_called_once_with(
        "SendMail",
        "(ssss)",
        ("acc1", "to@example.test", "Subject", "Body"),
    )


@pytest.mark.asyncio
async def test_send_mail_empty_attachment_list_uses_legacy_method(mocker: Any) -> None:
    bridge_call = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "queued"),
    )

    await send_mail_logic("acc1", "to@example.test", "Subject", "Body", attachment_paths=[])

    bridge_call.assert_called_once_with(
        "SendMail",
        "(ssss)",
        ("acc1", "to@example.test", "Subject", "Body"),
    )


@pytest.mark.asyncio
async def test_send_mail_with_attachment_builds_valid_glib_variant(
    mock_dbus_proxy: MagicMock, tmp_path: Any
) -> None:
    attachment = tmp_path / "report.xlsx"
    attachment.write_bytes(b"workbook")
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "queued")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(
        await send_mail_logic(
            "acc1",
            "to@example.test",
            "Subject",
            "Body",
            attachment_paths=[str(attachment)],
        )
    )

    assert payload["status"] == "sent"
    call_args = mock_dbus_proxy.call_sync.call_args[0]
    assert call_args[0] == "SendMailWithAttachments"
    assert call_args[1].get_type_string() == "(ssssasssss)"
    assert call_args[1].unpack() == (
        "acc1",
        "to@example.test",
        "Subject",
        "Body",
        [str(attachment.resolve())],
        "",
        "",
        "",
        "",
    )


@pytest.mark.asyncio
async def test_send_mail_rejects_missing_attachment_without_leaking_path(
    mocker: Any, tmp_path: Any
) -> None:
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")
    missing = tmp_path / "missing.xlsx"

    result = await send_mail_logic(
        "acc1",
        "to@example.test",
        "Subject",
        "Body",
        attachment_paths=[str(missing)],
    )
    payload = json.loads(result)

    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "missing.xlsx" in payload["error"]["message"]
    assert str(tmp_path) not in result
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_mail_rejects_too_many_attachments(mocker: Any) -> None:
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    payload = json.loads(
        await send_mail_logic(
            "acc1",
            "to@example.test",
            "Subject",
            "Body",
            attachment_paths=[f"attachment-{index}" for index in range(11)],
        )
    )

    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "allowed" in payload["error"]["message"]
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_mail_rejects_oversized_attachment(mocker: Any, tmp_path: Any) -> None:
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")
    attachment = tmp_path / "large.bin"
    with attachment.open("wb") as file_handle:
        file_handle.truncate(MAX_ATTACHMENT_TOTAL_BYTES + 1)

    payload = json.loads(
        await send_mail_logic(
            "acc1",
            "to@example.test",
            "Subject",
            "Body",
            attachment_paths=[str(attachment)],
        )
    )

    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "exceed" in payload["error"]["message"]
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_mail_as_threaded_reply(mocker: Any) -> None:
    mocker.patch("eds_mcp.mail.get_mail_db_path", return_value=None)
    mocker.patch(
        "eds_mcp.mail.read_cached_message",
        return_value=(
            "Message-ID: <message@example.test>\r\nReferences: <root@example.test>\r\n\r\nBody"
        ),
    )
    bridge_call = mocker.patch(
        "eds_mcp.mail.call_bridge_method",
        return_value=(True, "queued"),
    )

    payload = json.loads(
        await send_mail_logic(
            "acc1",
            "to@example.test",
            "Re: Subject",
            "Reply",
            reply_to_message_uid="message-uid",
            reply_to_folder="Inbox",
        )
    )

    assert payload["status"] == "sent"
    assert payload["in_reply_to"] == "<message@example.test>"
    bridge_call.assert_called_once_with(
        "SendMailWithAttachments",
        "(ssssasssss)",
        (
            "acc1",
            "to@example.test",
            "Re: Subject",
            "Reply",
            [],
            "<message@example.test>",
            "<root@example.test> <message@example.test>",
            "",
            "",
        ),
    )


def test_normalize_recipients() -> None:
    assert normalize_recipients(None) == ""
    assert normalize_recipients("") == ""
    assert normalize_recipients("user@example.test") == "user@example.test"
    assert (
        normalize_recipients("u1@example.test, u2@example.test; u3@example.test")
        == "u1@example.test, u2@example.test, u3@example.test"
    )
    assert (
        normalize_recipients(["u1@example.test", "u2@example.test; u3@example.test"])
        == "u1@example.test, u2@example.test, u3@example.test"
    )
    assert (
        normalize_recipients(["  u1@example.test  ", "", "u2@example.test"])
        == "u1@example.test, u2@example.test"
    )

    with pytest.raises(ValueError):
        normalize_recipients(123)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        normalize_recipients(["valid@example.test", 456])  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_send_mail_with_cc_bcc_and_multiple_to(mock_dbus_proxy: MagicMock) -> None:
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "queued")
    mock_dbus_proxy.call_sync.return_value = mock_result

    payload = json.loads(
        await send_mail_logic(
            account_uid="acc1",
            to=["to1@example.test", "to2@example.test; to3@example.test"],
            subject="Multi test",
            body="Body",
            cc="cc1@example.test, cc2@example.test",
            bcc=["bcc1@example.test"],
        )
    )

    assert payload["status"] == "sent"
    call_args = mock_dbus_proxy.call_sync.call_args[0]
    assert call_args[0] == "SendMailWithAttachments"
    assert call_args[1].get_type_string() == "(ssssasssss)"
    assert call_args[1].unpack() == (
        "acc1",
        "to1@example.test, to2@example.test, to3@example.test",
        "Multi test",
        "Body",
        [],
        "",
        "",
        "cc1@example.test, cc2@example.test",
        "bcc1@example.test",
    )


@pytest.mark.asyncio
async def test_send_mail_validation_errors(mocker: Any) -> None:
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    res1 = json.loads(await send_mail_logic("acc1", "", "Subject", "Body"))
    assert res1["error"]["code"] == "VALIDATION_ERROR"
    assert "required" in res1["error"]["message"]

    res2 = json.loads(await send_mail_logic("acc1", ["   "], "Subject", "Body"))
    assert res2["error"]["code"] == "VALIDATION_ERROR"

    res3 = json.loads(await send_mail_logic("acc1", 123, "Subject", "Body"))  # type: ignore[arg-type]
    assert res3["error"]["code"] == "VALIDATION_ERROR"
    assert "Invalid recipients type" in res3["error"]["message"]
    bridge_call.assert_not_called()
