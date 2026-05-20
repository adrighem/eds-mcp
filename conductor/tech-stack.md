# Tech Stack - eds-mcp

## Primary Languages
- **Python (3.12+)**: Main implementation of the MCP server, tools, and resources.
- **C**: Used for the custom Evolution plugin (`evolution-mcp-automation-bridge`) to handle low-level mail processing.

## Frameworks & Protocols
- **FastMCP**: High-level framework for building the MCP server.
- **Model Context Protocol (MCP)**: Standardized protocol for communication between the server and the LLM.
- **GNOME Evolution Data Server (EDS)**: The backend providing access to calendars, contacts, and mail.

## Libraries & Integration
- **PyGObject (GI)**: Introspection-based Python bindings for GObject libraries.
- **libebook / libecal**: EDS client libraries for address books and calendars.
- **libebackend**: Used for server-side EDS integration (in the C bridge).
- **Camel**: Evolution's mail library (used within the EDS context).

## Infrastructure & Tooling
- **uv**: Modern Python package and environment manager.
- **meson / ninja**: Build system for the C-based automation bridge.
- **Makefile**: Orchestrates the installation of the C plugin and environment setup.
- **hatchling**: Build backend for the Python package.

## Testing
- **pytest**: Primary testing framework.
- **pytest-asyncio**: Support for testing asynchronous Python code.
- **pytest-mock**: Mocking library for unit testing.
