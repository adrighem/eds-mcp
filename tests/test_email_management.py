import pytest
import asyncio
from unittest.mock import MagicMock
from eds_mcp.mail import move_email_logic, delete_message_logic

@pytest.fixture
def mock_gio(mocker):
    mock_gio = mocker.patch('gi.repository.Gio')
    mock_glib = mocker.patch('gi.repository.GLib')
    return mock_gio, mock_glib

@pytest.fixture
def mock_dbus_proxy(mocker):
    mock_proxy = MagicMock()
    mocker.patch('eds_mcp.mail.get_dbus_proxy', return_value=mock_proxy)
    return mock_proxy

@pytest.mark.asyncio
async def test_move_email_success(mock_dbus_proxy, mock_gio):
    mock_gio_pkg, mock_glib = mock_gio
    
    # Mock result of MoveMessage
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "Success")
    mock_dbus_proxy.call_sync.return_value = mock_result

    # Run
    result = await move_email_logic("acc1", "msg1", "Inbox", "Archive")
    
    assert "Successfully moved email: Success" in result
    mock_dbus_proxy.call_sync.assert_called_once()
    # Check variant construction
    args = mock_dbus_proxy.call_sync.call_args[0]
    assert args[0] == "MoveMessage"

@pytest.mark.asyncio
async def test_move_email_failure(mock_dbus_proxy, mock_gio):
    mock_gio_pkg, mock_glib = mock_gio
    
    # Mock failure result
    mock_result = MagicMock()
    mock_result.unpack.return_value = (False, "Folder not found")
    mock_dbus_proxy.call_sync.return_value = mock_result

    # Run
    result = await move_email_logic("acc1", "msg1", "Inbox", "NonExistent")
    
    assert "Failed to move email: Folder not found" in result

@pytest.mark.asyncio
async def test_delete_email_success(mock_dbus_proxy, mock_gio):
    mock_gio_pkg, mock_glib = mock_gio
    
    # Mock result of DeleteMessage
    mock_result = MagicMock()
    mock_result.unpack.return_value = (True, "Success")
    mock_dbus_proxy.call_sync.return_value = mock_result

    # Run
    result = await delete_message_logic("acc1", "msg1", "Inbox")
    
    assert "Successfully delete message: Success" in result
    mock_dbus_proxy.call_sync.assert_called_once()

@pytest.mark.asyncio
async def test_delete_email_failure(mock_dbus_proxy, mock_gio):
    mock_gio_pkg, mock_glib = mock_gio
    
    # Mock failure result
    mock_result = MagicMock()
    mock_result.unpack.return_value = (False, "Message not found")
    mock_dbus_proxy.call_sync.return_value = mock_result

    # Run
    result = await delete_message_logic("acc1", "msg1", "Inbox")
    
    assert "Failed to delete message: Message not found" in result

@pytest.mark.asyncio
async def test_dbus_exception_handling(mock_dbus_proxy, mock_gio):
    mock_gio_pkg, mock_glib = mock_gio
    
    # Mock D-Bus error
    mock_dbus_proxy.call_sync.side_effect = Exception("D-Bus error")

    # Run
    result = await move_email_logic("acc1", "msg1", "Inbox", "Archive")
    
    assert "Error: Failed to move email via Evolution D-Bus" in result
    assert "D-Bus error" in result
