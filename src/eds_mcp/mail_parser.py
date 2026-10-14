import os
import re
import glob
import tempfile
import logging
from typing import Optional, Union
from email import message_from_string

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_COUNT = 10
MAX_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_BODY_LENGTH = 10000


def clean_html(html: str) -> str:
    """Basic HTML to text conversion without external dependencies."""
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<(br|p|div|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', html)
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()


def extract_text_from_message(raw_content: str) -> str:
    """Parses RFC822 message and extracts best text representation."""
    try:
        msg = message_from_string(raw_content)
        text_content = ""
        html_content = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get_content_disposition())

                if content_type == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text_content += payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeError, AttributeError):
                        text_content += str(payload)
                elif content_type == "text/html" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html_content += payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeError, AttributeError):
                        html_content += str(payload)
        else:
            content_type = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            if content_type == "text/html":
                try:
                    html_content = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeError, AttributeError):
                    html_content = str(payload)
            else:
                try:
                    text_content = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeError, AttributeError):
                    text_content = str(payload)

        if text_content.strip():
            final_text = text_content
        elif html_content.strip():
            final_text = clean_html(html_content)
        else:
            final_text = "No readable text content found."

        if len(final_text) > MAX_BODY_LENGTH:
            final_text = final_text[:MAX_BODY_LENGTH] + "\n\n[... content truncated due to length ...]"

        headers = [
            f"From: {msg.get('From')}",
            f"To: {msg.get('To')}",
            f"Subject: {msg.get('Subject')}",
            f"Date: {msg.get('Date')}",
            "-" * 40
        ]
        return "\n".join(headers) + "\n" + final_text
    except Exception as e:
        logger.exception("Failed to parse email content")
        return f"Error parsing email content: {e}\n\nRaw content sample: {raw_content[:500]}..."


def get_cached_message_path(account_uid: str, message_uid: str, folder_name: str) -> Optional[str]:
    """Return cached RFC822 message path for Evolution message UID."""
    base_cache = os.path.expanduser(f"~/.cache/evolution/mail/{account_uid}/folders")
    if not os.path.exists(base_cache):
        base_cache = os.path.expanduser(f"~/.local/share/evolution/mail/{account_uid}/folders")

    folder_path = os.path.join(base_cache, folder_name, "cur")
    if not os.path.exists(folder_path):
        return None

    matches = glob.glob(os.path.join(folder_path, "*", glob.escape(message_uid)))
    return matches[0] if matches else None


def read_cached_message(account_uid: str, message_uid: str, folder_name: str) -> Optional[str]:
    """Read locally cached RFC822 message if Evolution cached it."""
    message_path = get_cached_message_path(account_uid, message_uid, folder_name)
    if not message_path:
        return None

    try:
        with open(message_path, "r", errors="replace") as f:
            return f.read()
    except OSError as e:
        logger.warning("Failed to read cached message at %s: %s", message_path, e)
        return None


def list_attachments_from_message(raw_content: str) -> list[dict[str, str]]:
    """Return attachment metadata from raw RFC822 message."""
    msg = message_from_string(raw_content)
    attachments = []

    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue

        attachments.append({
            "filename": filename,
            "mime_type": part.get_content_type(),
        })

    return attachments


def save_attachment_from_message(raw_content: str, attachment_name: str) -> Optional[str]:
    """Save attachment from raw RFC822 message to temporary directory."""
    msg = message_from_string(raw_content)
    safe_name = os.path.basename(attachment_name)
    if not safe_name:
        return None

    for part in msg.walk():
        if part.get_filename() != attachment_name:
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            payload = part.get_payload()
            if isinstance(payload, str):
                payload = payload.encode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                payload = b""

        temp_dir = tempfile.mkdtemp(prefix="eds_mcp_attachment_")
        dest_path = os.path.join(temp_dir, safe_name)
        with open(dest_path, "wb") as f:
            f.write(payload)
        return dest_path

    return None


def normalize_attachment_paths(attachment_paths: Optional[list[str]]) -> list[str]:
    """Validate local attachment paths without exposing full paths in errors."""
    if not attachment_paths:
        return []
    if len(attachment_paths) > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"At most {MAX_ATTACHMENT_COUNT} attachments are allowed.")

    normalized_paths = []
    total_bytes = 0
    for attachment_path in attachment_paths:
        normalized_path = os.path.realpath(os.path.abspath(os.path.expanduser(attachment_path)))
        basename = os.path.basename(normalized_path) or "attachment"
        try:
            stat_result = os.stat(normalized_path)
        except OSError:
            raise ValueError(f"Attachment '{basename}' is not a readable regular file.") from None
        if not os.path.isfile(normalized_path) or not os.access(normalized_path, os.R_OK):
            raise ValueError(f"Attachment '{basename}' is not a readable regular file.")

        total_bytes += stat_result.st_size
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            raise ValueError("Attachments exceed the 20 MiB total size limit.")
        normalized_paths.append(normalized_path)

    return normalized_paths


def extract_reply_headers(raw_content: str) -> tuple[str, str]:
    """Return sanitized In-Reply-To and References values from RFC822 message."""
    message = message_from_string(raw_content)

    def _sanitize(value: Optional[str]) -> str:
        return re.sub(r"[\r\n]+", " ", value or "").strip()

    message_id = _sanitize(message.get("Message-ID"))
    references = _sanitize(message.get("References"))
    if message_id and message_id not in references.split():
        references = f"{references} {message_id}".strip()
    return message_id, references


def normalize_recipients(recipients: Optional[Union[str, list[str]]]) -> str:
    """Normalizes string or list of recipient email addresses into clean comma-separated string."""
    if not recipients:
        return ""
    if isinstance(recipients, str):
        addrs = [addr.strip() for addr in re.split(r'[,;]+', recipients) if addr.strip()]
        return ", ".join(addrs)
    if isinstance(recipients, (list, tuple)):
        addrs = []
        for item in recipients:
            if isinstance(item, str):
                addrs.extend([addr.strip() for addr in re.split(r'[,;]+', item) if addr.strip()])
            else:
                raise ValueError(f"Invalid recipient item type: {type(item)}")
        return ", ".join(addrs)
    raise ValueError(f"Invalid recipients type: {type(recipients)}")
