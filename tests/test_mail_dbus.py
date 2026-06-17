import pytest

from eds_mcp.mail import get_email_body_logic


@pytest.mark.asyncio
async def test_get_email_body_dbus(mocker):
    mock_proxy = mocker.patch('eds_mcp.mail.get_dbus_proxy')
    mock_proxy_instance = mock_proxy.return_value
    mock_result = mocker.MagicMock()
    # Provide a raw message so parser has something to work with
    raw_msg = "From: me@example.com\nSubject: Test\n\ndbus fetched content"
    mock_result.unpack.return_value = (True, raw_msg)
    mock_proxy_instance.call_sync.return_value = mock_result
    
    mocker.patch('glob.glob', return_value=[])

    result = await get_email_body_logic("test_account", "test_msg", "Inbox")
    
    assert "dbus fetched content" in result
    assert "From: me@example.com" in result
    mock_proxy_instance.call_sync.assert_called_once()
