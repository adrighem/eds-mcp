"""Evolution CamelDataCache path lookup, MIME parsing, and reply-quote stripping."""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import re
import shutil
import tempfile
from email import message_from_string
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses
from typing import Any

from . import ValidationError
from .mail_db import get_mail_roots, validate_safe_identifier

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_COUNT = 10
MAX_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_BODY_LENGTH = 10000

_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fwd|fw|aw|wg|vs|sv|antw|doorst|tr)(?:\[\d+\])?\s*:\s*)+",
    re.IGNORECASE,
)
_SEPARATOR_LINE_RE = re.compile(
    r"^\s*(?:-{3,}\s*(?:original message|oorspronkelijk bericht|urspr[uü]ngliche nachricht|"
    r"opprinnelig melding|forwarded message|doorgestuurd bericht|weitergeleitete nachricht)\s*-{0,}"
    r"|_{16,})\s*$",
    re.IGNORECASE,
)
_SINGLE_LINE_ATTRIBUTION_RE = re.compile(
    r"^\s*(?:on\s+.+\bwrote:|op\s+.+\bschreef(?:\s+.+)?:|am\s+.+\bschrieb(?:\s+.+)?:"
    r"|den\s+.+\bskrev(?:\s+.+)?:|le\s+.+\ba\s+[ée]crit\s*:)\s*$",
    re.IGNORECASE,
)
_WRAPPED_ATTRIBUTION_START_RE = re.compile(r"^\s*(?:on|op|am|den)\s+.+$", re.IGNORECASE)
_WRAPPED_ATTRIBUTION_END_RE = re.compile(
    r"^.*\b(?:wrote|schreef|schrieb|skrev)\s*:\s*$", re.IGNORECASE
)
_HEADER_BLOCK_START_RE = re.compile(r"^\s*\*?(?:from|van|von|fra)\*?\s*:\s*\S+", re.IGNORECASE)
_HEADER_BLOCK_FOLLOW_RE = re.compile(
    r"^\s*\*?(?:sent|date|verzonden|datum|gesendet|sendt|dato|to|aan|an|til|cc|"
    r"subject|onderwerp|betreff|emne)\*?\s*:\s*",
    re.IGNORECASE,
)


def _candidate_folder_dirs(base_folders_dir: str, folder_name: str) -> list[str]:
    """Return candidate on-disk directories for an Evolution mail folder."""
    parts = [p for p in folder_name.split("/") if p]
    if not parts:
        return []
    candidates = [os.path.join(base_folders_dir, *parts)]
    if len(parts) > 1:
        sub_parts = [parts[0]]
        for seg in parts[1:]:
            sub_parts.extend(["subfolders", seg])
        candidates.append(os.path.join(base_folders_dir, *sub_parts))

    resolved = [cand for cand in candidates if os.path.isdir(cand)]
    if resolved or not os.path.isdir(base_folders_dir):
        return resolved

    for use_subfolders in (False, True):
        cur = base_folders_dir
        ok = True
        for idx, seg in enumerate(parts):
            if idx > 0 and use_subfolders:
                cur = os.path.join(cur, "subfolders")
            try:
                entries = os.listdir(cur)
            except OSError:
                ok = False
                break
            match = next((e for e in entries if e.casefold() == seg.casefold()), None)
            if not match or not os.path.isdir(os.path.join(cur, match)):
                ok = False
                break
            cur = os.path.join(cur, match)
        if ok and cur not in resolved:
            resolved.append(cur)
    return resolved


def get_cached_message_path(
    account_uid: str,
    message_uid: str,
    folder_name: str = "Inbox",
) -> str | None:
    """Return cached RFC822 message path supporting SHA-256 EWS and raw IMAP UIDs."""
    if not message_uid or "\x00" in message_uid:
        return None
    effective_folder = (folder_name or "Inbox").strip() or "Inbox"
    validate_safe_identifier(effective_folder, "folder_name")

    uid_sha256 = hashlib.sha256(message_uid.encode("utf-8")).hexdigest()
    hash_bucket = uid_sha256[:2]
    is_safe_raw = (
        "/" not in message_uid and "\\" not in message_uid and message_uid not in {".", ".."}
    )

    for root in get_mail_roots(account_uid):
        folders_dir = os.path.join(root, "folders")
        for folder_dir in _candidate_folder_dirs(folders_dir, effective_folder):
            for state_dir in ("cur", "new"):
                hashed_path = os.path.join(folder_dir, state_dir, hash_bucket, uid_sha256)
                if os.path.isfile(hashed_path):
                    return hashed_path

            for state_dir in ("cur", "new"):
                state_path = os.path.join(folder_dir, state_dir)
                if not os.path.isdir(state_path):
                    continue
                if is_safe_raw:
                    direct_raw = os.path.join(state_path, message_uid)
                    if os.path.isfile(direct_raw):
                        return direct_raw
                    raw_matches = glob.glob(os.path.join(state_path, "*", glob.escape(message_uid)))
                    if raw_matches:
                        return raw_matches[0]
                hash_matches = glob.glob(os.path.join(state_path, "*", uid_sha256))
                if hash_matches:
                    return hash_matches[0]
    return None


def read_cached_message(
    account_uid: str,
    message_uid: str,
    folder_name: str = "Inbox",
) -> str | None:
    """Read locally cached RFC822 message if Evolution cached it on disk."""
    message_path = get_cached_message_path(account_uid, message_uid, folder_name)
    if not message_path:
        return None
    try:
        with open(message_path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        logger.warning("Failed to read cached message at %s: %s", message_path, exc)
        return None


def decode_mime_header(value: Any) -> str:
    """Decode RFC 2047 encoded header values safely into a single-line Unicode string."""
    if value is None or not (raw_str := str(value)):
        return ""
    try:
        chunks: list[str] = []
        for fragment, charset in decode_header(raw_str):
            if isinstance(fragment, bytes):
                try:
                    chunks.append(fragment.decode(charset or "utf-8", errors="replace"))
                except LookupError:
                    chunks.append(fragment.decode("latin-1", errors="replace"))
            else:
                chunks.append(str(fragment))
        joined = "".join(chunks)
    except (ValueError, LookupError, TypeError):
        joined = raw_str
    return re.sub(r"[\r\n\t]+", " ", joined).strip()


def clean_html(html: str) -> str:
    """Convert HTML into readable plain text without external dependencies."""
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<(br|p|div|li|tr)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", cleaned)
    for ent, ch in (
        ("&nbsp;", " "),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(ent, ch)
    return re.sub(r"\n[ \t]*\n+", "\n\n", text).strip()


def _is_header_block_at(lines: list[str], idx: int) -> bool:
    """Detect localized From:/Sent:/To:/Subject: reply header blocks."""
    if not _HEADER_BLOCK_START_RE.match(lines[idx]):
        return False
    follow_matches = 0
    for j in range(idx + 1, min(len(lines), idx + 6)):
        if not (stripped := lines[j].strip()):
            break
        if _HEADER_BLOCK_FOLLOW_RE.match(stripped):
            follow_matches += 1
    return follow_matches >= 2


def strip_quoted_text(text: str) -> str:
    """Strip quoted reply history across EN/NL/DE/NO formats while preserving inline replies."""
    if not text or not text.strip():
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    for idx, line in enumerate(lines):
        if _SEPARATOR_LINE_RE.match(line) or _is_header_block_at(lines, idx):
            lines = lines[:idx]
            break

    for idx, line in enumerate(lines):
        attr_len = 0
        if _SINGLE_LINE_ATTRIBUTION_RE.match(line):
            attr_len = 1
        elif (
            idx + 1 < len(lines)
            and _WRAPPED_ATTRIBUTION_START_RE.match(line)
            and _WRAPPED_ATTRIBUTION_END_RE.match(lines[idx + 1].strip())
        ):
            attr_len = 2
        if attr_len > 0:
            non_empty = [ln.strip() for ln in lines[idx + attr_len :] if ln.strip()]
            if non_empty and all(ln.startswith(">") for ln in non_empty):
                lines = lines[:idx]
                break

    kept: list[str] = []
    skip_next = False
    for idx, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if _SINGLE_LINE_ATTRIBUTION_RE.match(stripped):
            nxt = next(
                (lines[k].strip() for k in range(idx + 1, len(lines)) if lines[k].strip()), ""
            )
            if not nxt or nxt.startswith(">"):
                continue
        if (
            idx + 1 < len(lines)
            and _WRAPPED_ATTRIBUTION_START_RE.match(stripped)
            and _WRAPPED_ATTRIBUTION_END_RE.match(lines[idx + 1].strip())
        ):
            nxt = next(
                (lines[k].strip() for k in range(idx + 2, len(lines)) if lines[k].strip()), ""
            )
            if not nxt or nxt.startswith(">"):
                skip_next = True
                continue
        kept.append(line)

    result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return result if result else normalized.strip()


def _decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    if not isinstance(payload, (bytes, bytearray)):
        return str(payload)
    try:
        return bytes(payload).decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        return bytes(payload).decode("latin-1", errors="replace")


def _extract_body_from_msg(msg: Message, *, strip_quoted: bool = False) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if (
                part.is_multipart()
                or (part.get_content_disposition() or "").lower() == "attachment"
            ):
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain_parts.append(_decode_part_payload(part))
            elif ctype == "text/html":
                html_parts.append(_decode_part_payload(part))
    elif msg.get_content_type() == "text/html":
        html_parts.append(_decode_part_payload(msg))
    else:
        plain_parts.append(_decode_part_payload(msg))

    if plain_joined := "\n".join(p for p in plain_parts if p).strip():
        body = plain_joined
    elif html_joined := "\n".join(h for h in html_parts if h).strip():
        body = clean_html(html_joined)
    else:
        body = "No readable text content found."

    if strip_quoted and body != "No readable text content found.":
        body = strip_quoted_text(body)
    return body


def extract_body_text(raw_content: str, *, strip_quoted: bool = False) -> str:
    """Extract plain-text (or cleaned HTML fallback) body from RFC822 content."""
    return _extract_body_from_msg(message_from_string(raw_content), strip_quoted=strip_quoted)


def parse_message_envelope(
    raw_or_msg: str | Message,
    *,
    max_chars: int = MAX_BODY_LENGTH,
    strip_quoted: bool = False,
) -> dict[str, Any]:
    """Parse RFC822 string or Message into compact headers, body, and truncation metadata."""
    msg = message_from_string(raw_or_msg) if isinstance(raw_or_msg, str) else raw_or_msg
    body = _extract_body_from_msg(msg, strip_quoted=strip_quoted)
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]

    msg_id = re.sub(r"[\r\n\t]+", " ", str(msg.get("Message-ID") or "")).strip()
    in_reply_to = re.sub(r"[\r\n\t]+", " ", str(msg.get("In-Reply-To") or "")).strip()
    refs_raw = re.sub(r"[\r\n\t]+", " ", str(msg.get("References") or "")).strip()
    return {
        "from": decode_mime_header(msg.get("From")),
        "to": decode_mime_header(msg.get("To")),
        "cc": decode_mime_header(msg.get("Cc")),
        "subject": decode_mime_header(msg.get("Subject")),
        "date": decode_mime_header(msg.get("Date")),
        "message_id": msg_id,
        "in_reply_to": in_reply_to,
        "references": [tok for tok in refs_raw.split() if tok],
        "body": body,
        "truncated": truncated,
    }


def extract_text_from_message(raw_content: str) -> str:
    """Format RFC822 message into human-readable header + body text."""
    parsed = parse_message_envelope(raw_content, max_chars=MAX_BODY_LENGTH, strip_quoted=False)
    body = parsed["body"]
    if parsed["truncated"]:
        body += "\n\n[... content truncated due to length ...]"
    headers = [
        f"From: {parsed['from'] or None}",
        f"To: {parsed['to'] or None}",
        f"Subject: {parsed['subject'] or None}",
        f"Date: {parsed['date'] or None}",
        "-" * 40,
    ]
    return "\n".join(headers) + "\n" + body


def normalize_subject(subject: str | None) -> str:
    """Strip localized reply/forward prefixes and collapse whitespace."""
    if not subject:
        return ""
    cleaned = decode_mime_header(subject)
    while (updated := _SUBJECT_PREFIX_RE.sub("", cleaned)) != cleaned:
        cleaned = updated
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_email_addresses(*header_values: str | None) -> set[str]:
    """Extract normalized lowercase email addresses from RFC 5322 header strings."""
    inputs = [decode_mime_header(v) for v in header_values if v]
    if not inputs:
        return set()
    return {addr.strip().casefold() for _, addr in getaddresses(inputs) if addr and "@" in addr}


def list_attachments_from_message(raw_content: str) -> list[dict[str, str]]:
    """Return attachment metadata from raw RFC822 message."""
    msg = message_from_string(raw_content)
    return [
        {"filename": decode_mime_header(fn), "mime_type": part.get_content_type()}
        for part in msg.walk()
        if (fn := part.get_filename())
    ]


def save_attachment_from_message(raw_content: str, attachment_name: str) -> str | None:
    """Save named attachment from raw RFC822 message to a temporary directory."""
    safe_name = os.path.basename(attachment_name)
    if not safe_name:
        return None
    msg = message_from_string(raw_content)
    for part in msg.walk():
        if not (raw_fn := part.get_filename()):
            continue
        decoded_fn = decode_mime_header(raw_fn)
        if decoded_fn not in (attachment_name, safe_name):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            raw_payload = part.get_payload()
            payload = (
                raw_payload.encode(part.get_content_charset() or "utf-8", errors="replace")
                if isinstance(raw_payload, str)
                else b""
            )
        temp_dir = tempfile.mkdtemp(prefix="eds_mcp_attachment_")
        dest_path = os.path.join(temp_dir, safe_name)
        try:
            with open(dest_path, "wb") as handle:
                handle.write(bytes(payload))
            return dest_path
        except OSError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
    return None


def normalize_attachment_paths(attachment_paths: list[str] | None) -> list[str]:
    """Validate local attachment paths without exposing full directory paths in errors."""
    if not attachment_paths:
        return []
    if len(attachment_paths) > MAX_ATTACHMENT_COUNT:
        raise ValidationError(f"At most {MAX_ATTACHMENT_COUNT} attachments are allowed.")

    normalized_paths: list[str] = []
    total_bytes = 0
    for attachment_path in attachment_paths:
        norm = os.path.realpath(os.path.abspath(os.path.expanduser(attachment_path)))
        basename = os.path.basename(norm) or "attachment"
        try:
            stat_result = os.stat(norm)
        except OSError:
            raise ValidationError(
                f"Attachment '{basename}' is not a readable regular file."
            ) from None
        if not os.path.isfile(norm) or not os.access(norm, os.R_OK):
            raise ValidationError(f"Attachment '{basename}' is not a readable regular file.")
        total_bytes += stat_result.st_size
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            raise ValidationError("Attachments exceed the 20 MiB total size limit.")
        normalized_paths.append(norm)
    return normalized_paths


def extract_reply_headers(raw_content: str) -> tuple[str, str]:
    """Return sanitized In-Reply-To and References values from RFC822 message."""
    msg = message_from_string(raw_content)
    msg_id = re.sub(r"[\r\n]+", " ", str(msg.get("Message-ID") or "")).strip()
    refs = re.sub(r"[\r\n]+", " ", str(msg.get("References") or "")).strip()
    if msg_id and msg_id not in refs.split():
        refs = f"{refs} {msg_id}".strip()
    return msg_id, refs


def normalize_recipients(recipients: str | list[str] | None) -> str:
    """Normalize string or list of recipient addresses into comma-separated string."""
    if not recipients:
        return ""
    if isinstance(recipients, str):
        return ", ".join(a.strip() for a in re.split(r"[,;]+", recipients) if a.strip())
    if isinstance(recipients, (list, tuple)):
        addrs: list[str] = []
        for item in recipients:
            if not isinstance(item, str):
                raise ValidationError(f"Invalid recipient item type: {type(item)}")
            addrs.extend(a.strip() for a in re.split(r"[,;]+", item) if a.strip())
        return ", ".join(addrs)
    raise ValidationError(f"Invalid recipients type: {type(recipients)}")
