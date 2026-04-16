import os
import sqlite3
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, Camel, Secret, GLib, Gio  # noqa: E402

logger = logging.getLogger(__name__)

# D-Bus configuration for Evolution MCP Automation Bridge plugin
EVOLUTION_BUS_NAME = "org.gnome.Evolution"
EVOLUTION_OBJECT_PATH = "/org/gnome/evolution/McpAutomationBridge"
EVOLUTION_INTERFACE_NAME = "org.gnome.Evolution.McpAutomationBridge"

def get_mail_db_path(account_uid: str) -> Optional[str]:
    """Resolves the SQLite database path for a given Evolution mail account."""
    potential_paths = [
        os.path.expanduser(f"~/.cache/evolution/mail/{account_uid}/folders.db"),
        os.path.expanduser(f"~/.local/share/evolution/mail/{account_uid}/folders.db")
    ]
    for path in potential_paths:
        if os.path.exists(path):
            return path
    return None

async def list_mail_accounts_logic() -> str:
    """Lists all configured email accounts."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_MAIL_ACCOUNT)
            accounts = []
            for source in sources:
                if source.get_enabled():
                    accounts.append({
                        "uid": source.get_uid(),
                        "name": source.get_display_name()
                    })
            return json.dumps(accounts, indent=2)
        except Exception as e:
            logger.exception("Failed to list mail accounts")
            return f"Error: {e}"
    
    return await asyncio.to_thread(_logic)

async def list_mail_folders_logic(account_uid: str) -> str:
    """Lists folders for a specific mail account."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT folder_name, unread_count, visible_count FROM folders")
            folders = []
            for row in cursor.fetchall():
                folders.append({
                    "name": row[0],
                    "unread": row[1],
                    "total": row[2]
                })
            conn.close()
            return json.dumps(folders, indent=2)
        except Exception as e:
            logger.exception(f"Database error for account {account_uid}")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

async def get_emails_logic(account_uid: str, folder_name: str = "Inbox", limit: int = 10) -> str:
    """Gets recent emails from a specific folder with validation."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Security: Validate folder name exists in the database before using it in a query
            cursor.execute("SELECT folder_name FROM folders WHERE folder_name = ?", (folder_name,))
            if not cursor.fetchone():
                conn.close()
                return f"Error: Folder '{folder_name}' not found in account {account_uid}"

            # Safe to use folder_name as table name now as we've verified it exists in the 'folders' metadata table
            query = f"SELECT uid, subject, mail_from, dreceived, preview FROM '{folder_name}' ORDER BY dreceived DESC LIMIT ?"
            cursor.execute(query, (limit,))

            emails = []
            for row in cursor.fetchall():
                try:
                    date_str = datetime.fromtimestamp(row[3]).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    date_str = str(row[3])

                emails.append({
                    "uid": row[0],
                    "subject": row[1],
                    "from": row[2],
                    "date": date_str,
                    "preview": row[4]
                })
            conn.close()
            return json.dumps(emails, indent=2)
        except Exception as e:
            logger.exception(f"Failed to fetch emails from {folder_name}")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

async def search_emails_logic(account_uid: str, query: str, folder_name: Optional[str] = None, limit: int = 10) -> str:
    """Searches emails for a specific query across all folders or a specific folder."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            folders_to_search = []
            if folder_name:
                cursor.execute("SELECT folder_name FROM folders WHERE folder_name = ?", (folder_name,))
                if not cursor.fetchone():
                    conn.close()
                    return f"Error: Folder '{folder_name}' not found in account {account_uid}"
                folders_to_search.append(folder_name)
            else:
                cursor.execute("SELECT folder_name FROM folders")
                folders_to_search = [row[0] for row in cursor.fetchall()]

            emails = []
            search_pattern = f"%{query}%"

            for folder in folders_to_search:
                # Verify table exists to prevent SQL injection or missing tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (folder,))
                if not cursor.fetchone():
                    continue

                sql = f"""
                    SELECT uid, subject, mail_from, dreceived, preview, '{folder}' as folder
                    FROM '{folder}'
                    WHERE subject LIKE ? OR preview LIKE ? OR mail_from LIKE ?
                    ORDER BY dreceived DESC
                    LIMIT ?
                """
                cursor.execute(sql, (search_pattern, search_pattern, search_pattern, limit))

                for row in cursor.fetchall():
                    try:
                        date_str = datetime.fromtimestamp(row[3]).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        date_str = str(row[3])

                    emails.append({
                        "uid": row[0],
                        "subject": row[1],
                        "from": row[2],
                        "date": date_str,
                        "preview": row[4],
                        "folder": row[5]
                    })

            # Sort combined results by date descending and take top 'limit'
            emails.sort(key=lambda x: x['date'], reverse=True)
            emails = emails[:limit]

            conn.close()
            return json.dumps(emails, indent=2)
        except Exception as e:
            logger.exception(f"Failed to search emails for query '{query}'")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

async def get_email_body_logic(account_uid: str, message_uid: str, folder_name: str = "INBOX") -> str:
    """Retrieves the full body/content of an email from the local cache."""
    def _logic():
        try:
            # 1. Resolve cache directory
            base_cache = os.path.expanduser(f"~/.cache/evolution/mail/{account_uid}/folders")
            if not os.path.exists(base_cache):
                base_cache = os.path.expanduser(f"~/.local/share/evolution/mail/{account_uid}/folders")
            
            folder_path = os.path.join(base_cache, folder_name, "cur")
            if not os.path.exists(folder_path):
                return f"Error: Folder cache not found at {folder_path}"

            # 2. Search for the UID in the hashed subdirectories
            import glob
            search_pattern = os.path.join(folder_path, "*", message_uid)
            matches = glob.glob(search_pattern)
            
            if not matches:
                return f"Error: Message content for UID {message_uid} not found in {folder_name}. It might not be cached locally."

            # 3. Read the file (it's a raw RFC822 message)
            with open(matches[0], 'r', errors='replace') as f:
                content = f.read()
            
            return content
        except Exception as e:
            logger.exception(f"Failed to read email body for {message_uid}")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


def get_dbus_proxy():
    from gi.repository import Gio
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus,
        Gio.DBusProxyFlags.NONE,
        None,
        EVOLUTION_BUS_NAME,
        EVOLUTION_OBJECT_PATH,
        EVOLUTION_INTERFACE_NAME,
        None
    )
    if proxy.get_name_owner() is None:
        raise Exception("Evolution is not running or the MCP automation bridge plugin is disabled. Please start Evolution first.")
    return proxy

async def move_email_logic(account_uid: str, message_uid: str, source_folder: str, dest_folder: str) -> str:
    """
    Moves an email using the Evolution extension D-Bus interface.
    
    This requires the 'evolution-mcp-automation-bridge' plugin to be active in Evolution.
    """
    def _logic():
        try:
            from gi.repository import GLib
            proxy = get_dbus_proxy()

            # Call MoveMessage(account_uid, message_uid, source_folder, dest_folder)
            # Returns (success: boolean, message: string)
            result = proxy.call_sync(
                "MoveMessage",
                GLib.Variant('(ssss)', (account_uid, message_uid, source_folder, dest_folder)),
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            
            success, message = result.unpack()
            if success:
                return f"Successfully moved email: {message}"
            else:
                return f"Failed to move email: {message}"

        except Exception as e:
            logger.error(f"D-Bus move failed: {e}")
            return f"Error: Failed to move email via Evolution D-Bus. Ensure Evolution is running with the MCP automation bridge plugin. Details: {e}"

    return await asyncio.to_thread(_logic)

async def mark_as_read_logic(account_uid: str, message_uid: str, folder_name: str, read: bool = True) -> str:
    """Marks an email as read or unread using the D-Bus interface."""
    def _logic():
        try:
            from gi.repository import GLib
            proxy = get_dbus_proxy()

            # Call MarkAsRead(account_uid, message_uid, folder_name, read)
            result = proxy.call_sync(
                "MarkAsRead",
                GLib.Variant('(sssb)', (account_uid, message_uid, folder_name, read)),
                Gio.DBusCallFlags.NONE, -1, None
            )
            success, message = result.unpack()
            return f"{'Successfully' if success else 'Failed to'} mark as {'read' if read else 'unread'}: {message}"
        except Exception as e:
            logger.error(f"D-Bus mark as read failed: {e}")
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'MarkAsRead'."

    return await asyncio.to_thread(_logic)

async def delete_message_logic(account_uid: str, message_uid: str, folder_name: str) -> str:
    """Deletes an email using the D-Bus interface."""
    def _logic():
        try:
            from gi.repository import GLib
            proxy = get_dbus_proxy()

            # Call DeleteMessage(account_uid, message_uid, folder_name)
            result = proxy.call_sync(
                "DeleteMessage",
                GLib.Variant('(sss)', (account_uid, message_uid, folder_name)),
                Gio.DBusCallFlags.NONE, -1, None
            )
            success, message = result.unpack()
            return f"{'Successfully' if success else 'Failed to'} delete message: {message}"
        except Exception as e:
            logger.error(f"D-Bus delete failed: {e}")
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'DeleteMessage'."

    return await asyncio.to_thread(_logic)

async def send_mail_logic(account_uid: str, to: str, subject: str, body: str) -> str:
    """Sends an email using the D-Bus interface."""
    def _logic():
        try:
            from gi.repository import GLib
            proxy = get_dbus_proxy()

            # Call SendMail(account_uid, to, subject, body)
            result = proxy.call_sync(
                "SendMail",
                GLib.Variant('(ssss)', (account_uid, to, subject, body)),
                Gio.DBusCallFlags.NONE, -1, None
            )
            success, message = result.unpack()
            return f"{'Successfully sent' if success else 'Failed to send'} mail: {message}"
        except Exception as e:
            logger.error(f"D-Bus send failed: {e}")
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'SendMail'."

    return await asyncio.to_thread(_logic)



)



