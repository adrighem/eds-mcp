"""Cross-folder RFC 5322 email thread resolution and deduplicated assembly."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import (
    BridgeCallError,
    BridgeUnavailableError,
    EdsMcpError,
    ResourceNotFoundError,
    ValidationError,
    error_from_exception,
    paginated_envelope,
)
from .mail_bridge import bridge_read_fallback_enabled, call_bridge_method
from .mail_cache import (
    extract_email_addresses,
    normalize_subject,
    parse_message_envelope,
    read_cached_message,
)
from .mail_db import (
    format_timestamp,
    get_mail_db_path,
    get_table_columns,
    is_trash_or_junk_folder,
    list_existing_tables,
    open_readonly_db,
    quote_sql_ident,
    resolve_folder_name,
)

logger = logging.getLogger(__name__)

_SENT_FOLDER_NAMES = frozenset(
    {
        "sent",
        "sent items",
        "sent messages",
        "verzonden",
        "verzonden items",
        "gesendet",
        "gesendete elemente",
        "sendt",
        "sendte elementer",
    }
)
_THREAD_COLS = (
    "uid",
    "subject",
    "mail_from",
    "mail_to",
    "mail_cc",
    "dsent",
    "dreceived",
    "preview",
    "part",
    "deleted",
)


def _is_sent_folder(folder_name: str) -> bool:
    return folder_name.rsplit("/", 1)[-1].strip().casefold() in _SENT_FOLDER_NAMES


@dataclass
class _Candidate:
    uid: str
    folder: str
    subject: str = ""
    base_subject: str = ""
    mail_from: str = ""
    mail_to: str = ""
    mail_cc: str = ""
    dsent: int = 0
    dreceived: int = 0
    preview: str = ""
    part: str = ""
    raw_content: str | None = None
    source: str = "index_preview"
    message_id: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    also_in: list[str] = field(default_factory=list)

    @property
    def sort_ts(self) -> int:
        return self.dsent if self.dsent > 0 else self.dreceived

    @property
    def participants(self) -> set[str]:
        return extract_email_addresses(self.mail_from, self.mail_to, self.mail_cc)


def _row_to_candidate(row: sqlite3.Row | tuple[Any, ...], folder: str) -> _Candidate:
    if isinstance(row, sqlite3.Row):
        keys = set(row.keys())
        subj = str(row["subject"] or "") if "subject" in keys else ""
        dsent = int(row["dsent"] or 0) if "dsent" in keys and row["dsent"] is not None else 0
        drec = (
            int(row["dreceived"] or 0)
            if "dreceived" in keys and row["dreceived"] is not None
            else 0
        )
        return _Candidate(
            uid=str(row["uid"]),
            folder=folder,
            subject=subj,
            base_subject=normalize_subject(subj),
            mail_from=str(row["mail_from"] or "") if "mail_from" in keys else "",
            mail_to=str(row["mail_to"] or "") if "mail_to" in keys else "",
            mail_cc=str(row["mail_cc"] or "") if "mail_cc" in keys else "",
            dsent=dsent,
            dreceived=drec,
            preview=str(row["preview"] or "").strip() if "preview" in keys else "",
            part=str(row["part"] or "").strip() if "part" in keys else "",
        )
    subj = str(row[1] or "") if len(row) > 1 else ""
    return _Candidate(
        uid=str(row[0]),
        folder=folder,
        subject=subj,
        base_subject=normalize_subject(subj),
        mail_from=str(row[2] or "") if len(row) > 2 else "",
        dreceived=int(row[3] or 0) if len(row) > 3 and row[3] is not None else 0,
        preview=str(row[4] or "").strip() if len(row) > 4 else "",
        mail_to=str(row[5] or "") if len(row) > 5 else "",
        mail_cc=str(row[6] or "") if len(row) > 6 else "",
    )


def _enrich_from_raw(cand: _Candidate, raw: str, source: str, max_chars: int) -> None:
    cand.raw_content = raw
    cand.source = source
    parsed = parse_message_envelope(raw, max_chars=max_chars, strip_quoted=False)
    cand.message_id = str(parsed.get("message_id") or "").strip()
    cand.in_reply_to = str(parsed.get("in_reply_to") or "").strip()
    cand.references = [r.strip() for r in parsed.get("references", []) if r and r.strip()]
    for hdr, attr in (("from", "mail_from"), ("to", "mail_to"), ("cc", "mail_cc")):
        if parsed.get(hdr):
            setattr(cand, attr, str(parsed[hdr]))
    if parsed.get("subject"):
        cand.subject = str(parsed["subject"])
        cand.base_subject = normalize_subject(cand.subject)


def _select_clause(cols: set[str]) -> str:
    return ", ".join(
        quote_sql_ident(c) if c in cols else f"NULL AS {quote_sql_ident(c)}" for c in _THREAD_COLS
    )


def _try_fetch_bridge(
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any],
    bridge_fallback_fn: Callable[[], bool],
    account_uid: str,
    msg_uid: str,
    folder: str,
) -> str | None:
    if not bridge_fallback_fn():
        return None
    try:
        ok, fetched = bridge_caller("GetMessage", "(sss)", (account_uid, msg_uid, folder))
        return str(fetched) if ok and fetched else None
    except (BridgeUnavailableError, BridgeCallError):
        return None


def _load_seed_and_candidates(
    conn: sqlite3.Connection,
    *,
    account_uid: str,
    seed_folder: str,
    message_uid: str | None,
    message_id: str | None,
    window_days: int,
    max_chars_per_message: int,
    cache_reader: Callable[[str, str, str], str | None],
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any],
    bridge_fallback_fn: Callable[[], bool],
) -> tuple[_Candidate, list[_Candidate]]:
    cur = conn.cursor()
    cur.execute("SELECT folder_name FROM folders")
    all_folders = [str(r[0]) for r in cur.fetchall() if r and r[0]]
    existing_tables = list_existing_tables(conn)

    seed: _Candidate | None = None
    target_mid = (message_id or "").strip()

    if message_uid:
        if seed_folder in existing_tables:
            cols = get_table_columns(conn, seed_folder)
            cur.execute(
                f"SELECT {_select_clause(cols)} FROM {quote_sql_ident(seed_folder)} WHERE uid = ?",
                (message_uid,),
            )
            if row := cur.fetchone():
                seed = _row_to_candidate(row, seed_folder)
        if seed is None:
            raw = cache_reader(account_uid, message_uid, seed_folder)
            src = "cache"
            if raw is None:
                raw = _try_fetch_bridge(
                    bridge_caller, bridge_fallback_fn, account_uid, message_uid, seed_folder
                )
                src = "bridge"
            if raw is not None:
                seed = _Candidate(uid=message_uid, folder=seed_folder)
                _enrich_from_raw(seed, raw, src, max_chars_per_message)
    elif target_mid:
        for folder in all_folders:
            if folder not in existing_tables or is_trash_or_junk_folder(folder):
                continue
            cols = get_table_columns(conn, folder)
            where_del = "WHERE COALESCE(deleted, 0) = 0" if "deleted" in cols else ""
            cur.execute(
                f"SELECT {_select_clause(cols)} FROM {quote_sql_ident(folder)} {where_del} "
                f"ORDER BY dreceived DESC LIMIT 500"
            )
            for row in cur.fetchall():
                cand = _row_to_candidate(row, folder)
                if raw := cache_reader(account_uid, cand.uid, folder):
                    _enrich_from_raw(cand, raw, "cache", max_chars_per_message)
                    if cand.message_id == target_mid:
                        seed = cand
                        break
            if seed is not None:
                break

    if seed is None:
        raise ResourceNotFoundError(
            "Seed message for thread not found.",
            hint="Verify account_uid, folder_name, and message_uid or message_id.",
        )

    if seed.raw_content is None:
        if raw := cache_reader(account_uid, seed.uid, seed.folder):
            _enrich_from_raw(seed, raw, "cache", max_chars_per_message)
        elif fetched := _try_fetch_bridge(
            bridge_caller, bridge_fallback_fn, account_uid, seed.uid, seed.folder
        ):
            _enrich_from_raw(seed, fetched, "bridge", max_chars_per_message)

    base_cf = seed.base_subject.casefold()
    seed_ts = seed.sort_ts
    span = window_days * 86400 if (window_days > 0 and seed_ts > 0) else None
    candidates: list[_Candidate] = [seed]
    seen_keys = {(seed.folder, seed.uid)}

    for folder in all_folders:
        if folder not in existing_tables or (
            folder != seed.folder and is_trash_or_junk_folder(folder)
        ):
            continue
        cols = get_table_columns(conn, folder)
        clauses: list[str] = []
        params: list[Any] = []
        if "deleted" in cols:
            clauses.append("COALESCE(deleted, 0) = 0")
        if base_cf and "subject" in cols:
            clauses.append("casefold_contains(subject, ?)")
            params.append(seed.base_subject)
        if span is not None and "dreceived" in cols:
            clauses.append(
                "(dreceived IS NULL OR dreceived = 0 OR (dreceived >= ? AND dreceived <= ?))"
            )
            params.extend([seed_ts - span, seed_ts + span])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur.execute(
            f"SELECT {_select_clause(cols)} FROM {quote_sql_ident(folder)} {where_sql} "
            f"ORDER BY dreceived DESC LIMIT 500",
            tuple(params),
        )
        for row in cur.fetchall():
            cand = _row_to_candidate(row, folder)
            if (cand.folder, cand.uid) in seen_keys:
                continue
            if base_cf and cand.base_subject.casefold() != base_cf:
                continue
            if raw := cache_reader(account_uid, cand.uid, folder):
                _enrich_from_raw(cand, raw, "cache", max_chars_per_message)
            seen_keys.add((cand.folder, cand.uid))
            candidates.append(cand)

    return seed, candidates


def _link_and_dedupe(seed: _Candidate, candidates: list[_Candidate]) -> list[_Candidate]:
    """Link candidates sharing RFC 5322 reference graph or subject+participant overlap."""
    adj: dict[str, set[str]] = {}

    def _edge(a: str, b: str) -> None:
        if a and b and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)

    for cand in candidates:
        refs = list(cand.references)
        if cand.in_reply_to and cand.in_reply_to not in refs:
            refs.append(cand.in_reply_to)
        for ref in refs:
            _edge(cand.message_id, ref)
        for idx in range(len(refs) - 1):
            _edge(refs[idx], refs[idx + 1])

    seed_ids = {x for x in (seed.message_id, seed.in_reply_to, *seed.references) if x}
    reachable = set(seed_ids)
    queue: deque[str] = deque(seed_ids)
    while queue:
        for nxt in adj.get(queue.popleft(), ()):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    linked: list[_Candidate] = []
    remaining: list[_Candidate] = []
    known_participants = set(seed.participants)

    for cand in candidates:
        cand_ids = {cand.message_id, cand.in_reply_to, *cand.references} - {""}
        if cand is seed or (cand_ids and reachable and (cand_ids & reachable)):
            linked.append(cand)
            known_participants.update(cand.participants)
        else:
            remaining.append(cand)

    seed_base_cf = seed.base_subject.casefold()
    for cand in remaining:
        if reachable and (cand.in_reply_to or cand.references):
            continue
        if seed_base_cf and cand.base_subject.casefold() == seed_base_cf:
            if not known_participants or (cand.participants & known_participants):
                linked.append(cand)
                known_participants.update(cand.participants)

    by_key: dict[str, _Candidate] = {}
    for cand in linked:
        key = f"mid:{cand.message_id}" if cand.message_id else f"row:{cand.folder}:{cand.uid}"
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = cand
            continue
        cand_better = (existing.raw_content is None and cand.raw_content is not None) or (
            bool(existing.raw_content) == bool(cand.raw_content)
            and _is_sent_folder(existing.folder)
            and not _is_sent_folder(cand.folder)
        )
        if cand_better:
            for folder in [existing.folder, *existing.also_in]:
                if folder != cand.folder and folder not in cand.also_in:
                    cand.also_in.append(folder)
            by_key[key] = cand
        elif cand.folder != existing.folder and cand.folder not in existing.also_in:
            existing.also_in.append(cand.folder)

    return sorted(by_key.values(), key=lambda c: (c.sort_ts, c.uid))


async def get_email_thread_logic(
    account_uid: str,
    message_uid: str | None = None,
    folder_name: str = "Inbox",
    *,
    message_id: str | None = None,
    strip_quoted: bool = True,
    max_chars_per_message: int = 3000,
    max_messages: int = 25,
    offset: int = 0,
    window_days: int = 90,
    db_path_getter: Callable[[str], str | None] | None = None,
    cache_reader: Callable[[str, str, str], str | None] | None = None,
    bridge_caller: Callable[[str, str, tuple[Any, ...]], Any] | None = None,
    bridge_fallback_fn: Callable[[], bool] | None = None,
) -> str:
    """Reconstruct chronological cross-folder email thread with quote stripping."""
    db_fn = db_path_getter or get_mail_db_path
    cache_fn = cache_reader or read_cached_message
    caller_fn = bridge_caller or call_bridge_method
    fallback_fn = bridge_fallback_fn or bridge_read_fallback_enabled

    def _logic() -> str:
        try:
            if not (message_uid and message_uid.strip()) and not (
                message_id and message_id.strip()
            ):
                raise ValidationError("Provide either 'message_uid' or 'message_id'.")
            if max_messages < 1 or max_messages > 100:
                raise ValidationError("'max_messages' must be between 1 and 100.")
            if offset < 0:
                raise ValidationError("'offset' must be >= 0.")
            if max_chars_per_message < 100:
                raise ValidationError("'max_chars_per_message' must be >= 100.")

            db_path = db_fn(account_uid)
            if not db_path:
                raise ResourceNotFoundError(f"Mail database not found for account '{account_uid}'.")

            resolved_folder = resolve_folder_name(account_uid, folder_name, db_path_getter=db_fn)
            with open_readonly_db(db_path) as conn:
                seed, candidates = _load_seed_and_candidates(
                    conn,
                    account_uid=account_uid,
                    seed_folder=resolved_folder,
                    message_uid=message_uid.strip() if message_uid else None,
                    message_id=message_id.strip() if message_id else None,
                    window_days=window_days,
                    max_chars_per_message=max_chars_per_message,
                    cache_reader=cache_fn,
                    bridge_caller=caller_fn,
                    bridge_fallback_fn=fallback_fn,
                )

            ordered = _link_and_dedupe(seed, candidates)
            items: list[dict[str, Any]] = []
            for cand in ordered[offset : offset + max_messages]:
                if cand.raw_content is not None:
                    parsed = parse_message_envelope(
                        cand.raw_content, max_chars=max_chars_per_message, strip_quoted=strip_quoted
                    )
                    body_text, truncated = parsed["body"], bool(parsed["truncated"])
                else:
                    truncated = len(cand.preview) > max_chars_per_message
                    body_text = cand.preview[:max_chars_per_message] if truncated else cand.preview

                items.append(
                    {
                        "uid": cand.uid,
                        "folder": cand.folder,
                        "also_in": cand.also_in,
                        "message_id": cand.message_id,
                        "in_reply_to": cand.in_reply_to,
                        "from": cand.mail_from,
                        "to": cand.mail_to,
                        "cc": cand.mail_cc,
                        "date": format_timestamp(cand.sort_ts),
                        "body": body_text,
                        "source": cand.source,
                        "truncated": truncated,
                    }
                )

            return paginated_envelope(
                items,
                total=len(ordered),
                offset=offset,
                extra_top={"subject": seed.base_subject or seed.subject},
                extra_meta={"strip_quoted": strip_quoted},
            )
        except (EdsMcpError, ValueError, sqlite3.Error) as exc:
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)
