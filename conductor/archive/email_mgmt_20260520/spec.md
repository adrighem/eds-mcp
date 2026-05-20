# Track Specification: email_mgmt_20260520

## Description
Implement tools for moving and deleting emails in GNOME Evolution via the Evolution MCP Automation Bridge.

## Scope
- Integrate with the existing C-based Evolution plugin (`evolution-mcp-automation-bridge`).
- Implement the `move_email` MCP tool.
- Implement the `delete_email` MCP tool.
- Ensure robust error handling and D-Bus communication between Python and the Evolution plugin.
- Add comprehensive tests for both success and failure scenarios.

## Technical Details
- **IPC**: Communication with Evolution will be handled via D-Bus (as established by the bridge plugin).
- **Python Implementation**: Use `PyGObject` to communicate with the bridge.
- **Tools**:
    - `move_email(account_uid, message_uid, source_folder, dest_folder)`
    - `delete_email(account_uid, message_uid, folder_name)`

## Success Criteria
- Emails can be moved between folders reliably.
- Emails can be deleted (moved to Trash or permanently deleted as per Evolution settings).
- Correct error messages are returned if the message or folder is not found.
- Test coverage for new tools is >80%.
