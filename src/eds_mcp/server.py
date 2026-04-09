import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment, check_gi_dependencies
setup_environment()

# Global logger for the server
logger = logging.getLogger("eds_mcp")

# FastMCP instance
mcp = FastMCP("EDS")

if check_gi_dependencies():
    from .calendar import list_calendars_logic, get_calendar_events_logic, get_shared_calendar_events_logic
    from .contacts import search_contacts_logic
    from .mail import list_mail_accounts_logic, list_mail_folders_logic, get_emails_logic

    # --- Resources ---

    @mcp.resource("eds://calendars")
    def get_calendars_resource() -> str:
        """Read the list of available and enabled calendars in Evolution."""
        return list_calendars_logic()

    @mcp.resource("eds://mail/accounts")
    def get_mail_accounts_resource() -> str:
        """Read the list of configured and enabled Evolution email accounts."""
        return list_mail_accounts_logic()

    @mcp.resource("eds://mail/{account_uid}/folders")
    def get_mail_folders_resource(account_uid: str) -> str:
        """Read the list of folders for a specific Evolution mail account."""
        return list_mail_folders_logic(account_uid)


    # --- Tools ---

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
        return get_calendar_events_logic(days_ahead, days_back, query, calendar_uid)

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
        return get_shared_calendar_events_logic(query, days_ahead, days_back)

    @mcp.tool()
    async def search_contacts(query: str) -> str:
        """Searches for contacts in the Evolution address book by name or email."""
        return search_contacts_logic(query)

    @mcp.tool()
    async def get_emails(account_uid: str, folder_name: str = "Inbox", limit: int = 10) -> str:
        """Gets recent emails from a specific folder (defaults to Inbox)."""
        return get_emails_logic(account_uid, folder_name, limit)


    # --- Prompts ---

    @mcp.prompt("daily_briefing")
    def daily_briefing_prompt() -> str:
        """A prompt to generate a daily briefing based on the user's agenda."""
        return "Please use the 'get_calendar_events' tool to fetch my events for today. Then, summarize my schedule. Point out any back-to-back meetings or unusual gaps."

    @mcp.prompt("contact_dossier")
    def contact_dossier_prompt(name: str) -> str:
        """Gather information about a contact."""
        return f"Please use the 'search_contacts' tool to look up '{name}'. Provide a summary of their contact details. If you can't find them, let me know."

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
