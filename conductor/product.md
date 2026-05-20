# Product Definition - eds-mcp

## Product Vision
To provide a seamless bridge between LLM-based agents (like Gemini) and the local GNOME Evolution Data Server (EDS), enabling secure and efficient management of personal information (calendars, contacts, and mail) directly from the Linux desktop.

## Target Audience
- Linux users who use GNOME Evolution or EWS-compatible services.
- Developers looking to automate personal workflows using MCP.
- Power users who want LLM assistance for scheduling, contact management, and email triaging.

## Core Features
- **Calendar Management**: Read, create, update, and delete events across local and remote (EWS/Office365) calendars.
- **Contact Management**: Search and retrieve detailed contact information from the Evolution address book.
- **Mail Integration**: Retrieve recent emails and perform actions like archiving or deleting.
- **Automation Bridge**: A custom C-based Evolution plugin (`evolution-mcp-automation-bridge`) that enables destructive actions and advanced features otherwise inaccessible via standard EDS APIs.
- **Proactive Insights**: Daily briefings and contact dossiers generated from local data.

## Success Metrics
- Full coverage of EDS calendar, contact, and mail APIs.
- Reliable operation of the C-based automation bridge.
- Minimal latency in data retrieval and processing.
- Robust error handling for offline or misconfigured EDS accounts.
