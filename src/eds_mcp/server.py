import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment, check_gi_dependencies
setup_environment()

# Global logger for the server
logger = logging.getLogger("eds_mcp")

# FastMCP instance
mcp = FastMCP(
    "EDS",
    instructions="""EDS MCP Server — execute operations on Evolution Data Server (EDS).

### 📖 Resource Hierarchy (Preferred for Discovery)
Use these resources to discover UIDs and stable identifiers:
- `eds://mail/accounts`: List all configured email accounts.
- `eds://mail/{account_uid}/folders`: List folders for a specific account.
- `eds://calendars`: List all available and enabled calendars.
- `eds://tasks`: List all enabled task lists.
- `eds://memos`: List all enabled memo lists.

### 🛠️ Tool Usage
- Use tools (e.g., `get_emails`, `get_calendar_events`) for performing actions, complex queries, or state changes.
- ALWAYS use these tools/resources instead of raw shell commands on Evolution files.
- To analyze an inbox, first find the `account_uid` via the `eds://mail/accounts` resource, then use `get_emails` or `search_emails`."""
)

if check_gi_dependencies():
    from .calendar import (
        list_calendars_logic, get_calendar_events_logic, get_shared_calendar_events_logic,
        list_tasks_logic, get_tasks_logic, list_memos_logic, get_memos_logic,
        create_calendar_event_logic
    )
    from .contacts import search_contacts_logic
    from .mail import (
        list_mail_accounts_logic, list_mail_folders_logic, get_emails_logic, 
        search_emails_logic, move_email_logic, get_email_body_logic,
        send_mail_logic, mark_as_read_logic, delete_message_logic
    )

    # --- Resources ---

    @mcp.resource("eds://calendars")
    async def get_calendars_resource() -> str:
        """Read the list of available and enabled calendars in Evolution."""
        return await list_calendars_logic()

    @mcp.resource("eds://tasks")
    async def get_tasks_resource() -> str:
        """Read the list of available and enabled task lists in Evolution."""
        return await list_tasks_logic()

    @mcp.resource("eds://memos")
    async def get_memos_resource() -> str:
        """Read the list of available and enabled memo lists in Evolution."""
        return await list_memos_logic()

    @mcp.resource("eds://mail/accounts")
    async def get_mail_accounts_resource() -> str:
        """Read the list of configured and enabled Evolution email accounts."""
        return await list_mail_accounts_logic()

    @mcp.resource("eds://mail/{account_uid}/folders")
    async def get_mail_folders_resource(account_uid: str) -> str:
        """Read the list of folders for a specific Evolution mail account."""
        return await list_mail_folders_logic(account_uid)


    # --- Tools ---

    @mcp.tool()
    async def list_calendars() -> str:
        """Lists all configured and enabled Evolution calendars."""
        return await list_calendars_logic()

    @mcp.tool()
    async def list_task_lists() -> str:
        """Lists all configured and enabled Evolution task lists."""
        return await list_tasks_logic()

    @mcp.tool()
    async def list_memo_lists() -> str:
        """Lists all configured and enabled Evolution memo lists."""
        return await list_memos_logic()

    @mcp.tool()
    async def get_calendar_events(
        days_ahead: int = 7,
        days_back: int = 0,
        query: Optional[str] = None,
        calendar_uid: Optional[str] = None
    ) -> str:
        """Gets calendar events for a date range and optional search query.
        Includes support for recurring events via EDS instance generation.
        """
        return await get_calendar_events_logic(days_ahead, days_back, query, calendar_uid)

    @mcp.tool()
    async def create_calendar_event(calendar_uid: str, ical_data: str) -> str:
        """Creates a new calendar event in Evolution."""
        return await create_calendar_event_logic(calendar_uid, ical_data)

    @mcp.tool()
    async def get_shared_calendar_events(
        query: str,
        days_ahead: int = 7,
        days_back: int = 0
    ) -> str:
        """Gets calendar events for another user by temporarily adding their shared calendar.
        If the detailed calendar cannot be read, falls back to Free/Busy information.
        The 'query' can be an email address or a contact name.
        """
        return await get_shared_calendar_events_logic(query, days_ahead, days_back)

    @mcp.tool()
    async def get_tasks(
        days_ahead: int = 30,
        days_back: int = 30,
        query: Optional[str] = None,
        task_list_uid: Optional[str] = None
    ) -> str:
        """Gets tasks/to-dos from Evolution task lists."""
        return await get_tasks_logic(days_ahead, days_back, query, task_list_uid)

    @mcp.tool()
    async def get_memos(
        query: Optional[str] = None,
        memo_list_uid: Optional[str] = None
    ) -> str:
        """Gets memos/notes from Evolution memo lists."""
        return await get_memos_logic(query, memo_list_uid)

    @mcp.tool()
    async def search_contacts(query: str) -> str:
        """Searches for contacts in the Evolution address book by name or email."""
        return await search_contacts_logic(query)

    @mcp.tool()
    async def list_mail_accounts() -> str:
        """Lists all configured and enabled Evolution email accounts."""
        return await list_mail_accounts_logic()

    @mcp.tool()
    async def list_mail_folders(account_uid: str) -> str:
        """Lists all folders for a specific Evolution mail account."""
        return await list_mail_folders_logic(account_uid)

    @mcp.tool()
    async def get_emails(account_uid: str, folder_name: str = "Inbox", limit: int = 10) -> str:
        """Gets recent emails from a specific folder (defaults to Inbox)."""
        return await get_emails_logic(account_uid, folder_name, limit)

    @mcp.tool()
    async def get_email_body(account_uid: str, message_uid: str, folder_name: str = "INBOX") -> str:
        """Retrieves the full raw body/content of an email message."""
        return await get_email_body_logic(account_uid, message_uid, folder_name)

    @mcp.tool()
    async def search_emails(account_uid: str, query: str, folder_name: Optional[str] = None, limit: int = 10) -> str:
        """Searches emails for a specific query across all folders or a specific folder."""
        return await search_emails_logic(account_uid, query, folder_name, limit)

    @mcp.tool()
    async def send_email(account_uid: str, to: str, subject: str, body: str) -> str:
        """Sends a new email via Evolution."""
        return await send_mail_logic(account_uid, to, subject, body)

    @mcp.tool()
    async def mark_email_as_read(account_uid: str, message_uid: str, folder_name: str, read: bool = True) -> str:
        """Marks an email as read or unread."""
        return await mark_as_read_logic(account_uid, message_uid, folder_name, read)

    @mcp.tool()
    async def delete_email(account_uid: str, message_uid: str, folder_name: str) -> str:
        """Deletes an email message."""
        return await delete_message_logic(account_uid, message_uid, folder_name)

    @mcp.tool()
    async def move_email(account_uid: str, message_uid: str, source_folder: str, dest_folder: str) -> str:
        """Moves an email from one folder to another.
        
        Args:
            account_uid: The UID of the mail account.
            message_uid: The UID of the message to move.
            source_folder: The name of the source folder (e.g. 'Inbox').
            dest_folder: The name of the destination folder (e.g. 'Archive').
        """
        return await move_email_logic(account_uid, message_uid, source_folder, dest_folder)


    # --- Prompts ---

    @mcp.prompt("daily_briefing")
    def daily_briefing_prompt() -> str:
        """A prompt to generate a daily briefing based on the user's agenda, tasks and recent mail."""
        return (
            "Please use 'get_calendar_events' for today, 'get_tasks' for pending items, "
            "and 'get_emails' for my primary inbox. Summarize my day, highlight urgent tasks, "
            "and point out important emails that might need a response."
        )

    @mcp.prompt("inbox_zero")
    def inbox_zero_prompt(account_name: str) -> str:
        """Analyze a specific inbox and suggest management actions."""
        return (
            f"Use the 'list_mail_accounts' tool to find the account_uid for '{account_name}'. "
            "Then use 'get_emails' to fetch the latest 20 messages. For each email, analyze if it should be "
            "archived, deleted, or if it needs a reply. Suggest using 'move_email' for archiving."
        )

    @mcp.prompt("contact_dossier")
    def contact_dossier_prompt(name: str) -> str:
        """Gather information about a contact."""
        return f"Please use the 'search_contacts' tool to look up '{name}'. Provide a summary of their contact details. If you can't find them, let me know."

    @mcp.prompt("analyze_email")
    def analyze_email_prompt(account_name: str, subject_query: str) -> str:
        """Search for a specific email and analyze its full content."""
        return (
            f"Find the account_uid for '{account_name}' using 'list_mail_accounts'. Then search for emails matching '{subject_query}'. "
            "Use 'get_email_body' to fetch the full content of the most relevant match and provide a "
            "detailed analysis or summary of the conversation."
        )


else:
    logger.error("EDS MCP server starting with degraded functionality due to missing GI dependencies.")

    @mcp.tool()
    async def system_status() -> str:
        """Returns the system dependency status."""
        return "Error: Evolution Data Server dependencies (PyGObject) are not installed correctly on this system."

def main():
    """Main entry point for the MCP server."""
    mcp.run()

if __name__ == "__main__":
    main()
