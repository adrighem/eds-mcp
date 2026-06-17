# Contributing

Thanks for helping maintain `eds-mcp`. The project has two parts:

- `src/eds_mcp/`: the Python MCP server and testable application logic.
- `evolution-mcp-automation-bridge/`: the Evolution plugin used for D-Bus mail actions.

## Local Setup

This project uses `uv` and depends on system GNOME Evolution/PyGObject packages.

```bash
uv venv --system-site-packages
source .venv/bin/activate
uv sync
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
make lock-check
make check
```

`make test` runs the default Python unit suite under `tests/`. It intentionally
does not collect the live bridge D-Bus integration test.

Run the bridge integration test explicitly when Evolution is running, the bridge
plugin is installed, and your Python interpreter can import `gi`:

```bash
python -m pytest evolution-mcp-automation-bridge/tests
```

## Code Layout

- `server.py` registers MCP resources, tools, and prompts.
- `calendar.py`, `contacts.py`, `mail.py`, and `documents.py` contain domain logic.
- `summary.py` holds daily-summary orchestration that can be tested without GI.
- `env.py` sets up system paths for PyGObject and EDS bindings.

Keep new orchestration code outside `server.py` when possible. Small pure-Python
helpers are much easier to test and review than logic embedded in MCP decorators.

## Maintenance Notes

- Use `uv lock --upgrade-package <package>` for dependency maintenance.
- Treat Dependabot PRs as signals; apply and verify the change locally.
- Keep MCP responses compact: avoid returning verbose internal EDS fields, empty
  values, or unbounded document/email content.
- Do not edit raw Evolution configuration files. Use EDS APIs and the bridge.
