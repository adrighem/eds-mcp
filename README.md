# Evolution Data Server (EDS) MCP Server

Een MCP server die integreert met de GNOME Evolution Data Server (EDS). Hiermee kan Gemini direct je lokale agenda en contactpersonen uitlezen die je in GNOME Evolution (bijv. via Office365) hebt geconfigureerd.

## Features

- **list_calendars**: Toon alle beschikbare agenda's.
- **get_calendar_events**: Haal agenda-items op voor de komende dagen.
- **search_contacts**: Zoek in je Evolution adresboek naar contactpersonen.

## Installatie & Gebruik via `uv`

Dit project maakt gebruik van `uv` voor package management. Omdat EDS-bindings (`PyGObject`) vaak afhankelijk zijn van systeem-libraries, raden we aan om `uv` te gebruiken in combinatie met de systeem-packages indien nodig.

### 1. Project klaarzetten
```bash
cd /home/vincent/src/eds-mcp
uv venv --system-site-packages
source .venv/bin/activate
uv pip install -e .
```

### 2. Als MCP Server toevoegen aan Gemini
Voeg de volgende configuratie toe aan je Gemini/Claude config bestand (meestal `~/.config/Gemini/config.json` of via de CLI):

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

## Handmatig Testen
Je kunt de server ook direct draaien om te zien of hij start:
```bash
uv run eds-mcp
```

## Vereisten
- Linux met GNOME
- `evolution-data-server` en de bijbehorende `-dev` pakketten.
- `python3-gi` (PyGObject bindings)
