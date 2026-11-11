from __future__ import annotations

import importlib
import json
from typing import Any
from unittest.mock import patch

import pytest

import eds_mcp.server
from eds_mcp.server import mcp


@pytest.mark.asyncio
async def test_registered_tools_presence() -> None:
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "get_email_thread",
        "create_draft",
        "open_composer",
        "get_emails",
        "search_emails",
        "get_email_body",
        "send_email",
        "move_email",
        "delete_email",
        "mark_email_as_read",
        "get_calendar_events",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "search_contacts",
        "read_document",
        "get_daily_summary",
    }
    assert expected_tools.issubset(tool_names)


@pytest.mark.asyncio
async def test_registered_resources() -> None:
    resources = await mcp.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    expected_resources = {
        "eds://calendars",
        "eds://tasks",
        "eds://memos",
        "eds://mail/accounts",
    }
    assert expected_resources.issubset(resource_uris)

    templates = await mcp.list_resource_templates()
    template_uris = {t.uriTemplate for t in templates}
    assert "eds://mail/{account_uid}/folders" in template_uris


@pytest.mark.asyncio
async def test_tool_annotations() -> None:
    tools_list = await mcp.list_tools()
    tools = {t.name: t for t in tools_list}

    # Read-only local tools
    read_only_local = [
        "get_emails",
        "search_emails",
        "get_email_thread",
        "get_calendar_events",
        "search_contacts",
        "read_document",
    ]
    for name in read_only_local:
        ann = tools[name].annotations
        assert ann is not None, f"Annotations missing on {name}"
        assert ann.readOnlyHint is True
        assert ann.destructiveHint is False
        assert ann.openWorldHint is False

    # Remote FreeBusy tool
    remote_ann = tools["get_shared_calendar_events"].annotations
    assert remote_ann is not None
    assert remote_ann.readOnlyHint is True
    assert remote_ann.openWorldHint is True

    # Idempotent write tools
    idempotent_writes = ["mark_email_as_read", "update_calendar_event"]
    for name in idempotent_writes:
        ann = tools[name].annotations
        assert ann is not None, f"Annotations missing on {name}"
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False
        assert ann.idempotentHint is True

    # Non-idempotent write tools
    non_idempotent_writes = [
        "create_draft",
        "open_composer",
        "create_calendar_event",
    ]
    for name in non_idempotent_writes:
        ann = tools[name].annotations
        assert ann is not None, f"Annotations missing on {name}"
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False
        assert ann.idempotentHint is False

    # Destructive local tools
    destructive_tools = ["delete_email", "delete_calendar_event"]
    for name in destructive_tools:
        ann = tools[name].annotations
        assert ann is not None, f"Annotations missing on {name}"
        assert ann.destructiveHint is True

    # Send external email tool
    send_ann = tools["send_email"].annotations
    assert send_ann is not None
    assert send_ann.destructiveHint is True
    assert send_ann.openWorldHint is True


@pytest.mark.asyncio
async def test_folder_name_schema_defaults() -> None:
    tools_list = await mcp.list_tools()
    tools = {t.name: t for t in tools_list}

    folder_default_tools = [
        "get_emails",
        "get_email_body",
        "get_email_thread",
        "list_attachments",
        "mark_email_as_read",
        "delete_email",
    ]
    for name in folder_default_tools:
        schema = tools[name].inputSchema
        props = schema.get("properties", {})
        assert "folder_name" in props, f"Missing folder_name property in {name}"
        assert props["folder_name"].get("default") == "Inbox", f"Expected 'Inbox' default in {name}"


@pytest.mark.asyncio
async def test_create_calendar_event_schema_properties() -> None:
    tools_list = await mcp.list_tools()
    tools = {t.name: t for t in tools_list}
    schema = tools["create_calendar_event"].inputSchema
    props = schema.get("properties", {})

    expected_props = [
        "summary",
        "start",
        "end",
        "timezone",
        "location",
        "description",
        "attendees",
        "ical_data",
    ]
    for prop in expected_props:
        assert prop in props, f"Property '{prop}' missing in create_calendar_event schema"


@pytest.mark.asyncio
async def test_degraded_mode_missing_gi_dependencies() -> None:
    with patch("eds_mcp.env.check_gi_dependencies", return_value=False):
        importlib.reload(eds_mcp.server)
        try:
            tools = await eds_mcp.server.mcp.list_tools()
            tool_names = [t.name for t in tools]
            assert "system_status" in tool_names

            raw_result: Any = await eds_mcp.server.mcp.call_tool("system_status", {})
            content = raw_result[0] if isinstance(raw_result, tuple) else raw_result
            first_item = content[0] if isinstance(content, (list, tuple)) else content
            raw_text = getattr(first_item, "text", str(first_item))
            payload = json.loads(raw_text)
            assert payload["error"]["code"] == "DEPENDENCY_MISSING"
        finally:
            importlib.reload(eds_mcp.server)
