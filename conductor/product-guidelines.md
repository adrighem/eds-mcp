# Product Guidelines - eds-mcp

## Prose Style
- **Tone**: Technical, professional, and clear.
- **Voice**: Active voice where possible.
- **Audience**: Developers and power users.
- **Clarity**: Avoid unnecessary jargon; explain project-specific terms (like EDS, EWS, and MCP) if needed.

## UX Principles for MCP
- **Minimalism**: Return only the data necessary for the LLM to complete its task.
- **Safety**: Require explicit confirmation for destructive actions (delete, move).
- **Feedback**: Provide informative error messages when EDS is unavailable or data retrieval fails.
- **Consistency**: Use consistent naming conventions for tools and resources.

## Design Patterns
- **Resource Discovery**: Use a hierarchical URI structure for EDS data (e.g., `eds://mail/{account}/folders`).
- **Tool Design**: Tools should be idempotent where possible and handle long-running operations asynchronously.
- **Error Handling**: Standardize error codes and responses across all MCP endpoints.

## Hybrid Architecture Guidelines (Python + C)
- **Plugin Management**: Ensure the `evolution-mcp-automation-bridge` is correctly installed and version-synced with the Python MCP server.
- **D-Bus/IPC Protocols**: Clearly document the interface between the Python server and the C plugin.
- **Error Propagation**: Ensure errors from the C plugin are gracefully surfaced through the MCP interface.

## Documentation Standards
- **README**: Maintain a comprehensive README with installation instructions and feature lists.
- **Code Comments**: Use inline comments for complex logic, especially in the C automation bridge.
- **Type Hinting**: Use Python type hints for all tool parameters and return values.
