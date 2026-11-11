"""Thin public facade for calendar, tasks, memos, and free/busy queries."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .env import setup_environment

setup_environment()

from gi.repository import ECal, EDataServer, GLib, ICalGLib  # noqa: E402, F401

from . import (  # noqa: E402
    EdsClientError,
    ResourceNotFoundError,
    ValidationError,
    error_from_exception,
    ok_envelope,
    paginated_envelope,
)
from .calendar_events import (  # noqa: E402, F401
    SOURCE_EXT_MAP,
    _apply_vevent_fields,
    _connect_client,
    _resolve_rid,
    _run_cal_op,
    build_vevent_component,
    get_component_summary,
    get_items_logic,
    ical_time_to_local_string,
)
from .calendar_freebusy import (  # noqa: E402, F401
    find_primary_ews_calendar,
    get_free_busy_logic,
)
from .calendar_freebusy import (  # noqa: E402
    get_shared_calendar_events_logic as _impl_shared_calendar_events_logic,
)

logger = logging.getLogger(__name__)


async def list_sources_logic(source_type: ECal.ClientSourceType) -> str:
    """List all enabled sources for a given type (Calendar, Tasks, or Memos)."""

    def _logic() -> str:
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            result: list[dict[str, Any]] = []
            for source in registry.list_sources(SOURCE_EXT_MAP[source_type]):
                if source.get_enabled():
                    p_uid = source.get_parent()
                    p_src = registry.ref_source(p_uid) if p_uid else None
                    p_name = p_src.get_display_name() if p_src else None
                    result.append(
                        {
                            "uid": source.get_uid(),
                            "name": source.get_display_name(),
                            "parent_uid": p_uid,
                            "parent_name": p_name,
                        }
                    )
            return paginated_envelope(result, total=len(result), offset=0)
        except (GLib.Error, RuntimeError) as exc:
            logger.exception("Failed to list sources for %s", source_type)
            return error_from_exception(exc)

    return await asyncio.to_thread(_logic)


async def list_calendars_logic() -> str:
    """List all configured and enabled Evolution calendars."""
    return await list_sources_logic(ECal.ClientSourceType.EVENTS)


async def get_calendar_events_logic(
    days_ahead: int = 7,
    days_back: int = 0,
    query: str | None = None,
    calendar_uid: str | None = None,
    date: str | None = None,
    summary_only: bool = False,
    include_attendees: bool = False,
    max_attendees: int = 50,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Get calendar events for a date range and optional search query."""
    return await get_items_logic(
        ECal.ClientSourceType.EVENTS,
        days_ahead=days_ahead,
        days_back=days_back,
        query=query,
        uid=calendar_uid,
        date_str=date,
        summary_only=summary_only,
        include_attendees=include_attendees,
        max_attendees=max_attendees,
        limit=limit,
        offset=offset,
    )


async def list_tasks_logic() -> str:
    """List all configured and enabled Evolution task lists."""
    return await list_sources_logic(ECal.ClientSourceType.TASKS)


async def get_tasks_logic(
    days_ahead: int = 30,
    days_back: int = 30,
    query: str | None = None,
    task_list_uid: str | None = None,
    date: str | None = None,
    summary_only: bool = False,
    include_completed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Get tasks/to-dos from Evolution task lists."""
    return await get_items_logic(
        ECal.ClientSourceType.TASKS,
        days_ahead=days_ahead,
        days_back=days_back,
        query=query,
        uid=task_list_uid,
        date_str=date,
        summary_only=summary_only,
        include_completed=include_completed,
        limit=limit,
        offset=offset,
    )


async def list_memos_logic() -> str:
    """List all configured and enabled Evolution memo lists."""
    return await list_sources_logic(ECal.ClientSourceType.MEMOS)


async def get_memos_logic(
    query: str | None = None,
    memo_list_uid: str | None = None,
    summary_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Get memos/notes from Evolution memo lists."""
    return await get_items_logic(
        ECal.ClientSourceType.MEMOS,
        days_ahead=365,
        days_back=365,
        query=query,
        uid=memo_list_uid,
        summary_only=summary_only,
        limit=limit,
        offset=offset,
    )


async def get_shared_calendar_events_logic(
    query: str,
    days_ahead: int = 7,
    days_back: int = 0,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Get free/busy information for another user using primary account's EWS connection."""
    return await _impl_shared_calendar_events_logic(
        query=query,
        days_ahead=days_ahead,
        days_back=days_back,
        limit=limit,
        offset=offset,
        get_free_busy_fn=get_free_busy_logic,
        to_thread_fn=asyncio.to_thread,
    )


async def create_calendar_event_logic(
    calendar_uid: str,
    ical_data: str | None = None,
    *,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str | None = None,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """Create a calendar event from structured inputs or raw iCal."""

    def _logic() -> str:
        comp = build_vevent_component(
            summary, start, end, timezone, location, description, attendees, ical_data=ical_data
        )
        ok, new_uid = _connect_client(calendar_uid).create_object_sync(
            comp, ECal.OperationFlags.NONE, None
        )
        if not ok or not new_uid:
            raise EdsClientError("Failed to create event in calendar.")
        return ok_envelope({"status": "created", "calendar_uid": calendar_uid, "uid": new_uid})

    return await _run_cal_op("create_event", _logic)


async def delete_calendar_event_logic(
    calendar_uid: str, event_uid: str, event_rid: str | None = None
) -> str:
    """Delete a calendar event or a specific recurrence instance."""

    def _logic() -> str:
        rid, mod = _resolve_rid(event_rid)
        _connect_client(calendar_uid).remove_object_sync(
            event_uid, rid, mod, ECal.OperationFlags.NONE, None
        )
        return ok_envelope(
            {"status": "deleted", "calendar_uid": calendar_uid, "uid": event_uid, "rid": rid}
        )

    return await _run_cal_op("delete_event", _logic)


async def update_calendar_event_logic(
    calendar_uid: str,
    event_uid: str,
    event_rid: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    timezone: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    ical_data: str | None = None,
) -> str:
    """Update summary, description, times, location, or attendees of a calendar event."""

    def _logic() -> str:
        rid, mod = _resolve_rid(event_rid)
        client = _connect_client(calendar_uid)
        res = {"status": "updated", "calendar_uid": calendar_uid, "uid": event_uid, "rid": rid}
        if ical_data:
            if not (comp_raw := ICalGLib.Component.new_from_string(ical_data)):
                raise ValidationError("Invalid iCal data.")
            client.modify_object_sync(comp_raw, mod, ECal.OperationFlags.NONE, None)
            return ok_envelope(res)

        ok, icalcomp = client.get_object_sync(event_uid, rid, None)
        if not ok or not icalcomp:
            raise ResourceNotFoundError(f"Event '{event_uid}' not found.")

        comp = ECal.Component.new_from_icalcomponent(icalcomp)
        _apply_vevent_fields(comp, summary, start, end, timezone, location, description, attendees)
        client.modify_object_sync(comp.get_icalcomponent(), mod, ECal.OperationFlags.NONE, None)
        return ok_envelope(res)

    return await _run_cal_op("update_event", _logic)
