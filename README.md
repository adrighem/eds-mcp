# Evolution MCP Automation Bridge

This is an Evolution EPlugin that exposes a D-Bus interface for programmatic control of the Evolution Mail client. It is primarily designed to act as a bridge for the **EDS Model Context Protocol (MCP)** server, allowing AI agents to perform actions like moving or deleting messages directly through the Evolution UI state.

## Features

- **MoveMessage**: Move emails between folders within an account.
- **DeleteMessage**: Securely mark messages for deletion and synchronize the folder.
- **D-Bus Interface**: Exposed at `org.gnome.Evolution.McpAutomationBridge`.

## Installation

### Prerequisites

You will need Evolution development headers and standard build tools:

\`\`\`bash
sudo apt install build-essential pkg-config cmake evolution-dev libemail-engine-dev libedataserver1.2-dev libcamel1.2-dev
\`\`\`

### Build and Install

Use the provided install script:

\`\`\`bash
cd scripts
./install.sh
\`\`\`

This will:
1. Compile the plugin using CMake.
2. Install the shared library to Evolution's plugin directory (e.g., \`/usr/lib/evolution/plugins\`).
3. Force-shutdown Evolution to ensure the new plugin is loaded on next start.

## Usage

The plugin registers a D-Bus object at:
- **Service**: \`org.gnome.Evolution\`
- **Path**: \`/org/gnome/evolution/McpAutomationBridge\`
- **Interface**: \`org.gnome.Evolution.McpAutomationBridge\`

### Example: Delete a message via busctl

\`\`\`bash
busctl --user call org.gnome.Evolution /org/gnome/evolution/McpAutomationBridge org.gnome.Evolution.McpAutomationBridge DeleteMessage sss "account_uid" "message_uid" "folder_name"
\`\`\`

## Integration with EDS MCP

This bridge is required for the full functionality of the [eds-mcp](https://github.com/adrighem/eds-mcp) server.
