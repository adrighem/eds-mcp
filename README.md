# Evolution Data Server (EDS) MCP Server

An MCP server that integrates with the GNOME Evolution Data Server (EDS). This allows Gemini to directly read your local calendar and contacts configured in GNOME Evolution (e.g., via Office365).

## Features

### Resources
- **eds://calendars**: Read all available and enabled calendars.
- **eds://mail/accounts**: Read all configured and enabled email accounts.
- **eds://mail/{account_uid}/folders**: Read the list of folders for a specific email account.

### Tools
- **get_calendar_events**: Retrieve calendar events for the coming days.
- **search_contacts**: Search for contacts in your Evolution address book.
- **get_emails**: Retrieve recent emails from a specific folder.

### Prompts
- **daily_briefing**: A prompt to generate a daily briefing based on the user's agenda.
- **contact_dossier**: Gather information about a specific contact.

## Accessing Microsoft Outlook Calendars

This MCP server relies on the GNOME Evolution Data Server (EDS). This means that to access Microsoft Outlook (Exchange or Office 365) calendars and contacts from your Linux system, you need to configure them in GNOME Evolution first:

1. Install GNOME Evolution and `evolution-ews` (the Exchange Web Services plugin).
2. Open Evolution and add a new account.
3. Choose "Exchange Web Services" (EWS) or "Outlook" as the server type and log in.
4. Ensure the calendars and contacts you want to access are enabled in Evolution's sidebar.
5. Once synced, `eds-mcp` will automatically discover and be able to read these calendars through EDS.

## Installation & Usage via `uv`

This project uses `uv` for package management. Because EDS bindings (`PyGObject`) often depend on system libraries, we recommend using `uv` in combination with system packages if necessary.

### 1. Preparing the project
```bash
cd /path/to/src/eds-mcp
uv venv --system-site-packages
source .venv/bin/activate
uv pip install -e .
```

### 2. Add as an MCP Server to Gemini
Add the following configuration to your Gemini/Claude config file (usually `~/.config/Gemini/config.json` or via the CLI):

```json
{
  "mcpServers": {
    "eds": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/src/eds-mcp",
        "run",
        "eds-mcp"
      ]
    }
  }
}
```

## Manual Testing
You can also run the server directly to see if it starts:
```bash
uv run eds-mcp
```

## Requirements
- Linux with GNOME
- `evolution-data-server` and the corresponding `-dev` packages.
- `python3-gi` (PyGObject bindings)
