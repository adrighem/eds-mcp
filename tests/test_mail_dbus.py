import pytest

from eds_mcp.mail import (
    BRIDGE_CALL_TIMEOUT_MS,
    BRIDGE_READ_FALLBACK_ENV,
    get_email_body_logic,
    list_attachments_logic,
    save_attachment_logic,
)


@pytest.mark.asyncio
async def test_get_email_body_does_not_call_bridge_by_default(mocker, monkeypatch):
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    result = await get_email_body_logic("test_account", "test_msg", "Inbox")

    assert "not found in the local Evolution cache" in result
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_email_body_dbus_fallback_when_enabled(mocker, monkeypatch):
    monkeypatch.setenv(BRIDGE_READ_FALLBACK_ENV, "1")
    raw_msg = "From: me@example.com\nSubject: Test\n\ndbus fetched content"
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=None)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method", return_value=(True, raw_msg))

    result = await get_email_body_logic("test_account", "test_msg", "Inbox")

    assert "dbus fetched content" in result
    assert "From: me@example.com" in result
    bridge_call.assert_called_once_with("GetMessage", "(sss)", ("test_account", "test_msg", "Inbox"))


@pytest.mark.asyncio
async def test_list_attachments_uses_cached_message(mocker, monkeypatch):
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    raw_msg = """From: me@example.com
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
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=raw_msg)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    result = await list_attachments_logic("test_account", "test_msg", "Inbox")

    assert result == '[{"filename":"notes.txt","mime_type":"text/plain"}]'
    bridge_call.assert_not_called()


@pytest.mark.asyncio
async def test_save_attachment_uses_cached_message(mocker, monkeypatch, tmp_path):
    monkeypatch.delenv(BRIDGE_READ_FALLBACK_ENV, raising=False)
    def fake_mkdtemp(prefix):
        path = tmp_path / prefix.rstrip("_")
        path.mkdir()
        return str(path)

    monkeypatch.setattr("tempfile.mkdtemp", fake_mkdtemp)
    raw_msg = """From: me@example.com
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
    mocker.patch("eds_mcp.mail.read_cached_message", return_value=raw_msg)
    bridge_call = mocker.patch("eds_mcp.mail.call_bridge_method")

    result = await save_attachment_logic("test_account", "test_msg", "Inbox", "notes.txt")

    assert result.startswith("Attachment saved to: ")
    saved_path = result.removeprefix("Attachment saved to: ")
    with open(saved_path, "rb") as f:
        assert f.read() == b"attachment content"
    bridge_call.assert_not_called()


def test_call_bridge_method_uses_timeout(mocker):
    from eds_mcp.mail import call_bridge_method

    proxy = mocker.patch("eds_mcp.mail.get_dbus_proxy").return_value
    result = mocker.MagicMock()
    result.unpack.return_value = (True, "ok")
    proxy.call_sync.return_value = result

    assert call_bridge_method("MoveMessage", "(ssss)", ("a", "b", "c", "d")) == (True, "ok")

    args = proxy.call_sync.call_args[0]
    assert args[3] == BRIDGE_CALL_TIMEOUT_MS
