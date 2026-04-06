# Evolution Data Server (EDS) MCP Server

An MCP server that integrates with the GNOME Evolution Data Server (EDS). This allows Gemini to directly read your local calendar and contacts configured in GNOME Evolution (e.g., via Office365).

## Features

- **list_calendars**: Show all available calendars.
- **get_calendar_events**: Retrieve calendar events for the coming days.
- **search_contacts**: Search for contacts in your Evolution address book.

## Installation & Usage via `uv`

This project uses `uv` for package management. Because EDS bindings (`PyGObject`) often depend on system libraries, we recommend using `uv` in combination with system packages if necessary.

### 1. Preparing the project
```bash
cd /home/vincent/src/eds-mcp
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
        "/home/vincent/src/eds-mcp",
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