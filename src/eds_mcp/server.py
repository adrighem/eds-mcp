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
    from .calendar import list_calendars_logic, get_calendar_events_logic
    from .contacts import search_contacts_logic
    from .mail import list_mail_accounts_logic, list_mail_folders_logic, get_emails_logic

    # --- Tool Registration ---

    @mcp.tool()
    async def list_calendars() -> str:
        """Lists all available calendars in Evolution."""
        return list_calendars_logic()

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
    async def search_contacts(query: str) -> str:
        """Searches for contacts in the Evolution address book by name or email."""
        return search_contacts_logic(query)

    @mcp.tool()
    async def list_mail_accounts() -> str:
        """Lists all configured Evolution email accounts and their UIDs."""
        return list_mail_accounts_logic()

    @mcp.tool()
    async def list_mail_folders(account_uid: str) -> str:
        """Lists folders for a specific Evolution mail account."""
        return list_mail_folders_logic(account_uid)

    @mcp.tool()
    async def get_emails(account_uid: str, folder_name: str = "Inbox", limit: int = 10) -> str:
        """Gets recent emails from a specific folder (defaults to Inbox)."""
        return get_emails_logic(account_uid, folder_name, limit)
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
