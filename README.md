# Evolution Data Server MCP

[![CI](https://github.com/adrighem/eds-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/adrighem/eds-mcp/actions/workflows/ci.yml)

Connect an MCP-compatible assistant to calendars, tasks, memos, contacts, and
mail already synced by [GNOME Evolution](https://gitlab.gnome.org/GNOME/evolution)
on Linux.

`eds-mcp` uses Evolution Data Server instead of asking for separate provider
credentials. It works with accounts supported by Evolution, including Microsoft
365 and Exchange accounts configured through Evolution EWS.

> [!IMPORTANT]
> The server reads personal data from your local Evolution profile and returns
> it to your MCP client. Your client and model decide where that returned data
> is processed. Use only clients you trust.

## What can it do?

- **Calendars:** Browse calendars, find recurring events, view a day or date
  range, create or edit events, delete events, and check EWS free/busy
  information.
- **Tasks and memos:** Discover enabled lists, search items, and build a focused
  view for today.
- **Contacts:** Find people by name or email across enabled Evolution address
  books.
- **Mail:** Browse accounts and folders, list or search messages, read cached
  bodies, work with attachments, and optionally send or manage mail.
- **Daily overview:** Combine today's events, tasks, and recent inbox messages
  into one summary.
- **Documents:** Extract text from downloaded PDF, DOCX, XLSX, TXT, Markdown,
  CSV, and JSON files.

Once connected, try prompts such as:

- "What is on my calendar today?"
- "Show my open tasks and important recent email."
- "Find Ada's email address."
- "Download the invoice attachment and summarize it."
- "When is my colleague free this week?"

## Before you start

You need:

- Linux with a user D-Bus session
- Python 3.12 or newer
- Evolution and Evolution Data Server
- PyGObject bindings for your distribution's Python
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

The documented installation path targets Debian and Ubuntu. Other Linux
distributions can work with equivalent Evolution, EDS, and GI packages.

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

Add the installed executable to your MCP client's server configuration. The
configuration file location varies by client, but the common JSON shape is:

```json
{
  "mcpServers": {
    "evolution": {
      "command": "/absolute/path/to/eds-mcp/.venv/bin/eds-mcp"
    }
  }
}
```

Replace the example with the real absolute path, restart your MCP client, and
ask it what is on your calendar today.

To check startup manually:

```bash
.venv/bin/eds-mcp
```

The server waits for MCP messages on standard input, so silence is normal. Any
startup error appears on standard error. Press `Ctrl+C` to stop it.

## Optional mail automation bridge

Calendar changes use EDS directly. Basic mail listing and search also work
without the bridge by reading Evolution's local index and message cache.

Install the bridge when you want to:

- send email or threaded replies
- attach local files to outgoing email
- move or delete messages
- mark messages read or unread
- retrieve uncached message content through Evolution's process

From the repository root, run:

```bash
make install-bridge
```

The installer is Debian/Ubuntu-oriented. It may install build packages with
`sudo`, builds a native Evolution plugin, installs it into the system plugin
directory, and closes Evolution so the new plugin can load. Save any drafts
first, then launch Evolution again.

Verify the running bridge with:

```bash
.venv/bin/python scripts/ping_bridge.py
```

See the [bridge guide](evolution-mcp-automation-bridge/README.md) for details.

> [!WARNING]
> Mail and calendar write tools act immediately when your MCP client calls
> them. The server has no confirmation screen. Enable tool approval in your
> client and review send, move, delete, and calendar-change requests carefully.

## Limits and data behavior

- Mail search uses Evolution's cached subject, sender, and preview metadata. It
  does not search complete message bodies.
- Full bodies and attachments normally require the message to be synced in
  Evolution's local cache. Open or sync a missing message in Evolution first.
- Email body output is limited to 10,000 characters.
- Outgoing mail accepts at most 10 attachments and 20 MiB total.
- Document parsing accepts files up to 5 MiB and returns at most 30,000
  characters.
- Downloaded attachments are written to a temporary directory.
- `read_document` can read any supported local file available to the server
  process. Do not expose this server to an untrusted MCP client.

## Troubleshooting

### Only `system_status` is available

The Python process cannot load PyGObject or the EDS introspection libraries.
Use your distribution's Python when creating the virtual environment and make
sure Evolution, EDS, and `python3-gi` are installed.

### Calendars, contacts, or folders are missing

Open Evolution, enable the source in its sidebar, and let it finish syncing.
The server only discovers enabled EDS sources.

### An email body or attachment is not found

Open or sync that message in Evolution so it enters the local cache. Advanced
users can opt into bridge-based reads by setting
`EDS_MCP_ENABLE_EVOLUTION_BRIDGE_READS=1` for the MCP server.

### Sending or changing mail fails

Make sure Evolution is running, the automation bridge is installed, and the
bridge check above succeeds.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, project layout,
tests, and bridge integration checks.

Licensed under the [MIT License](LICENSE).
