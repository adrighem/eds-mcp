# Evolution Mail Automation Bridge

This optional Evolution plugin gives `eds-mcp` access to mail actions that are
not available through Evolution Data Server alone.

Evolution must be running for the bridge to work. The bridge uses your current
desktop user's D-Bus session and does not expose a network service.

## When do I need it?

You do not need the bridge to list accounts and folders, search indexed mail,
or read messages already present in Evolution's local cache.

Install it to let `eds-mcp`:

- send plain-text email
- send local attachments
- preserve reply threading headers
- move or delete messages
- mark messages read or unread
- fetch uncached bodies and attachments when bridge reads are enabled

## Install

The installer targets Debian and Ubuntu systems. It needs standard C build
tools plus Evolution development headers, and it uses `sudo` to install the
plugin into Evolution's system plugin directory.

From the `eds-mcp` repository root:

```bash
make install-bridge
```

The installer may install missing build packages, compiles the plugin, and
closes Evolution so the plugin can load cleanly. Save open drafts before
starting. Launch Evolution again after installation.

Installer output is also saved to
`/tmp/evolution_mcp_automation_bridge_install.log` for troubleshooting.

## Verify

With Evolution running, return to the repository root and run:

```bash
.venv/bin/python scripts/ping_bridge.py
```

A successful result confirms that the D-Bus service is available to the same
desktop user.

## Troubleshooting

### Build dependencies are missing

The build checks for Evolution Shell, Evolution Mail, Camel, EDataServer,
ECal, EBook, GLib, Gio, and JSON-GLib development packages through
`pkg-config`. Package names vary across distributions.

### The bridge cannot be found

- Start Evolution after installing the plugin.
- Run the bridge check from the same desktop session as Evolution.
- Confirm your distribution's Evolution plugin directory is one of the paths
  detected by the installer.
- Reinstall after upgrading Evolution if its plugin ABI or install path changed.

### Cached reads work, but mail changes fail

Cached reads happen in the MCP server process. Sending, moving, deleting, and
read-state changes require this plugin and a running Evolution process.

## D-Bus interface

- Service: `org.gnome.Evolution`
- Object path: `/org/gnome/evolution/McpAutomationBridge`
- Interface: `org.gnome.Evolution.McpAutomationBridge`

The bridge is a companion to the main [eds-mcp project](https://github.com/adrighem/eds-mcp).
