# Maintainer Context

## Project

`eds-mcp` is a Python 3.12+ MCP server for GNOME Evolution Data Server. It exposes local calendars, contacts, mail, and document extraction to agent clients while relying on system EDS/GNOME dependencies and an optional C automation bridge for destructive mail actions.

## Priorities

- Keep local personal-data access safe and explicit.
- Preserve context-efficient MCP responses: compact projections, sensible limits, and structured errors.
- Keep dependency updates low-risk by using `uv` resolver output and running the Python test suite.
- Treat external PRs as signals; implement maintenance changes locally after verification.

## Tone

Concise, practical, and user-focused. Public responses should state what changed, why it matters, and what was verified.

