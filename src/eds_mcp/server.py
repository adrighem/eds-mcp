"""FastMCP server registration, resources, prompts, and tool annotations for EDS MCP."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import ErrorCode, error_envelope
from .env import check_gi_dependencies, setup_environment

setup_environment()

logger = logging.getLogger("eds_mcp")


def _ann(
    *, ro: bool = False, destr: bool = False, idem: bool = True, world: bool = False
) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=ro, destructiveHint=destr, idempotentHint=idem, openWorldHint=world
    )


_READ_LOCAL = _ann(ro=True)
_READ_REMOTE = _ann(ro=True, world=True)
_WRITE_IDEMPOTENT = _ann()
_WRITE_NON_IDEMPOTENT = _ann(idem=False)
_DESTRUCTIVE_LOCAL = _ann(destr=True)
_SEND_EXTERNAL = _ann(destr=True, idem=False, world=True)

mcp = FastMCP(
    "EDS",
    instructions="""EDS MCP Server: token-efficient access to Evolution Data Server (EDS).

### Resource Discovery (Preferred)
- `eds://mail/accounts`: Enabled mail accounts (`uid`, `name`).
- `eds://mail/{account_uid}/folders`: Mail folders and unread/total counts.
- `eds://calendars`: Enabled calendars.
- `eds://tasks`: Enabled task lists.
- `eds://memos`: Enabled memo lists.

### Tool Guidelines
- Prefer `get_email_thread` (quote-stripped) over repeated `get_email_body` calls.
- Prefer `create_draft` or `open_composer` when human review is requested before sending.
- Never inspect raw `~/.config/evolution` or `~/.cache/evolution` files directly.""",
)

if check_gi_dependencies():
    from . import calendar as _cal
    from . import contacts as _contacts
    from . import documents as _docs
    from . import mail as _mail
    from . import summary as _summary

    mcp.resource("eds://calendars")(_cal.list_calendars_logic)
    mcp.resource("eds://tasks")(_cal.list_tasks_logic)
    mcp.resource("eds://memos")(_cal.list_memos_logic)
    mcp.resource("eds://mail/accounts")(_mail.list_mail_accounts_logic)
    mcp.resource("eds://mail/{account_uid}/folders")(_mail.list_mail_folders_logic)

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_calendars() -> str:
        """List enabled calendars (`eds://calendars`)."""
        return await _cal.list_calendars_logic()

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_task_lists() -> str:
        """List enabled task lists (`eds://tasks`)."""
        return await _cal.list_tasks_logic()

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_memo_lists() -> str:
        """List enabled memo lists (`eds://memos`)."""
        return await _cal.list_memos_logic()

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_calendar_events(
        days_ahead: int = 7,
        days_back: int = 0,
        query: str | None = None,
        calendar_uid: str | None = None,
        date: str | None = None,
        summary_only: bool = False,
        include_attendees: bool = False,
        max_attendees: int = 50,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Fetch calendar events (recurring expanded). Compact attendee summary by default; `date='today'|'tomorrow'|'YYYY-MM-DD'`."""
        return await _cal.get_calendar_events_logic(
            days_ahead,
            days_back,
            query,
            calendar_uid,
            date,
            summary_only,
            include_attendees,
            max_attendees,
            limit,
            offset,
        )

    @mcp.tool(annotations=_WRITE_NON_IDEMPOTENT)
    async def create_calendar_event(
        calendar_uid: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
        ical_data: str | None = None,
    ) -> str:
        """Create calendar event in `calendar_uid` (`eds://calendars`) from structured ISO fields or raw `ical_data`."""
        return await _cal.create_calendar_event_logic(
            calendar_uid,
            ical_data,
            summary=summary,
            start=start,
            end=end,
            timezone=timezone,
            location=location,
            description=description,
            attendees=attendees,
        )

    @mcp.tool(annotations=_DESTRUCTIVE_LOCAL)
    async def delete_calendar_event(
        calendar_uid: str, event_uid: str, event_rid: str | None = None
    ) -> str:
        """Delete calendar event (or single recurrence instance when `event_rid` is set)."""
        return await _cal.delete_calendar_event_logic(calendar_uid, event_uid, event_rid)

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    async def update_calendar_event(
        calendar_uid: str,
        event_uid: str,
        event_rid: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        ical_data: str | None = None,
    ) -> str:
        """Update fields or raw `ical_data` of an existing calendar event."""
        return await _cal.update_calendar_event_logic(
            calendar_uid,
            event_uid,
            event_rid,
            summary,
            description,
            start=start,
            end=end,
            timezone=timezone,
            location=location,
            attendees=attendees,
            ical_data=ical_data,
        )

    @mcp.tool(annotations=_READ_REMOTE)
    async def get_shared_calendar_events(
        query: str, days_ahead: int = 7, days_back: int = 0, limit: int = 50, offset: int = 0
    ) -> str:
        """Fetch another user's EWS free/busy slots by email address or contact name."""
        return await _cal.get_shared_calendar_events_logic(
            query, days_ahead, days_back, limit, offset
        )

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_tasks(
        days_ahead: int = 30,
        days_back: int = 30,
        query: str | None = None,
        task_list_uid: str | None = None,
        date: str | None = None,
        summary_only: bool = False,
        include_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Fetch tasks (`eds://tasks`), excluding completed items by default (`limit=50`)."""
        return await _cal.get_tasks_logic(
            days_ahead,
            days_back,
            query,
            task_list_uid,
            date,
            summary_only,
            include_completed,
            limit,
            offset,
        )

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_memos(
        query: str | None = None,
        memo_list_uid: str | None = None,
        summary_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Fetch memos/notes (`eds://memos`, `limit=50`)."""
        return await _cal.get_memos_logic(query, memo_list_uid, summary_only, limit, offset)

    @mcp.tool(annotations=_READ_LOCAL)
    async def search_contacts(query: str, limit: int = 25, offset: int = 0) -> str:
        """Search Evolution address books by name or email (`limit` 1-200, default 25)."""
        return await _contacts.search_contacts_logic(query, limit, offset)

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_mail_accounts() -> str:
        """List enabled mail accounts (`eds://mail/accounts`)."""
        return await _mail.list_mail_accounts_logic()

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_mail_folders(account_uid: str) -> str:
        """List folders and unread/total counts (`eds://mail/{account_uid}/folders`)."""
        return await _mail.list_mail_folders_logic(account_uid)

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_emails(
        account_uid: str,
        folder_name: str = "Inbox",
        limit: int = 10,
        offset: int = 0,
        format: str = "json",
    ) -> str:
        """Fetch paginated emails from `folder_name` (case-insensitive, `limit` 1-200)."""
        return await _mail.get_emails_logic(account_uid, folder_name, limit, offset, format)

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_daily_summary(account_uid: str | None = None) -> str:
        """Return compact markdown summary of today's events, open tasks, and recent Inbox mail."""
        return await _summary.get_daily_summary_logic(
            _cal.get_calendar_events_logic,
            _cal.get_tasks_logic,
            _mail.list_mail_accounts_logic,
            _mail.get_emails_logic,
            account_uid=account_uid,
        )

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_email_body(
        account_uid: str, message_uid: str, folder_name: str = "Inbox", max_chars: int = 10000
    ) -> str:
        """Fetch parsed email headers, body, and `source` (`cache` or `bridge` fallback)."""
        return await _mail.get_email_body_logic(account_uid, message_uid, folder_name, max_chars)

    @mcp.tool(annotations=_READ_LOCAL)
    async def get_email_thread(
        account_uid: str,
        message_uid: str | None = None,
        folder_name: str = "Inbox",
        message_id: str | None = None,
        strip_quoted: bool = True,
        max_chars_per_message: int = 3000,
        max_messages: int = 25,
        offset: int = 0,
        window_days: int = 90,
    ) -> str:
        """Reconstruct chronological thread across Inbox/Archive/Sent with deduplication and quote stripping."""
        return await _mail.get_email_thread_logic(
            account_uid,
            message_uid,
            folder_name,
            message_id=message_id,
            strip_quoted=strip_quoted,
            max_chars_per_message=max_chars_per_message,
            max_messages=max_messages,
            offset=offset,
            window_days=window_days,
        )

    @mcp.tool(annotations=_READ_LOCAL)
    async def list_attachments(
        account_uid: str, message_uid: str, folder_name: str = "Inbox"
    ) -> str:
        """List attachment filenames and MIME types for an email."""
        return await _mail.list_attachments_logic(account_uid, message_uid, folder_name)

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    async def download_attachment(
        account_uid: str, message_uid: str, folder_name: str, attachment_name: str
    ) -> str:
        """Save email attachment to temporary local file and return `path` for `read_document`."""
        return await _mail.save_attachment_logic(
            account_uid, message_uid, folder_name, attachment_name
        )

    @mcp.tool(annotations=_READ_LOCAL)
    async def read_document(file_path: str) -> str:
        """Extract text from a downloaded PDF, DOCX, XLSX, or text document."""
        return await _docs.parse_document_logic(file_path)

    @mcp.tool(annotations=_READ_LOCAL)
    async def search_emails(
        account_uid: str,
        query: str = "",
        folder_name: str | None = None,
        limit: int = 25,
        offset: int = 0,
        from_query: str | None = None,
        to_query: str | None = None,
        since: str | None = None,
        until: str | None = None,
        unread_only: bool = False,
        dedupe_threads: bool = False,
        search_body: bool = False,
        max_scanned: int = 500,
    ) -> str:
        """Search emails (Unicode case-insensitive) with recipient/date/unread filters and opt-in cached body scan."""
        return await _mail.search_emails_logic(
            account_uid,
            query,
            folder_name,
            limit,
            offset,
            from_query=from_query,
            to_query=to_query,
            since=since,
            until=until,
            unread_only=unread_only,
            dedupe_threads=dedupe_threads,
            search_body=search_body,
            max_scanned=max_scanned,
        )

    @mcp.tool(annotations=_SEND_EXTERNAL)
    async def send_email(
        account_uid: str,
        to: str | list[str],
        subject: str,
        body: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachment_paths: list[str] | None = None,
        reply_to_message_uid: str | None = None,
        reply_to_folder: str = "Inbox",
    ) -> str:
        """Transmit email immediately via Evolution (supports `cc`, `bcc`, attachments, and threaded replies)."""
        return await _mail.send_mail_logic(
            account_uid,
            to,
            subject,
            body,
            cc=cc,
            bcc=bcc,
            attachment_paths=attachment_paths,
            reply_to_message_uid=reply_to_message_uid,
            reply_to_folder=reply_to_folder,
        )

    @mcp.tool(annotations=_WRITE_NON_IDEMPOTENT)
    async def create_draft(
        account_uid: str,
        to: str | list[str] = "",
        subject: str = "",
        body: str = "",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachment_paths: list[str] | None = None,
        reply_to_message_uid: str | None = None,
        reply_to_folder: str = "Inbox",
    ) -> str:
        """Save draft in account's Drafts folder without transmitting mail (preserves reply threading)."""
        return await _mail.create_draft_logic(
            account_uid,
            to,
            subject,
            body,
            cc=cc,
            bcc=bcc,
            attachment_paths=attachment_paths,
            reply_to_message_uid=reply_to_message_uid,
            reply_to_folder=reply_to_folder,
        )

    @mcp.tool(annotations=_WRITE_NON_IDEMPOTENT)
    async def open_composer(
        account_uid: str,
        to: str | list[str] = "",
        subject: str = "",
        body: str = "",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachment_paths: list[str] | None = None,
        reply_to_message_uid: str | None = None,
        reply_to_folder: str = "Inbox",
    ) -> str:
        """Open interactive Evolution GUI composer pre-populated with recipients, body, attachments, and reply headers."""
        return await _mail.open_composer_logic(
            account_uid,
            to,
            subject,
            body,
            cc=cc,
            bcc=bcc,
            attachment_paths=attachment_paths,
            reply_to_message_uid=reply_to_message_uid,
            reply_to_folder=reply_to_folder,
        )

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    async def mark_email_as_read(
        account_uid: str, message_uid: str, folder_name: str = "Inbox", read: bool = True
    ) -> str:
        """Mark email as read (`read=True`) or unread (`read=False`)."""
        return await _mail.mark_as_read_logic(account_uid, message_uid, folder_name, read)

    @mcp.tool(annotations=_DESTRUCTIVE_LOCAL)
    async def delete_email(account_uid: str, message_uid: str, folder_name: str = "Inbox") -> str:
        """Delete an email message from `folder_name`."""
        return await _mail.delete_message_logic(account_uid, message_uid, folder_name)

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    async def move_email(
        account_uid: str, message_uid: str, source_folder: str, dest_folder: str
    ) -> str:
        """Move an email message from `source_folder` to `dest_folder`."""
        return await _mail.move_email_logic(account_uid, message_uid, source_folder, dest_folder)

    @mcp.prompt("schedule_today")
    def schedule_today_prompt() -> str:
        """Generate today's schedule from agenda, pending tasks, and recent Inbox mail."""
        return (
            "Use 'get_calendar_events' (date='today'), 'get_tasks', and 'get_emails' for my primary inbox. "
            "Summarize my day, highlight urgent tasks, and flag emails needing a response."
        )

    @mcp.prompt("inbox_zero")
    def inbox_zero_prompt(account_name: str) -> str:
        """Analyze an inbox and suggest archive/delete/reply actions."""
        return (
            f"Find account_uid for '{account_name}' via 'eds://mail/accounts', fetch the latest 20 Inbox emails "
            "with 'get_emails', and recommend archive ('move_email'), delete, or draft reply ('create_draft')."
        )

    @mcp.prompt("contact_dossier")
    def contact_dossier_prompt(name: str) -> str:
        """Gather contact details from Evolution address books."""
        return f"Use 'search_contacts' to look up '{name}' and summarize their contact details."

    @mcp.prompt("analyze_email")
    def analyze_email_prompt(account_name: str, subject_query: str) -> str:
        """Search for an email thread and summarize the full conversation."""
        return (
            f"Find account_uid for '{account_name}' via 'eds://mail/accounts', run 'search_emails' for "
            f"'{subject_query}', then call 'get_email_thread' on the best match and summarize the thread."
        )

else:
    logger.error("EDS MCP server starting degraded due to missing GI dependencies.")

    @mcp.tool(annotations=_READ_LOCAL)
    async def system_status() -> str:
        """Return system GI dependency status."""
        return error_envelope(
            ErrorCode.DEPENDENCY_MISSING,
            "Evolution Data Server dependencies (PyGObject) are not installed on this system.",
            retryable=False,
            hint="Install python3-gi, gir1.2-edataserver-1.2, gir1.2-ecal-2.0, gir1.2-ebook-1.2, and gir1.2-ical-3.0.",
        )


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
