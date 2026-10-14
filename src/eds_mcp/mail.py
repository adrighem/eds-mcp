import os
import sqlite3
import json
import logging
import asyncio
import tempfile
from datetime import datetime
from typing import Optional, Union, Any

from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, Gio, GLib  # noqa: E402

from .mail_bridge import (
    EVOLUTION_BUS_NAME,
    EVOLUTION_OBJECT_PATH,
    EVOLUTION_INTERFACE_NAME,
    BRIDGE_READ_FALLBACK_ENV,
    BRIDGE_CALL_TIMEOUT_MS,
    bridge_read_fallback_enabled,
    get_dbus_proxy as _bridge_get_dbus_proxy,
    call_bridge_method as _bridge_call_bridge_method,
)
from .mail_parser import (
    MAX_ATTACHMENT_COUNT,
    MAX_ATTACHMENT_TOTAL_BYTES,
    MAX_BODY_LENGTH,
    clean_html,
    extract_text_from_message,
    get_cached_message_path,
    read_cached_message,
    list_attachments_from_message,
    save_attachment_from_message,
    normalize_attachment_paths,
    extract_reply_headers,
    normalize_recipients,
)

logger = logging.getLogger(__name__)


def get_dbus_proxy() -> Gio.DBusProxy:
    """Acquires D-Bus proxy for Evolution MCP automation bridge."""
    return _bridge_get_dbus_proxy()


def call_bridge_method(method_name: str, variant_signature: str, parameters: tuple) -> Any:
    """Call method on Evolution automation bridge via configured proxy."""
    return _bridge_call_bridge_method(
        method_name,
        variant_signature,
        parameters,
        proxy_getter=get_dbus_proxy,
    )


def get_mail_db_path(account_uid: str) -> Optional[str]:
    """Resolves SQLite database path for given Evolution mail account."""
    potential_paths = [
        os.path.expanduser(f"~/.cache/evolution/mail/{account_uid}/folders.db"),
        os.path.expanduser(f"~/.local/share/evolution/mail/{account_uid}/folders.db"),
    ]
    for path in potential_paths:
        if os.path.exists(path):
            return path
    return None


async def list_mail_accounts_logic() -> str:
    """Lists all configured email accounts."""
    def _logic() -> str:
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_MAIL_ACCOUNT)
            accounts = []
            for source in sources:
                if source.get_enabled():
                    parent_uid = source.get_parent()
                    parent_name = None
                    if parent_uid:
                        parent_source = registry.ref_source(parent_uid)
                        if parent_source:
                            parent_name = parent_source.get_display_name()

                    accounts.append({
                        "uid": source.get_uid(),
                        "name": source.get_display_name(),
                        "parent_uid": parent_uid,
                        "parent_name": parent_name,
                    })
            return json.dumps(accounts, separators=(',', ':'))
        except (GLib.Error, RuntimeError) as e:
            logger.exception("Failed to list mail accounts")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


async def list_mail_folders_logic(account_uid: str) -> str:
    """Lists folders for specific mail account."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic() -> str:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT folder_name, unread_count, visible_count FROM folders")
            folders = [
                {"name": row[0], "unread": row[1], "total": row[2]}
                for row in cursor.fetchall()
            ]
            conn.close()
            return json.dumps(folders, separators=(',', ':'))
        except sqlite3.Error as e:
            logger.exception("Database error for account %s", account_uid)
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


async def get_emails_logic(account_uid: str, folder_name: str = "Inbox", limit: int = 10, format: str = "json") -> str:
    """Gets recent emails from specific folder with validation."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic() -> str:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT folder_name FROM folders WHERE folder_name = ?", (folder_name,))
            if not cursor.fetchone():
                conn.close()
                return f"Error: Folder '{folder_name}' not found in account {account_uid}"

            query = f"SELECT uid, subject, mail_from, dreceived, preview FROM '{folder_name}' ORDER BY dreceived DESC LIMIT ?"
            cursor.execute(query, (limit,))

            emails = []
            for row in cursor.fetchall():
                try:
                    date_str = datetime.fromtimestamp(row[3]).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError, OverflowError):
                    date_str = str(row[3])

                email = {
                    "uid": row[0],
                    "subject": row[1],
                    "from": row[2],
                    "date": date_str,
                }
                if row[4] and row[4].strip():
                    email["preview"] = row[4].strip()
                emails.append(email)
            conn.close()

            if format == "summary":
                if not emails:
                    return f"No emails found in {folder_name}."

                output = [f"## Recent emails in {folder_name}"]
                for e in emails:
                    sender = e["from"].split("<")[0].strip() or e["from"]
                    line = f"* **{e['subject']}** (from: {sender}, {e['date']})"
                    if "preview" in e:
                        snippet = e["preview"][:100] + "..." if len(e["preview"]) > 100 else e["preview"]
                        line += f"\n  _{snippet}_"
                    output.append(line)
                return "\n".join(output)

            return json.dumps(emails, separators=(',', ':'))
        except sqlite3.Error as e:
            logger.exception("Failed to fetch emails from %s", folder_name)
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


async def search_emails_logic(account_uid: str, query: str, folder_name: Optional[str] = None, limit: int = 10) -> str:
    """Searches emails for query across all folders or specific folder."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    def _logic() -> str:
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

            all_results = []
            search_pattern = f"%{query}%"

            for folder in folders_to_search:
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
                    except (ValueError, OSError, OverflowError):
                        date_str = str(row[3])

                    res = {
                        "uid": row[0],
                        "subject": row[1],
                        "from": row[2],
                        "date": date_str,
                        "folder": row[5],
                    }
                    if row[4] and row[4].strip():
                        res["preview"] = row[4].strip()
                    all_results.append(res)

            all_results.sort(key=lambda x: x['date'], reverse=True)
            all_results = all_results[:limit]

            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in all_results:
                f = item.pop("folder")
                grouped.setdefault(f, []).append(item)

            conn.close()
            return json.dumps(grouped, separators=(',', ':'))
        except sqlite3.Error as e:
            logger.exception("Failed to search emails for query '%s'", query)
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


async def get_email_body_logic(account_uid: str, message_uid: str, folder_name: str = "INBOX") -> str:
    """Retrieves and optimizes body/content of email message."""
    def _logic() -> str:
        try:
            raw_content = read_cached_message(account_uid, message_uid, folder_name)

            if raw_content is None:
                if not bridge_read_fallback_enabled():
                    return (
                        f"Error: Message content for UID {message_uid} was not found in the local Evolution cache. "
                        f"Open or sync the message in Evolution first. To allow the in-process Evolution bridge "
                        f"fallback for read operations, set {BRIDGE_READ_FALLBACK_ENV}=1."
                    )

                try:
                    success, dbus_content = call_bridge_method(
                        "GetMessage",
                        '(sss)',
                        (account_uid, message_uid, folder_name),
                    )
                    if success:
                        raw_content = dbus_content
                    else:
                        return f"Error: Message content for UID {message_uid} not found locally, and D-Bus fetch failed: {dbus_content}"
                except Exception as dbus_e:
                    logger.warning("D-Bus fallback failed for %s: %s", message_uid, dbus_e)
                    return f"Error: Message content for UID {message_uid} not found in {folder_name}. It might not be cached locally."

            return extract_text_from_message(raw_content)
        except Exception as e:
            logger.exception("Failed to read email body for %s", message_uid)
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)


async def move_email_logic(account_uid: str, message_uid: str, source_folder: str, dest_folder: str) -> str:
    """Moves email using Evolution extension D-Bus interface."""
    def _logic() -> str:
        try:
            success, message = call_bridge_method(
                "MoveMessage",
                '(ssss)',
                (account_uid, message_uid, source_folder, dest_folder),
            )
            return f"Successfully moved email: {message}" if success else f"Failed to move email: {message}"
        except Exception as e:
            logger.error("D-Bus move failed: %s", e)
            return f"Error: Failed to move email via Evolution D-Bus. Ensure Evolution is running with the MCP automation bridge plugin. Details: {e}"

    return await asyncio.to_thread(_logic)


async def mark_as_read_logic(account_uid: str, message_uid: str, folder_name: str, read: bool = True) -> str:
    """Marks email as read or unread using D-Bus interface."""
    def _logic() -> str:
        try:
            success, message = call_bridge_method(
                "MarkAsRead",
                '(sssb)',
                (account_uid, message_uid, folder_name, read),
            )
            return f"{'Successfully' if success else 'Failed to'} mark as {'read' if read else 'unread'}: {message}"
        except Exception as e:
            logger.error("D-Bus mark as read failed: %s", e)
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'MarkAsRead'."

    return await asyncio.to_thread(_logic)


async def delete_message_logic(account_uid: str, message_uid: str, folder_name: str) -> str:
    """Deletes email using D-Bus interface."""
    def _logic() -> str:
        try:
            success, message = call_bridge_method(
                "DeleteMessage",
                '(sss)',
                (account_uid, message_uid, folder_name),
            )
            return f"{'Successfully' if success else 'Failed to'} delete message: {message}"
        except Exception as e:
            logger.error("D-Bus delete failed: %s", e)
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'DeleteMessage'."

    return await asyncio.to_thread(_logic)


async def send_mail_logic(
    account_uid: str,
    to: Union[str, list[str]],
    subject: str,
    body: str,
    cc: Optional[Union[str, list[str]]] = None,
    bcc: Optional[Union[str, list[str]]] = None,
    attachment_paths: Optional[list[str]] = None,
    reply_to_message_uid: Optional[str] = None,
    reply_to_folder: str = "Inbox",
) -> str:
    """Sends email using D-Bus interface."""
    def _logic() -> str:
        try:
            to_norm = normalize_recipients(to)
            if not to_norm:
                return "Error: At least one 'to' recipient is required."
            cc_norm = normalize_recipients(cc)
            bcc_norm = normalize_recipients(bcc)

            normalized_paths = normalize_attachment_paths(attachment_paths)
            in_reply_to = ""
            references = ""

            if reply_to_message_uid:
                raw_content = read_cached_message(account_uid, reply_to_message_uid, reply_to_folder)
                if raw_content is None:
                    success, raw_content = call_bridge_method(
                        "GetMessage",
                        '(sss)',
                        (account_uid, reply_to_message_uid, reply_to_folder),
                    )
                    if not success:
                        return "Failed to send mail: reply source message could not be read."
                in_reply_to, references = extract_reply_headers(raw_content)

            if normalized_paths or reply_to_message_uid or cc_norm or bcc_norm:
                success, message = call_bridge_method(
                    "SendMailWithAttachments",
                    '(ssssassss)',
                    (
                        account_uid,
                        to_norm,
                        subject,
                        body,
                        normalized_paths,
                        in_reply_to,
                        references,
                        cc_norm,
                        bcc_norm,
                    ),
                )
                if not success and "signature" in str(message).lower() and not cc_norm and not bcc_norm:
                    success, message = call_bridge_method(
                        "SendMailWithAttachments",
                        '(ssssasss)',
                        (
                            account_uid,
                            to_norm,
                            subject,
                            body,
                            normalized_paths,
                            in_reply_to,
                            references,
                        ),
                    )
            else:
                success, message = call_bridge_method(
                    "SendMail",
                    '(ssss)',
                    (account_uid, to_norm, subject, body),
                )
            return f"{'Successfully sent' if success else 'Failed to send'} mail: {message}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error("D-Bus send failed: %s", e)
            return f"Error: {e}. Ensure the Evolution MCP automation bridge is current."

    return await asyncio.to_thread(_logic)


async def list_attachments_logic(account_uid: str, message_uid: str, folder_name: str = "INBOX") -> str:
    """Lists attachments for specific email message."""
    def _logic() -> str:
        try:
            raw_content = read_cached_message(account_uid, message_uid, folder_name)
            if raw_content is not None:
                return json.dumps(list_attachments_from_message(raw_content), separators=(',', ':'))

            if not bridge_read_fallback_enabled():
                return (
                    f"Error: Message content for UID {message_uid} was not found in the local Evolution cache. "
                    f"Open or sync the message in Evolution first. To allow the in-process Evolution bridge "
                    f"fallback for read operations, set {BRIDGE_READ_FALLBACK_ENV}=1."
                )

            success, attachments_json = call_bridge_method(
                "ListAttachments",
                '(sss)',
                (account_uid, message_uid, folder_name),
            )
            return attachments_json if success else f"Error: {attachments_json}"
        except Exception as e:
            logger.error("D-Bus list attachments failed: %s", e)
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'ListAttachments'."

    return await asyncio.to_thread(_logic)


async def save_attachment_logic(account_uid: str, message_uid: str, folder_name: str, attachment_name: str) -> str:
    """Saves attachment to temporary file and returns path."""
    def _logic() -> str:
        try:
            raw_content = read_cached_message(account_uid, message_uid, folder_name)
            if raw_content is not None:
                dest_path = save_attachment_from_message(raw_content, attachment_name)
                return f"Attachment saved to: {dest_path}" if dest_path else f"Error: Attachment '{attachment_name}' not found."

            if not bridge_read_fallback_enabled():
                return (
                    f"Error: Message content for UID {message_uid} was not found in the local Evolution cache. "
                    f"Open or sync the message in Evolution first. To allow the in-process Evolution bridge "
                    f"fallback for read operations, set {BRIDGE_READ_FALLBACK_ENV}=1."
                )

            temp_dir = tempfile.mkdtemp(prefix="eds_mcp_attachment_")
            safe_name = os.path.basename(attachment_name)
            if not safe_name:
                return "Error: Attachment name is invalid."
            dest_path = os.path.join(temp_dir, safe_name)

            success, message = call_bridge_method(
                "SaveAttachment",
                '(sssss)',
                (account_uid, message_uid, folder_name, attachment_name, dest_path),
            )
            return f"Attachment saved to: {dest_path}" if success else f"Error: {message}"
        except Exception as e:
            logger.error("D-Bus save attachment failed: %s", e)
            return f"Error: {e}. Ensure the MCP automation bridge plugin supports 'SaveAttachment'."

    return await asyncio.to_thread(_logic)
