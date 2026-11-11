"""Thin public facade and read entrypoints for EDS MCP mail operations."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from typing import Any

from . import (
    BridgeCallError,
    CacheMissError,
    EdsClientError,
    EdsMcpError,
    ResourceNotFoundError,
    ValidationError,
    compact_json,
    error_from_exception,
    ok_envelope,
    paginated_envelope,
    strip_empty,
)
from . import mail_actions as _actions
from . import mail_bridge as _bridge
from . import mail_cache as _cache
from . import mail_db as _db
from . import mail_threads as _threads
from .env import setup_environment

setup_environment()

from gi.repository import EDataServer, Gio, GLib  # noqa: E402

logger = logging.getLogger(__name__)

BRIDGE_CALL_TIMEOUT_MS = _bridge.BRIDGE_CALL_TIMEOUT_MS
BRIDGE_READ_FALLBACK_ENV = _bridge.BRIDGE_READ_FALLBACK_ENV
get_mail_db_path = _db.get_mail_db_path
resolve_folder_name = _db.resolve_folder_name
read_cached_message = _cache.read_cached_message
normalize_recipients = _cache.normalize_recipients


def get_dbus_proxy() -> Gio.DBusProxy:
    """Acquire D-Bus proxy for Evolution MCP automation bridge."""
    return _bridge.get_dbus_proxy()


def is_bridge_reachable() -> bool:
    """Return True if Evolution's automation bridge is active on session D-Bus."""
    return _bridge.is_bridge_reachable(proxy_getter=get_dbus_proxy)


def bridge_read_fallback_enabled() -> bool:
    """Return True if uncached reads may fall back to Evolution's D-Bus bridge."""
    return _bridge.bridge_read_fallback_enabled(proxy_getter=get_dbus_proxy)


def call_bridge_method(
    method_name: str, variant_signature: str, parameters: tuple[Any, ...]
) -> Any:
    """Call method on Evolution automation bridge via configured proxy."""
    return _bridge.call_bridge_method(
        method_name, variant_signature, parameters, proxy_getter=get_dbus_proxy
    )


def _require_db_path(account_uid: str) -> str:
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        raise ResourceNotFoundError(f"Could not find mail database for account '{account_uid}'.")
    return db_path


async def _run_mail_op(fn: Callable[[], str]) -> str:
    def _wrapped() -> str:
        try:
            return fn()
        except (
            EdsMcpError,
            ValueError,
            json.JSONDecodeError,
            sqlite3.Error,
            ConnectionError,
            OSError,
            RuntimeError,
            GLib.Error,
        ) as exc:
            return error_from_exception(exc)

    return await asyncio.to_thread(_wrapped)


async def list_mail_accounts_logic() -> str:
    """List all configured and enabled Evolution email accounts."""

    def _logic() -> str:
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            accounts: list[dict[str, Any]] = []
            for source in registry.list_sources(EDataServer.SOURCE_EXTENSION_MAIL_ACCOUNT):
                if source.get_enabled():
                    p_uid = source.get_parent()
                    p_src = registry.ref_source(p_uid) if p_uid else None
                    accounts.append(
                        strip_empty(
                            {
                                "uid": source.get_uid(),
                                "name": source.get_display_name(),
                                "parent_uid": p_uid,
                                "parent_name": p_src.get_display_name() if p_src else None,
                            }
                        )
                    )
            return paginated_envelope(accounts, total=len(accounts), offset=0)
        except (GLib.Error, RuntimeError) as exc:
            logger.exception("Failed to list mail accounts")
            raise EdsClientError(str(exc)) from exc

    return await _run_mail_op(_logic)


async def list_mail_folders_logic(account_uid: str) -> str:
    """List all indexed mail folders for an account."""

    def _logic() -> str:
        with _db.open_readonly_db(_require_db_path(account_uid)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT folder_name, unread_count, visible_count FROM folders")
            folders = [
                {"name": str(r[0]), "unread": int(r[1] or 0), "total": int(r[2] or 0)}
                for r in cur.fetchall()
            ]
        return paginated_envelope(folders, total=len(folders), offset=0)

    return await _run_mail_op(_logic)


async def get_emails_logic(
    account_uid: str,
    folder_name: str = "Inbox",
    limit: int = 10,
    offset: int = 0,
    format: str = "json",
) -> str:
    """Fetch recent emails from a canonical folder as compact JSON or markdown summary."""

    def _logic() -> str:
        if limit < 1 or limit > 200 or offset < 0:
            raise ValidationError("Invalid limit (1-200) or offset (>= 0).")
        db_path = _require_db_path(account_uid)
        resolved = resolve_folder_name(
            account_uid, folder_name, db_path_getter=get_mail_db_path, strict=True
        )
        with _db.open_readonly_db(db_path) as conn:
            emails, total = _db.fetch_folder_page(conn, resolved, limit, offset)

        if format == "summary":
            if not emails:
                return f"No emails found in {resolved}."
            output = [f"## Recent emails in {resolved}"]
            for item in emails:
                sender = item["from"].split("<")[0].strip() or item["from"]
                line = f"* **{item['subject']}** (from: {sender}, {item['date']})"
                if p := item.get("preview"):
                    line += f"\n  _{p[:100] + '...' if len(p) > 100 else p}_"
                output.append(line)
            return "\n".join(output)
        return paginated_envelope(
            emails, total=total, offset=offset, extra_meta={"folder": resolved}
        )

    return await _run_mail_op(_logic)


async def search_emails_logic(
    account_uid: str,
    query: str = "",
    folder_name: str | None = None,
    limit: int = 25,
    offset: int = 0,
    *,
    from_query: str | None = None,
    to_query: str | None = None,
    since: str | None = None,
    until: str | None = None,
    unread_only: bool = False,
    dedupe_threads: bool = False,
    search_body: bool = False,
    max_scanned: int = 500,
) -> str:
    """Search emails with Unicode case-folding, recipient/date filters, and opt-in body scan."""

    def _logic() -> str:
        q_clean = (query or "").strip()
        from_clean, to_clean = (from_query or "").strip(), (to_query or "").strip()
        if not any([q_clean, from_clean, to_clean, since, until, unread_only]):
            raise ValidationError("Provide 'query' or at least one filter.")
        if limit < 1 or limit > 200 or offset < 0 or max_scanned < 1 or max_scanned > 5000:
            raise ValidationError("Invalid pagination or max_scanned bounds.")

        since_ts = _db.parse_iso_timestamp(since, end_of_day=False) if since else None
        until_ts = _db.parse_iso_timestamp(until, end_of_day=True) if until else None
        if since_ts is not None and until_ts is not None and since_ts > until_ts:
            raise ValidationError("'since' must be earlier than or equal to 'until'.")

        db_path = _require_db_path(account_uid)
        if folder_name:
            target_folders = [
                resolve_folder_name(
                    account_uid, folder_name, db_path_getter=get_mail_db_path, strict=True
                )
            ]
        else:
            with _db.open_readonly_db(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT folder_name FROM folders")
                target_folders = [
                    str(r[0])
                    for r in cur.fetchall()
                    if r and r[0] and not _db.is_trash_or_junk_folder(str(r[0]))
                ]

        def _match_body(uid: str, f_name: str, needle_cf: str) -> tuple[bool, bool]:
            raw = read_cached_message(account_uid, uid, f_name)
            if raw is None:
                return False, True
            return needle_cf in _cache.extract_body_text(raw, strip_quoted=False).casefold(), False

        with _db.open_readonly_db(db_path) as conn:
            ordered, scanned_count, cache_misses = _db.execute_folder_search(
                conn,
                target_folders,
                q_clean=q_clean,
                from_clean=from_clean,
                to_clean=to_clean,
                since_ts=since_ts,
                until_ts=until_ts,
                unread_only=unread_only,
                search_body=search_body,
                max_scanned=max_scanned,
                limit=limit,
                offset=offset,
                body_matcher=_match_body,
            )

        if dedupe_threads:
            deduped: list[dict[str, Any]] = []
            by_subj: dict[str, dict[str, Any]] = {}
            for item in ordered:
                base = _cache.normalize_subject(item.get("subject")).casefold()
                key = base or f"uid:{item.get('folder')}:{item['uid']}"
                if key not in by_subj:
                    entry = {**item, "thread_count": 1}
                    by_subj[key] = entry
                    deduped.append(entry)
                else:
                    by_subj[key]["thread_count"] = int(by_subj[key]["thread_count"]) + 1
            ordered = deduped

        extra_meta: dict[str, Any] = {}
        if search_body:
            extra_meta.update({"scanned_count": scanned_count, "cache_misses": cache_misses})
        if folder_name and target_folders:
            extra_meta["folder"] = target_folders[0]
        return paginated_envelope(
            ordered[offset : offset + limit],
            total=len(ordered),
            offset=offset,
            extra_meta=extra_meta or None,
        )

    return await _run_mail_op(_logic)


async def get_email_body_logic(
    account_uid: str,
    message_uid: str,
    folder_name: str = "Inbox",
    max_chars: int = _cache.MAX_BODY_LENGTH,
) -> str:
    """Retrieve parsed email headers, body, source, and truncation metadata."""

    def _logic() -> str:
        if max_chars < 100:
            raise ValidationError("'max_chars' must be >= 100.")
        resolved = resolve_folder_name(account_uid, folder_name, db_path_getter=get_mail_db_path)
        raw_content, source = read_cached_message(account_uid, message_uid, resolved), "cache"
        if raw_content is None:
            if not bridge_read_fallback_enabled():
                raise CacheMissError(
                    f"Message UID '{message_uid}' not found in local Evolution cache for '{resolved}'."
                )
            ok, dbus_content = call_bridge_method(
                "GetMessage", "(sss)", (account_uid, message_uid, resolved)
            )
            if not ok or not dbus_content:
                raise BridgeCallError(
                    f"Message UID '{message_uid}' not in local cache and bridge fetch failed: {dbus_content}"
                )
            raw_content, source = str(dbus_content), "bridge"

        parsed = _cache.parse_message_envelope(raw_content, max_chars=max_chars, strip_quoted=False)
        payload = strip_empty(
            {
                "uid": message_uid,
                "folder": resolved,
                "from": parsed["from"],
                "to": parsed["to"],
                "cc": parsed["cc"],
                "subject": parsed["subject"],
                "date": parsed["date"],
                "message_id": parsed["message_id"],
                "in_reply_to": parsed["in_reply_to"],
                "body": parsed["body"],
                "source": source,
            }
        )
        payload["truncated"] = bool(parsed["truncated"])
        return compact_json(payload)

    return await _run_mail_op(_logic)


async def list_attachments_logic(
    account_uid: str, message_uid: str, folder_name: str = "Inbox"
) -> str:
    """List attachments on an email via local cache or Evolution bridge fallback."""

    def _logic() -> str:
        resolved = resolve_folder_name(account_uid, folder_name, db_path_getter=get_mail_db_path)
        raw_content = read_cached_message(account_uid, message_uid, resolved)
        if raw_content is not None:
            atts = _cache.list_attachments_from_message(raw_content)
            return paginated_envelope(
                atts, total=len(atts), offset=0, extra_meta={"source": "cache", "folder": resolved}
            )
        if not bridge_read_fallback_enabled():
            raise CacheMissError(f"Message UID '{message_uid}' not in local Evolution cache.")
        ok, att_json = call_bridge_method(
            "ListAttachments", "(sss)", (account_uid, message_uid, resolved)
        )
        if not ok:
            raise BridgeCallError(f"ListAttachments failed: {att_json}")
        parsed_atts = json.loads(att_json) if att_json else []
        atts_list = parsed_atts if isinstance(parsed_atts, list) else []
        return paginated_envelope(
            atts_list,
            total=len(atts_list),
            offset=0,
            extra_meta={"source": "bridge", "folder": resolved},
        )

    return await _run_mail_op(_logic)


async def save_attachment_logic(
    account_uid: str, message_uid: str, folder_name: str, attachment_name: str
) -> str:
    """Save an attachment to a temporary file and return its local path."""

    def _logic() -> str:
        safe_name = os.path.basename(attachment_name)
        if not safe_name:
            raise ValidationError("Attachment name is invalid.")
        resolved = resolve_folder_name(account_uid, folder_name, db_path_getter=get_mail_db_path)
        raw_content = read_cached_message(account_uid, message_uid, resolved)
        if raw_content is not None:
            dest = _cache.save_attachment_from_message(raw_content, attachment_name)
            if not dest:
                raise ResourceNotFoundError(
                    f"Attachment '{safe_name}' not found on message '{message_uid}'."
                )
            source = "cache"
        else:
            if not bridge_read_fallback_enabled():
                raise CacheMissError(f"Message UID '{message_uid}' not in local Evolution cache.")
            temp_dir = tempfile.mkdtemp(prefix="eds_mcp_attachment_")
            dest = os.path.join(temp_dir, safe_name)
            try:
                ok, msg = call_bridge_method(
                    "SaveAttachment",
                    "(sssss)",
                    (account_uid, message_uid, resolved, attachment_name, dest),
                )
                if not ok:
                    raise BridgeCallError(f"SaveAttachment failed: {msg}")
            except BaseException:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise
            source = "bridge"
        return ok_envelope(
            {
                "uid": message_uid,
                "folder": resolved,
                "filename": safe_name,
                "path": dest,
                "source": source,
            }
        )

    return await _run_mail_op(_logic)


def _folder_deps() -> dict[str, Any]:
    return {"db_path_getter": get_mail_db_path, "bridge_caller": call_bridge_method}


def _action_deps() -> dict[str, Any]:
    return {**_folder_deps(), "cache_reader": read_cached_message}


async def get_email_thread_logic(
    account_uid: str,
    message_uid: str | None = None,
    folder_name: str = "Inbox",
    **kwargs: Any,
) -> str:
    """Reconstruct chronological cross-folder email thread with quote stripping."""
    deps = {**_action_deps(), "bridge_fallback_fn": bridge_read_fallback_enabled, **kwargs}
    return await _threads.get_email_thread_logic(account_uid, message_uid, folder_name, **deps)


async def move_email_logic(
    account_uid: str, message_uid: str, source_folder: str, dest_folder: str
) -> str:
    return await _actions.move_email_logic(
        account_uid, message_uid, source_folder, dest_folder, **_folder_deps()
    )


async def mark_as_read_logic(
    account_uid: str, message_uid: str, folder_name: str = "Inbox", read: bool = True
) -> str:
    return await _actions.mark_as_read_logic(
        account_uid, message_uid, folder_name, read, **_folder_deps()
    )


async def delete_message_logic(
    account_uid: str, message_uid: str, folder_name: str = "Inbox"
) -> str:
    return await _actions.delete_message_logic(
        account_uid, message_uid, folder_name, **_folder_deps()
    )


async def send_mail_logic(
    account_uid: str, to: str | list[str], subject: str, body: str, **kwargs: Any
) -> str:
    return await _actions.send_mail_logic(
        account_uid, to, subject, body, **{**_action_deps(), **kwargs}
    )


async def create_draft_logic(
    account_uid: str, to: str | list[str] = "", subject: str = "", body: str = "", **kwargs: Any
) -> str:
    return await _actions.create_draft_logic(
        account_uid, to, subject, body, **{**_action_deps(), **kwargs}
    )


async def open_composer_logic(
    account_uid: str, to: str | list[str] = "", subject: str = "", body: str = "", **kwargs: Any
) -> str:
    return await _actions.open_composer_logic(
        account_uid, to, subject, body, **{**_action_deps(), **kwargs}
    )
