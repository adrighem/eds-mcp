# Evolution Data Server MCP

[![CI](https://github.com/adrighem/eds-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/adrighem/eds-mcp/actions/workflows/ci.yml)

Connect an MCP-compatible assistant to calendars, tasks, memos, contacts, and
mail already synced by [GNOME Evolution](https://gitlab.gnome.org/GNOME/evolution)
on Linux.

`eds-mcp` uses Evolution Data Server instead of asking for separate provider
credentials. It works with accounts supported by Evolution, including Microsoft
365 and Exchange accounts configured through Evolution EWS (supporting both raw
IMAP UIDs and SHA-256 hashed `CamelDataCache` filenames).

> [!IMPORTANT]
> The server reads personal data from your local Evolution profile and returns
> it to your MCP client. Your client and model decide where that returned data
> is processed. Use only clients you trust.

## What can it do?

- **Calendars:** Browse calendars, find recurring events with compact attendee
  summaries, view a day or date range, create or edit events using structured
  fields or raw iCalendar `VEVENT` data, delete events, and check EWS free/busy
  information.
- **Tasks and memos:** Discover enabled lists, filter incomplete tasks by
  default, paginate items, and build a focused view for today.
- **Contacts:** Search people by name or email across enabled Evolution address
  books with bounded pagination.
- **Mail:** Browse accounts and case-insensitive canonical folders, reconstruct
  chronological cross-folder threads with automatic reply-quote stripping
  (`get_email_thread`), search with Unicode case-folding plus sender/recipient,
  date, unread, and bounded body filters (`search_emails`), read bodies and
  attachments, save drafts (`create_draft`), open interactive Evolution composer
  windows (`open_composer`), and send or manage mail.
- **Daily overview:** Combine today's events, tasks, and recent inbox messages
  into one summary.
- **Documents:** Extract text from downloaded PDF, DOCX, XLSX, TXT, Markdown,
  CSV, and JSON files.

Once connected, try prompts such as:

- "What is on my calendar today?"
- "Summarize the full email thread with Ada across Inbox and Sent Items."
- "Create a draft reply to that thread or open it in Evolution for review."
- "Download the invoice attachment and summarize it."
- "When is my colleague free this week?"

## Before you start

You need:

- Linux with a user D-Bus session
- Python 3.12 or newer
- Evolution and Evolution Data Server
- PyGObject bindings for your distribution's Python
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

On Debian or Ubuntu, start with:

```bash
sudo apt install evolution evolution-data-server python3-gi
```

For Microsoft 365 or Exchange, also install `evolution-ews`. Add the account in
Evolution, enable the calendars, address books, and mail folders you want, then
let Evolution finish its first sync.

## Quick start

Clone the project and create a virtual environment that can see your system GI
bindings:

```bash
git clone https://github.com/adrighem/eds-mcp.git
cd eds-mcp
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --locked --no-dev
```

Add the installed executable to your MCP client's server configuration:

```json
{
  "mcpServers": {
    "evolution": {
      "command": "/absolute/path/to/eds-mcp/.venv/bin/eds-mcp"
    }
  }
}
```

## Optional mail automation bridge

Calendar changes use EDS directly. Mail listing, search, thread reconstruction,
and cached body/attachment reads work without the bridge by reading Evolution's
local read-only SQLite index and `CamelDataCache`.

Install the bridge when you want to:

- send email or threaded replies (with automatic SMTP `Sent` folder persistence)
- save server/local drafts (`create_draft`)
- open interactive Evolution composer windows for human review (`open_composer`)
- attach local files to outgoing email or drafts
- move, delete, or mark messages read/unread
- automatically fetch uncached message content when Evolution is running

From the repository root, run:

```bash
make install-bridge
```

Verify the running bridge with:

```bash
.venv/bin/python scripts/ping_bridge.py
```

See the [bridge guide](evolution-mcp-automation-bridge/README.md) for details.

> [!WARNING]
> Mail and calendar write tools act immediately when your MCP client calls
> them. Prefer `create_draft` or `open_composer` when human review is desired
> before sending mail, and enable tool approval in your MCP client.

## Response contracts and limits

- List tools return compact JSON envelopes:
  `{"items":[...],"meta":{"returned":...,"total":...,"offset":...,"has_more":...}}`.
- Errors return structured JSON:
  `{"error":{"code":"...","message":"...","retryable":false,"hint":"..."}}`.
- When `org.gnome.Evolution.McpAutomationBridge` is active on session D-Bus,
  uncached mail reads fall back to the bridge automatically and tag responses
  with `"source":"bridge"`. Set `EDS_MCP_ENABLE_EVOLUTION_BRIDGE_READS=0` to
  force offline-only cache reads.
- `get_email_body` defaults to 10,000 characters; `get_email_thread` strips
  quoted reply history by default and caps per-message text at 3,000 characters.
- Outgoing mail, drafts, and composer windows accept at most 10 attachments and
  20 MiB total.
- Document parsing accepts files up to 5 MiB and returns at most 30,000
  characters.

## Troubleshooting

### Only `system_status` is available

The Python process cannot load PyGObject or the EDS introspection libraries.
Use your distribution's Python when creating the virtual environment and make
sure Evolution, EDS, and `python3-gi` are installed.

### Calendars, contacts, or folders are missing

Open Evolution, enable the source in its sidebar, and let it finish syncing.
The server only discovers enabled EDS sources.

### An email body or attachment is not found

Open Evolution (with the bridge installed) so uncached items fetch on demand, or
sync the folder in Evolution for offline cache access.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, module layout,
linting, typechecking, tests, and bridge integration checks.

Licensed under the [GPL-3.0-only License](LICENSE).
