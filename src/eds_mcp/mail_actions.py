"""Bridge-backed mail mutations, draft creation, and interactive composer tools."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from . import (
    BridgeCallError,
    EdsMcpError,
    ValidationError,
    error_from_exception,
    ok_envelope,
)
from .mail_bridge import call_bridge_method
from .mail_cache import (
    extract_reply_headers,
    normalize_attachment_paths,
    normalize_recipients,
    read_cached_message,
)
from .mail_db import get_mail_db_path, resolve_folder_name

logger = logging.getLogger(__name__)


def _resolve_reply_headers(
    account_uid: str,
    reply_to_message_uid: str | None,
    reply_to_folder: str,
    *,
    db_fn: Callable[[str], str | None],
    cache_fn: Callable[[str, str, str], str | None],
    caller_fn: Callable[[str, str, tuple[Any, ...]], Any],
) -> tuple[str, str]:
    """Fetch In-Reply-To and References headers from cache or bridge for threaded replies."""
    if not reply_to_message_uid:
        return "", ""
    resolved_folder = resolve_folder_name(account_uid, reply_to_folder, db_path_getter=db_fn)
    raw_content = cache_fn(account_uid, reply_to_message_uid, resolved_folder)
    if raw_content is None:
        success, fetched = caller_fn(
            "GetMessage", "(sss)", (account_uid, reply_to_message_uid, resolved_folder)
        )
        if not success or not fetched:
            raise BridgeCallError(
                "Reply source message could not be read from cache or Evolution bridge.",
                hint="Verify reply_to_message_uid and reply_to_folder, or sync the folder in Evolution.",
            )
        raw_content = str(fetched)
    return extract_reply_headers(raw_content)


def _prepare_outgoing_payload(
    *,
    account_uid: str,
    to: str | list[str] | None,
    cc: str | list[str] | None,
    bcc: str | list[str] | None,
    attachment_paths: list[str] | None,
    reply_to_message_uid: str | None,
    reply_to_folder: str,
    require_recipient: bool,
    db_fn: Callable[[str], str | None],
    cache_fn: Callable[[str, str, str], str | None],
    caller_fn: Callable[[str, str, tuple[Any, ...]], Any],
) -> tuple[str, str, str, list[str], str, str]:
    to_norm = normalize_recipients(to)
    cc_norm = normalize_recipients(cc)
    bcc_norm = normalize_recipients(bcc)
    if require_recipient and not to_norm:
        raise ValidationError("At least one 'to' recipient is required.")
    normalized_paths = normalize_attachment_paths(attachment_paths)
    in_reply_to, references = _resolve_reply_headers(
        account_uid,
        reply_to_message_uid,
        reply_to_folder,
        db_fn=db_fn,
        cache_fn=cache_fn,
        caller_fn=caller_fn,
    )
    return to_norm, cc_norm, bcc_norm, normalized_paths, in_reply_to, references


async def move_email_logic(
    account_uid: str,
    message_uid: str,
    source_folder: str,
    dest_folder: str,
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Move an email between folders via the Evolution D-Bus bridge."""
    db_fn = db_path_getter or get_mail_db_path
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            src = resolve_folder_name(account_uid, source_folder, db_path_getter=db_fn)
            dst = resolve_folder_name(account_uid, dest_folder, db_path_getter=db_fn)
            success, message = caller_fn(
                "MoveMessage", "(ssss)", (account_uid, message_uid, src, dst)
            )
            if not success:
                raise BridgeCallError(f"Failed to move email: {message}")
            return ok_envelope(
                {
                    "status": "moved",
                    "uid": message_uid,
                    "source_folder": src,
                    "dest_folder": dst,
                    "message": str(message),
                }
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            logger.error("Move email failed for UID %s: %s", message_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def mark_as_read_logic(
    account_uid: str,
    message_uid: str,
    folder_name: str = "Inbox",
    read: bool = True,
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Mark an email read or unread via the Evolution D-Bus bridge."""
    db_fn = db_path_getter or get_mail_db_path
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            resolved = resolve_folder_name(account_uid, folder_name, db_path_getter=db_fn)
            success, message = caller_fn(
                "MarkAsRead", "(sssb)", (account_uid, message_uid, resolved, bool(read))
            )
            if not success:
                raise BridgeCallError(
                    f"Failed to mark message as {'read' if read else 'unread'}: {message}"
                )
            return ok_envelope(
                {
                    "status": "updated",
                    "uid": message_uid,
                    "folder": resolved,
                    "read": bool(read),
                    "message": str(message),
                }
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            logger.error("Mark as read failed for UID %s: %s", message_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def delete_message_logic(
    account_uid: str,
    message_uid: str,
    folder_name: str = "Inbox",
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Delete an email via the Evolution D-Bus bridge."""
    db_fn = db_path_getter or get_mail_db_path
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            resolved = resolve_folder_name(account_uid, folder_name, db_path_getter=db_fn)
            success, message = caller_fn(
                "DeleteMessage", "(sss)", (account_uid, message_uid, resolved)
            )
            if not success:
                raise BridgeCallError(f"Failed to delete message: {message}")
            return ok_envelope(
                {
                    "status": "deleted",
                    "uid": message_uid,
                    "folder": resolved,
                    "message": str(message),
                }
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            logger.error("Delete message failed for UID %s: %s", message_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def send_mail_logic(
    account_uid: str,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachment_paths: list[str] | None = None,
    reply_to_message_uid: str | None = None,
    reply_to_folder: str = "Inbox",
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    cache_reader: Callable[[str, str, str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Send an email via the Evolution D-Bus bridge."""
    db_fn = db_path_getter or get_mail_db_path
    cache_fn = cache_reader or read_cached_message
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            to_norm, cc_norm, bcc_norm, paths, in_reply_to, references = _prepare_outgoing_payload(
                account_uid=account_uid,
                to=to,
                cc=cc,
                bcc=bcc,
                attachment_paths=attachment_paths,
                reply_to_message_uid=reply_to_message_uid,
                reply_to_folder=reply_to_folder,
                require_recipient=True,
                db_fn=db_fn,
                cache_fn=cache_fn,
                caller_fn=caller_fn,
            )
            if paths or reply_to_message_uid or cc_norm or bcc_norm:
                success, message = caller_fn(
                    "SendMailWithAttachments",
                    "(ssssasssss)",
                    (
                        account_uid,
                        to_norm,
                        subject,
                        body,
                        paths,
                        in_reply_to,
                        references,
                        cc_norm,
                        bcc_norm,
                    ),
                )
                if (
                    not success
                    and "signature" in str(message).lower()
                    and not cc_norm
                    and not bcc_norm
                ):
                    success, message = caller_fn(
                        "SendMailWithAttachments",
                        "(ssssasss)",
                        (account_uid, to_norm, subject, body, paths, in_reply_to, references),
                    )
            else:
                success, message = caller_fn(
                    "SendMail", "(ssss)", (account_uid, to_norm, subject, body)
                )

            if not success:
                raise BridgeCallError(f"Failed to send mail: {message}")
            return ok_envelope(
                {"status": "sent", "message": str(message), "in_reply_to": in_reply_to}
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            if not isinstance(exc, ValidationError):
                logger.error("Send mail failed for account %s: %s", account_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def create_draft_logic(
    account_uid: str,
    to: str | list[str] = "",
    subject: str = "",
    body: str = "",
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachment_paths: list[str] | None = None,
    reply_to_message_uid: str | None = None,
    reply_to_folder: str = "Inbox",
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    cache_reader: Callable[[str, str, str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Save an email draft in the account's configured Drafts folder without sending."""
    db_fn = db_path_getter or get_mail_db_path
    cache_fn = cache_reader or read_cached_message
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            to_norm, cc_norm, bcc_norm, paths, in_reply_to, references = _prepare_outgoing_payload(
                account_uid=account_uid,
                to=to,
                cc=cc,
                bcc=bcc,
                attachment_paths=attachment_paths,
                reply_to_message_uid=reply_to_message_uid,
                reply_to_folder=reply_to_folder,
                require_recipient=False,
                db_fn=db_fn,
                cache_fn=cache_fn,
                caller_fn=caller_fn,
            )
            success, folder_or_error, draft_uid = caller_fn(
                "SaveDraft",
                "(ssssasssss)",
                (
                    account_uid,
                    to_norm,
                    subject,
                    body,
                    paths,
                    in_reply_to,
                    references,
                    cc_norm,
                    bcc_norm,
                ),
            )
            if not success:
                raise BridgeCallError(
                    f"Failed to save draft: {folder_or_error}",
                    hint="Ensure Evolution is running with the updated MCP automation bridge (`make install-bridge`).",
                )
            return ok_envelope(
                {
                    "status": "draft_saved",
                    "folder": str(folder_or_error),
                    "draft_uid": str(draft_uid),
                    "in_reply_to": in_reply_to,
                }
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            if not isinstance(exc, ValidationError):
                logger.error("Create draft failed for account %s: %s", account_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def open_composer_logic(
    account_uid: str,
    to: str | list[str] = "",
    subject: str = "",
    body: str = "",
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachment_paths: list[str] | None = None,
    reply_to_message_uid: str | None = None,
    reply_to_folder: str = "Inbox",
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    cache_reader: Callable[[str, str, str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
) -> str:
    """Open an interactive Evolution composer window pre-populated for human review."""
    db_fn = db_path_getter or get_mail_db_path
    cache_fn = cache_reader or read_cached_message
    caller_fn = bridge_caller or call_bridge_method

    def _logic() -> str:
        try:
            to_norm, cc_norm, bcc_norm, paths, in_reply_to, references = _prepare_outgoing_payload(
                account_uid=account_uid,
                to=to,
                cc=cc,
                bcc=bcc,
                attachment_paths=attachment_paths,
                reply_to_message_uid=reply_to_message_uid,
                reply_to_folder=reply_to_folder,
                require_recipient=False,
                db_fn=db_fn,
                cache_fn=cache_fn,
                caller_fn=caller_fn,
            )
            success, message = caller_fn(
                "OpenComposer",
                "(ssssasssss)",
                (
                    account_uid,
                    to_norm,
                    subject,
                    body,
                    paths,
                    in_reply_to,
                    references,
                    cc_norm,
                    bcc_norm,
                ),
            )
            if not success:
                raise BridgeCallError(
                    f"Failed to open Evolution composer: {message}",
                    hint="Ensure Evolution GUI is running with the updated MCP automation bridge (`make install-bridge`).",
                )
            return ok_envelope(
                {
                    "status": "composer_opened",
                    "message": str(message),
                    "in_reply_to": in_reply_to,
                }
            )
        except (EdsMcpError, ValueError, ConnectionError, OSError, RuntimeError) as exc:
            if not isinstance(exc, ValidationError):
                logger.error("Open composer failed for account %s: %s", account_uid, exc)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)
