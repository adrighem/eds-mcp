"""Read-only SQLite access, canonical folder resolution, and query builders for Evolution mail."""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import urllib.parse
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from . import DatabaseError, ResourceNotFoundError, ValidationError

logger = logging.getLogger(__name__)

_TRASH_JUNK_NAMES = frozenset(
    {
        "trash",
        "deleted items",
        "verwijderde items",
        "papierkorb",
        "slettede elementer",
        "junk",
        "junk email",
        "junk-e-mail",
        "ongewenste e-mail",
        "spam",
    }
)

_SUMMARY_COLUMNS = (
    "uid",
    "subject",
    "mail_from",
    "mail_to",
    "mail_cc",
    "dsent",
    "dreceived",
    "preview",
    "read",
    "flags",
    "attachment",
)


def validate_safe_identifier(value: str, field_name: str) -> str:
    """Reject empty values, NUL bytes, and parent-directory traversal segments."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"'{field_name}' must be a non-empty string.")
    if "\x00" in value:
        raise ValidationError(f"'{field_name}' contains invalid NUL characters.")
    if any(seg == ".." for seg in value.replace("\\", "/").split("/")):
        raise ValidationError(f"'{field_name}' must not contain '..' path traversal.")
    return value.strip()


def quote_sql_ident(identifier: str) -> str:
    """Safely double-quote a SQLite table or column identifier."""
    if "\x00" in identifier:
        raise ValidationError("SQLite identifier contains invalid NUL byte.")
    return '"' + identifier.replace('"', '""') + '"'


def get_mail_roots(account_uid: str) -> list[str]:
    """Return candidate Evolution mail directories for an account."""
    safe_uid = validate_safe_identifier(account_uid, "account_uid")
    if "/" in safe_uid:
        raise ValidationError("'account_uid' must not contain path separators.")
    return [
        os.path.expanduser(f"~/.cache/evolution/mail/{safe_uid}"),
        os.path.expanduser(f"~/.local/share/evolution/mail/{safe_uid}"),
    ]


def get_mail_db_path(account_uid: str) -> str | None:
    """Resolve SQLite folders.db path for a given Evolution mail account."""
    for root in get_mail_roots(account_uid):
        candidate = os.path.join(root, "folders.db")
        if os.path.exists(candidate):
            return candidate
    return None


def _casefold_contains(haystack: str | None, needle: str | None) -> int:
    """Unicode case-insensitive substring predicate for SQLite queries."""
    if not haystack or not needle:
        return 0
    return 1 if str(needle).casefold() in str(haystack).casefold() else 0


@contextlib.contextmanager
def open_readonly_db(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open Evolution's folders.db in read-only URI mode without locking writers."""
    quoted = urllib.parse.quote(os.path.abspath(db_path), safe="/")
    uri = f"file:{quoted}?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        except TypeError:
            conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        if hasattr(conn, "create_function"):
            try:
                conn.create_function("casefold_contains", 2, _casefold_contains, deterministic=True)
            except TypeError:
                conn.create_function("casefold_contains", 2, _casefold_contains)
        yield conn
    except sqlite3.Error as exc:
        raise DatabaseError(f"SQLite error reading Evolution index: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def list_existing_tables(conn: sqlite3.Connection) -> set[str]:
    """Return all existing table names in the SQLite database."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {str(row[0]) for row in cur.fetchall() if row and row[0]}


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names defined on a folder table."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({quote_sql_ident(table_name)})")
    cols: set[str] = set()
    for row in cur.fetchall():
        if isinstance(row, sqlite3.Row):
            cols.add(str(row["name"]))
        elif isinstance(row, (tuple, list)) and len(row) > 1:
            cols.add(str(row[1]))
    return cols


def _resolve_folder_on_disk(base_folders_dir: str, requested_folder: str) -> str | None:
    """Case-insensitively resolve a folder path on disk, including Maildir subfolders."""
    parts = [p for p in requested_folder.split("/") if p]
    if not parts or not os.path.isdir(base_folders_dir):
        return None
    current_dir = base_folders_dir
    resolved_parts: list[str] = []
    for idx, part in enumerate(parts):
        search_dir = current_dir
        if idx > 0 and not os.path.isdir(os.path.join(current_dir, part)):
            sub_candidate = os.path.join(current_dir, "subfolders")
            if os.path.isdir(sub_candidate):
                search_dir = sub_candidate
        try:
            entries = os.listdir(search_dir)
        except OSError:
            return None
        exact = next((e for e in entries if e == part), None)
        folded = exact or next((e for e in entries if e.casefold() == part.casefold()), None)
        if not folded or not os.path.isdir(os.path.join(search_dir, folded)):
            return None
        resolved_parts.append(folded)
        current_dir = os.path.join(search_dir, folded)
    return "/".join(resolved_parts)


def resolve_folder_name(
    account_uid: str,
    requested_folder: str = "Inbox",
    *,
    db_path_getter: Callable[[str], str | None] | None = None,
    strict: bool = False,
) -> str:
    """Resolve canonical folder name case-insensitively via folders.db then filesystem."""
    effective = (requested_folder or "Inbox").strip() or "Inbox"
    validate_safe_identifier(effective, "folder_name")
    getter = db_path_getter or get_mail_db_path

    db_path = getter(account_uid)
    if db_path:
        try:
            with open_readonly_db(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT folder_name FROM folders")
                names = [str(r[0]) for r in cur.fetchall() if r and r[0]]
            for name in names:
                if name == effective:
                    return name
            target_cf = effective.casefold()
            for name in names:
                if name.casefold() == target_cf:
                    return name
            if strict:
                raise ResourceNotFoundError(
                    f"Folder '{effective}' not found in account '{account_uid}'.",
                    hint="List available folders via eds://mail/{account_uid}/folders.",
                )
        except DatabaseError as exc:
            logger.debug("Folder DB lookup skipped for %s: %s", account_uid, exc)

    for root in get_mail_roots(account_uid):
        matched = _resolve_folder_on_disk(os.path.join(root, "folders"), effective)
        if matched:
            return matched

    if strict:
        raise ResourceNotFoundError(f"Folder '{effective}' not found in account '{account_uid}'.")
    return effective


def is_trash_or_junk_folder(folder_name: str) -> bool:
    """Return True if folder appears to be Trash/Deleted Items or Junk/Spam."""
    return folder_name.rsplit("/", 1)[-1].strip().casefold() in _TRASH_JUNK_NAMES


def parse_iso_timestamp(value: str, *, end_of_day: bool = False) -> int:
    """Parse YYYY-MM-DD or ISO-8601 datetime string into Unix epoch seconds."""
    raw = value.strip()
    if not raw:
        raise ValidationError("Date filter cannot be empty.")
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            dt_date = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError as exc:
            raise ValidationError(
                f"Invalid date '{value}'. Expected YYYY-MM-DD or ISO-8601 datetime."
            ) from exc
        if end_of_day:
            dt_date = dt_date.replace(hour=23, minute=59, second=59)
        return int(dt_date.timestamp())

    iso_norm = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(iso_norm)
    except ValueError as exc:
        raise ValidationError(
            f"Invalid datetime '{value}'. Expected YYYY-MM-DD or ISO-8601 datetime."
        ) from exc
    return int(dt.timestamp()) if dt.tzinfo is None else int(dt.astimezone(UTC).timestamp())


def format_timestamp(epoch: Any) -> str:
    """Format Camel epoch timestamp into compact local YYYY-MM-DD HH:MM:SS string."""
    if epoch is None:
        return ""
    try:
        ts = int(epoch)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts > 0 else ""
    except (ValueError, TypeError, OSError, OverflowError):
        return str(epoch)


def row_to_email_summary(
    row: sqlite3.Row | tuple[Any, ...],
    *,
    folder: str | None = None,
) -> dict[str, Any]:
    """Project a CamelMIRecord SQLite row into a minimal MCP email summary dict."""
    if isinstance(row, sqlite3.Row):
        keys = set(row.keys())
        uid = row["uid"]
        subject = row["subject"] if "subject" in keys else ""
        mail_from = row["mail_from"] if "mail_from" in keys else ""
        mail_to = row["mail_to"] if "mail_to" in keys else None
        mail_cc = row["mail_cc"] if "mail_cc" in keys else None
        dreceived = row["dreceived"] if "dreceived" in keys else None
        dsent = row["dsent"] if "dsent" in keys else None
        preview = row["preview"] if "preview" in keys else None
        read_flag = row["read"] if "read" in keys else None
        flags_val = row["flags"] if "flags" in keys else None
        attachment_flag = row["attachment"] if "attachment" in keys else None
    else:
        uid = row[0]
        subject = row[1] if len(row) > 1 else ""
        mail_from = row[2] if len(row) > 2 else ""
        dreceived = row[3] if len(row) > 3 else None
        preview = row[4] if len(row) > 4 else None
        mail_to = row[5] if len(row) > 5 else None
        mail_cc = row[6] if len(row) > 6 else None
        dsent = read_flag = flags_val = attachment_flag = None

    item: dict[str, Any] = {
        "uid": str(uid),
        "subject": str(subject or ""),
        "from": str(mail_from or ""),
        "date": format_timestamp(dreceived if dreceived else dsent),
    }
    if folder:
        item["folder"] = folder
    if mail_to:
        item["to"] = str(mail_to)
    if mail_cc:
        item["cc"] = str(mail_cc)
    if read_flag is not None:
        if int(read_flag) == 0:
            item["unread"] = True
    elif flags_val is not None and (int(flags_val) & 16) == 0:
        item["unread"] = True
    if attachment_flag is not None and int(attachment_flag) != 0:
        item["has_attachments"] = True
    if isinstance(preview, str) and preview.strip():
        item["preview"] = preview.strip()
    return item


def fetch_folder_page(
    conn: sqlite3.Connection,
    folder_name: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Query paginated email summaries and total visible count for a folder table."""
    cols = get_table_columns(conn, folder_name)
    q_table = quote_sql_ident(folder_name)
    where_sql = "WHERE COALESCE(deleted, 0) = 0" if "deleted" in cols else ""
    cur = conn.cursor()
    total = 0
    if cols:
        cur.execute(f"SELECT COUNT(*) FROM {q_table} {where_sql}")
        cnt_row = cur.fetchone()
        total = int(cnt_row[0]) if cnt_row and cnt_row[0] is not None else 0
        sel = ", ".join(
            quote_sql_ident(c) if c in cols else f"NULL AS {quote_sql_ident(c)}"
            for c in _SUMMARY_COLUMNS
        )
        cur.execute(
            f"SELECT {sel} FROM {q_table} {where_sql} ORDER BY dreceived DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    else:
        cur.execute(
            f"SELECT uid, subject, mail_from, dreceived, preview "
            f"FROM {q_table} ORDER BY dreceived DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    emails = [row_to_email_summary(r) for r in cur.fetchall()]
    return emails, max(total, offset + len(emails))


def execute_folder_search(
    conn: sqlite3.Connection,
    target_folders: list[str],
    *,
    q_clean: str,
    from_clean: str,
    to_clean: str,
    since_ts: int | None,
    until_ts: int | None,
    unread_only: bool,
    search_body: bool,
    max_scanned: int,
    limit: int,
    offset: int,
    body_matcher: Callable[[str, str, str], tuple[bool, bool]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Execute Unicode-aware SQLite search across target folders with optional body scan."""
    existing_tables = list_existing_tables(conn)
    cur = conn.cursor()
    matches: list[tuple[int, dict[str, Any]]] = []
    scanned_count = 0
    cache_misses = 0
    q_cf = q_clean.casefold()

    for folder in target_folders:
        if folder not in existing_tables:
            continue
        cols = get_table_columns(conn, folder)
        clauses: list[str] = []
        params: list[Any] = []
        if "deleted" in cols:
            clauses.append("COALESCE(deleted, 0) = 0")
        if unread_only:
            if "read" in cols:
                clauses.append("COALESCE(read, 0) = 0")
            elif "flags" in cols:
                clauses.append("(COALESCE(flags, 0) & 16) = 0")
        if since_ts is not None and "dreceived" in cols:
            clauses.append("dreceived >= ?")
            params.append(since_ts)
        if until_ts is not None and "dreceived" in cols:
            clauses.append("dreceived <= ?")
            params.append(until_ts)
        if from_clean and "mail_from" in cols:
            clauses.append("casefold_contains(mail_from, ?)")
            params.append(from_clean)
        if to_clean:
            to_parts = [f"casefold_contains({c}, ?)" for c in ("mail_to", "mail_cc") if c in cols]
            if to_parts:
                clauses.append("(" + " OR ".join(to_parts) + ")")
                params.extend([to_clean] * len(to_parts))

        text_cols = [
            c for c in ("subject", "mail_from", "mail_to", "mail_cc", "preview") if c in cols
        ]
        if q_clean and not search_body and text_cols:
            clauses.append("(" + " OR ".join(f"casefold_contains({c}, ?)" for c in text_cols) + ")")
            params.extend([q_clean] * len(text_cols))

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sel = ", ".join(
            quote_sql_ident(c) if c in cols else f"NULL AS {quote_sql_ident(c)}"
            for c in _SUMMARY_COLUMNS
        )
        per_folder_cap = (
            max(1, max_scanned - scanned_count)
            if (search_body and q_clean)
            else max(offset + limit, 200)
        )
        cur.execute(
            f"SELECT {sel} FROM {quote_sql_ident(folder)} {where_sql} "
            f"ORDER BY dreceived DESC LIMIT ?",
            (*params, per_folder_cap),
        )
        for row in cur.fetchall():
            drec = int(row["dreceived"] or 0) if row["dreceived"] is not None else 0
            summary = row_to_email_summary(row, folder=folder)
            if q_clean and search_body:
                header_hit = any(q_cf in str(row[c] or "").casefold() for c in text_cols)
                if not header_hit:
                    if scanned_count >= max_scanned:
                        continue
                    scanned_count += 1
                    hit, missed = body_matcher(summary["uid"], folder, q_cf)
                    if missed:
                        cache_misses += 1
                    if not hit:
                        continue
            matches.append((drec, summary))
        if search_body and q_clean and scanned_count >= max_scanned:
            break

    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in matches], scanned_count, cache_misses
