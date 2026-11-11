"""Shared calendar and EWS free-busy lookup logic for Evolution Data Server."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from .env import setup_environment

setup_environment()

from gi.repository import ECal, EDataServer, GLib, ICalGLib  # noqa: E402

from . import (  # noqa: E402
    EdsMcpError,
    ErrorCode,
    error_envelope,
    error_from_exception,
    paginated_envelope,
)
from .calendar_events import ical_time_to_local_string  # noqa: E402

logger = logging.getLogger(__name__)

FB_TYPE_MAP: dict[Any, str] = {
    ICalGLib.ParameterFbtype.BUSY: "Busy",
    ICalGLib.ParameterFbtype.BUSYTENTATIVE: "Busy (Tentative)",
    ICalGLib.ParameterFbtype.BUSYUNAVAILABLE: "Busy (Unavailable)",
    ICalGLib.ParameterFbtype.FREE: "Free",
}


def find_primary_ews_calendar() -> tuple[str | None, str | None]:
    """Find the primary EWS account calendar UID."""
    try:
        registry = EDataServer.SourceRegistry.new_sync(None)
        sources = registry.list_sources(None)
        ews_parent_uid = None
        primary_cal_uid = None

        for s in sources:
            if s.has_extension(EDataServer.SOURCE_EXTENSION_COLLECTION):
                coll = s.get_extension(EDataServer.SOURCE_EXTENSION_COLLECTION)
                if coll.get_backend_name() == "ews":
                    ews_parent_uid = s.get_uid()
                    break

        if not ews_parent_uid:
            return None, "No EWS account found to support free/busy queries."

        for s in sources:
            if s.get_parent() == ews_parent_uid and s.get_display_name() == "Calendar":
                primary_cal_uid = s.get_uid()
                break

        if not primary_cal_uid:
            return None, "Could not find primary calendar for EWS connection."

        return primary_cal_uid, None
    except (GLib.Error, RuntimeError) as e:
        logger.exception("Failed to resolve primary EWS calendar")
        return None, f"Error searching for primary EWS calendar: {e}"


async def get_free_busy_logic(
    email: str,
    days_ahead: int,
    days_back: int,
    primary_cal_uid: str,
) -> list[dict[str, Any]]:
    """Fetches free/busy information for given email address using ICalGLib."""

    def _logic() -> list[dict[str, Any]]:
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            source = registry.ref_source(primary_cal_uid)
            if not source:
                return []

            client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
            now = datetime.now()
            start_time = (now - timedelta(days=days_back)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_time = (now + timedelta(days=days_ahead)).replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            success, components = client.get_free_busy_sync(
                int(start_time.timestamp()),
                int(end_time.timestamp()),
                [email],
                None,
            )
            fb_events: list[dict[str, Any]] = []
            for comp in components:
                ical_comp = comp.get_icalcomponent()
                prop = ical_comp.get_first_property(ICalGLib.PropertyKind.FREEBUSY_PROPERTY)
                while prop:
                    fb = prop.get_freebusy()
                    if fb:
                        param = prop.get_first_parameter(ICalGLib.ParameterKind.FBTYPE_PARAMETER)
                        fb_type = FB_TYPE_MAP.get(param.get_fbtype(), "Busy") if param else "Busy"
                        fb_events.append(
                            {
                                "type": fb_type,
                                "start": ical_time_to_local_string(fb.get_start()),
                                "end": ical_time_to_local_string(fb.get_end()),
                            }
                        )
                    prop = ical_comp.get_next_property(ICalGLib.PropertyKind.FREEBUSY_PROPERTY)
            return fb_events
        except (GLib.Error, RuntimeError) as e:
            logger.exception("Failed to fetch free/busy for %s: %s", email, e)
            return []

    return await asyncio.to_thread(_logic)


async def get_shared_calendar_events_logic(
    query: str,
    days_ahead: int = 7,
    days_back: int = 0,
    limit: int = 50,
    offset: int = 0,
    *,
    get_free_busy_fn: Callable[..., Awaitable[list[dict[str, Any]]]] | None = None,
    to_thread_fn: Callable[..., Any] | None = None,
) -> str:
    """Gets free/busy information for another user using primary account's EWS connection."""
    email: str | None = query if "@" in query else None

    if not email:
        from .contacts import search_contacts_logic

        contacts_raw = await search_contacts_logic(query, limit=10)
        try:
            contacts_data = json.loads(contacts_raw)
        except (json.JSONDecodeError, TypeError):
            contacts_data = {}

        if isinstance(contacts_data, dict):
            # Support new envelope format: {"items": [{"emails": [...]}]}
            if "items" in contacts_data and isinstance(contacts_data["items"], list):
                for item in contacts_data["items"]:
                    if isinstance(item, dict):
                        for addr in item.get("emails", []):
                            if isinstance(addr, str) and addr.strip():
                                email = addr.strip()
                                break
                    if email:
                        break

            # Support legacy format: {"Book": [{"emails": [...]}]}
            if not email:
                for val in contacts_data.values():
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                for addr in item.get("emails", []):
                                    if isinstance(addr, str) and addr.strip():
                                        email = addr.strip()
                                        break
                            if email:
                                break
                    if email:
                        break

    if not email:
        return error_envelope(
            ErrorCode.NOT_FOUND,
            f"Could not find email for '{query}'.",
            hint="Verify the contact name or provide an explicit email address.",
        )

    thread_call = to_thread_fn or asyncio.to_thread
    primary_cal_uid, err_msg = await thread_call(find_primary_ews_calendar)
    if err_msg or not primary_cal_uid:
        return error_envelope(
            ErrorCode.NOT_FOUND,
            err_msg or "Could not find primary calendar for EWS connection.",
        )

    fb_call = get_free_busy_fn or get_free_busy_logic
    try:
        all_events = await fb_call(email, days_ahead, days_back, primary_cal_uid)
    except (GLib.Error, RuntimeError, EdsMcpError, OSError) as e:
        logger.exception("Failed to fetch free/busy events for %s", email)
        return error_from_exception(e)

    total = len(all_events)
    sliced = all_events[offset : offset + limit]
    return paginated_envelope(sliced, total=total, offset=offset, extra_top={"email": email})
