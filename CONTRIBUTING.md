# Contributing

Thanks for helping maintain `eds-mcp`. The project has two parts:

- `src/eds_mcp/`: the Python MCP server and testable domain modules.
- `evolution-mcp-automation-bridge/`: the Evolution plugin used for D-Bus mail actions.

## Local Setup

This project uses `uv` and depends on system GNOME Evolution/PyGObject packages.

```bash
uv venv --system-site-packages
source .venv/bin/activate
uv sync --all-groups
```

On Debian/Ubuntu-style systems, install the runtime pieces with:

```bash
sudo apt install evolution evolution-data-server python3-gi
```

Bridge development also needs Evolution development headers; see
`evolution-mcp-automation-bridge/README.md`.

## Common Commands

```bash
make test
make lint
make format-check
make typecheck
make lock-check
make check
```

`make test` runs the isolated Python unit suite under `tests/`. It never touches
live `~/.config/evolution` or `~/.cache/evolution` directories.

Run the bridge integration test explicitly when Evolution is running, the bridge
plugin is installed, and your Python interpreter can import `gi`:

```bash
python -m pytest evolution-mcp-automation-bridge/tests
```

## Code Layout

- `__init__.py`: shared `EdsMcpError` hierarchy and compact JSON envelope serializers.
- `server.py`: MCP resources, annotated tools, and prompts.
- `mail.py`, `mail_db.py`, `mail_cache.py`, `mail_threads.py`, `mail_actions.py`, `mail_bridge.py`: modular mail subsystem (read-only SQLite, raw/SHA-256 Camel cache, cross-folder thread assembly, quote stripping, and D-Bus mutations).
- `calendar.py`, `calendar_events.py`, `calendar_freebusy.py`: calendar, task, memo, structured `VEVENT`, and EWS free/busy subsystem.
- `contacts.py` and `documents.py`: bounded address book search and local document text extraction.
- `summary.py`: GI-free daily summary orchestration.
- `env.py`: PyGObject/EDS environment and D-Bus session discovery.

Keep every Python module under 500 lines with strict type annotations and single
responsibility.

## Maintenance Notes

- Use `uv lock --upgrade-package <package>` for dependency maintenance.
- Keep MCP responses compact: strip `None`, empty strings, and empty lists, and
  use `paginated_envelope` / `error_envelope` contracts.
- Do not edit raw Evolution configuration files. Use EDS APIs and the bridge.
