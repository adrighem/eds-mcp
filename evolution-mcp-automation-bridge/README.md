# Evolution Mail Automation Bridge

This optional Evolution plugin gives `eds-mcp` access to mail actions that are
not available through Evolution Data Server alone.

Evolution must be running for the bridge to work. The bridge uses your current
desktop user's D-Bus session and does not expose a network service.

## When do I need it?

You do not need the bridge to list accounts and folders, search indexed mail,
reconstruct cached threads, or read messages already present in Evolution's
local `CamelDataCache`.

Install it to let `eds-mcp`:

- send plain-text email with attachments and automatic SMTP `Sent` persistence
- save drafts to the account's configured Drafts folder (`SaveDraft`)
- open interactive Evolution composer windows for human review (`OpenComposer`)
- preserve `In-Reply-To` and `References` reply threading headers
- move, delete, or mark messages read/unread (with case-insensitive folder fallback)
- automatically fetch uncached bodies and attachments when Evolution is running

## Install

From the `eds-mcp` repository root:

```bash
make install-bridge
```

The installer compiles the plugin, installs it into Evolution's plugin
directory, and closes Evolution so the plugin can load cleanly. Save open drafts
before starting. Launch Evolution again after installation.

Installer output is saved to `/tmp/evolution_mcp_automation_bridge_install.log`.

## Verify

With Evolution running, return to the repository root and run:

```bash
.venv/bin/python scripts/ping_bridge.py
```

## D-Bus interface

- Service: `org.gnome.Evolution`
- Object path: `/org/gnome/evolution/McpAutomationBridge`
- Interface: `org.gnome.Evolution.McpAutomationBridge`
- Methods: `GetVersion`, `MoveMessage`, `DeleteMessage`, `MarkAsRead`, `GetMessage`,
  `ListAttachments`, `SaveAttachment`, `SendMail`, `SendMailWithAttachments`,
  `SaveDraft`, `OpenComposer`

## Version information

Each build embeds the git commit (`git describe --always --dirty`) and the UTC
build date. CMake re-configures when HEAD, the git index or the plugin source
changes, so both values stay current. They appear in:

- The plugin description in Evolution's plugin manager.
- The Evolution log line printed when the plugin loads.
- The `GetVersion` D-Bus method, returning `(git_commit, build_date)`:

```bash
gdbus call --session --dest org.gnome.Evolution \
  --object-path /org/gnome/evolution/McpAutomationBridge \
  --method org.gnome.Evolution.McpAutomationBridge.GetVersion
```

`scripts/ping_bridge.py` in the main project prints the same values.

The bridge is a companion to the main [eds-mcp project](https://github.com/adrighem/eds-mcp).
