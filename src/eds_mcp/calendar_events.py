"""Local/EDS ECalClient event, task, and memo queries plus structured VEVENT creation/updates."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from .env import setup_environment

setup_environment()

from gi.repository import ECal, EDataServer, GLib, ICalGLib  # noqa: E402

from . import (  # noqa: E402
    EdsMcpError,
    ErrorCode,
    ResourceNotFoundError,
    ValidationError,
    error_envelope,
    error_from_exception,
    paginated_envelope,
)

logger = logging.getLogger(__name__)

PARTSTAT_MAP: dict[Any, str] = {
    ICalGLib.ParameterPartstat.ACCEPTED: "ACCEPTED",
    ICalGLib.ParameterPartstat.DECLINED: "DECLINED",
    ICalGLib.ParameterPartstat.TENTATIVE: "TENTATIVE",
    ICalGLib.ParameterPartstat.DELEGATED: "DELEGATED",
    ICalGLib.ParameterPartstat.NEEDSACTION: "NEEDS-ACTION",
    ICalGLib.ParameterPartstat.COMPLETED: "COMPLETED",
    ICalGLib.ParameterPartstat.INPROCESS: "IN-PROCESS",
}
SOURCE_EXT_MAP: dict[ECal.ClientSourceType, str] = {
    ECal.ClientSourceType.EVENTS: EDataServer.SOURCE_EXTENSION_CALENDAR,
    ECal.ClientSourceType.TASKS: EDataServer.SOURCE_EXTENSION_TASK_LIST,
    ECal.ClientSourceType.MEMOS: EDataServer.SOURCE_EXTENSION_MEMO_LIST,
}


class _ItemFilter(NamedTuple):
    is_task: bool
    query_cf: str | None
    user_emails: set[str]
    include_attendees: bool
    max_attendees: int
    include_completed: bool


def _strip_mailto(value: str) -> str:
    return (value[7:] if value.lower().startswith("mailto:") else value).strip()


def ical_time_to_local_string(itt: ICalGLib.Time | None) -> str:
    """Convert ICalTime object to local ISO 8601 time string."""
    if not itt:
        return "Unknown"
    try:
        zone = None if itt.is_utc() else itt.get_timezone()
        ts = itt.as_timet_with_zone(zone) if zone else itt.as_timet()
        return datetime.fromtimestamp(ts).astimezone().isoformat()
    except (GLib.Error, ValueError, OverflowError, OSError):
        return str(itt.as_ical_string())


def get_component_summary(comp: Any) -> str:
    """Extract human-readable summary from calendar/task/memo component."""
    try:
        obj = comp.get_summary()
        if not obj:
            return "No Summary"
        for attr in ("get_value", "get_value_as_string"):
            if hasattr(obj, attr):
                return str(getattr(obj, attr)())
        return str(obj)
    except (GLib.Error, AttributeError, ValueError):
        return "Error extracting summary"


def _resolve_rid(event_rid: str | None) -> tuple[str | None, ECal.ObjModType]:
    rid = None if event_rid in ("00000000T000000", "") else event_rid
    return rid, (ECal.ObjModType.THIS if rid else ECal.ObjModType.ALL)


def _parse_date_or_dt(dt_str: str) -> tuple[datetime, bool]:
    if len(dt_str) == 10 and "T" not in dt_str:
        return datetime.strptime(dt_str, "%Y-%m-%d"), True
    return datetime.fromisoformat(dt_str), False


def _parse_comparable_dt(dt_str: str) -> datetime:
    dt, _ = _parse_date_or_dt(dt_str)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _parse_iso_datetime(dt_str: str, tz_name: str | None = None) -> ECal.ComponentDateTime:
    itt = ICalGLib.Time.new_null_time()
    dt, is_date = _parse_date_or_dt(dt_str)
    if is_date:
        itt.set_date(dt.year, dt.month, dt.day)
        itt.set_is_date(True)
        return ECal.ComponentDateTime.new(itt, None)

    itt.set_is_date(False)
    is_utc = dt.tzinfo is not None or bool(tz_name and tz_name.upper() == "UTC")
    target = dt.astimezone(UTC) if dt.tzinfo is not None else dt
    itt.set_date(target.year, target.month, target.day)
    itt.set_time(target.hour, target.minute, target.second)
    if is_utc:
        itt.set_timezone(ICalGLib.Timezone.get_utc_timezone())
        return ECal.ComponentDateTime.new(itt, "UTC")
    return ECal.ComponentDateTime.new(itt, tz_name)


def _make_attendees_list(emails: list[str]) -> list[ECal.ComponentAttendee]:
    out: list[ECal.ComponentAttendee] = []
    for raw in emails:
        if clean := raw.strip():
            att = ECal.ComponentAttendee.new()
            att.set_value(clean if clean.lower().startswith("mailto:") else f"mailto:{clean}")
            att.set_partstat(ICalGLib.ParameterPartstat.NEEDSACTION)
            out.append(att)
    return out


def _apply_vevent_fields(
    ec: ECal.Component,
    summary: str | None,
    start: str | None,
    end: str | None,
    timezone: str | None,
    location: str | None,
    description: str | None,
    attendees: list[str] | None,
) -> None:
    if summary is not None:
        ec.set_summary(ECal.ComponentText.new(summary, None))
    if description is not None:
        ec.set_descriptions([ECal.ComponentText.new(description, None)])
    if location is not None:
        ec.set_location(location)
    if start is not None:
        ec.set_dtstart(_parse_iso_datetime(start, timezone))
    if end is not None:
        ec.set_dtend(_parse_iso_datetime(end, timezone))
    if attendees is not None:
        ec.set_attendees(_make_attendees_list(attendees))
    ec.commit_sequence()


def build_vevent_component(
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str | None = None,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    *,
    ical_data: str | None = None,
) -> ICalGLib.Component:
    """Build RFC 5545 VEVENT ICalGLib.Component from structured inputs or raw ical_data."""
    if ical_data:
        try:
            comp = ICalGLib.Component.new_from_string(ical_data)
        except (TypeError, GLib.Error, ValueError) as exc:
            raise ValidationError(f"Invalid iCal data: {exc}") from exc
        if not comp:
            raise ValidationError("Invalid iCal data.")
        return comp

    if not summary or not start or not end:
        raise ValidationError("summary, start, and end are required to create an event.")
    try:
        if _parse_comparable_dt(end) < _parse_comparable_dt(start):
            raise ValidationError("Event end must be greater than or equal to start.")
    except ValueError as exc:
        raise ValidationError(f"Invalid datetime format: {exc}") from exc

    ec = ECal.Component.new()
    ec.set_new_vtype(ECal.ComponentVType.EVENT)
    ec.set_uid(str(uuid.uuid4()))
    _apply_vevent_fields(
        ec,
        summary,
        start,
        end,
        timezone,
        location or None,
        description or None,
        attendees if attendees else None,
    )
    return ec.get_icalcomponent()


def _get_user_mail_identities(registry: EDataServer.SourceRegistry) -> set[str]:
    user_emails: set[str] = set()
    ext_name = EDataServer.SOURCE_EXTENSION_MAIL_IDENTITY
    try:
        for src in registry.list_sources(ext_name):
            if src.get_enabled() and src.has_extension(ext_name):
                if addr := src.get_extension(ext_name).get_address():
                    user_emails.add(addr.strip().lower())
    except (GLib.Error, RuntimeError):
        logger.debug("Could not query mail identities for self-attendee matching.")
    return user_emails


def _connect_client(calendar_uid: str) -> ECal.Client:
    source = EDataServer.SourceRegistry.new_sync(None).ref_source(calendar_uid)
    if not source:
        raise ResourceNotFoundError(f"Calendar '{calendar_uid}' not found.")
    return ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)


def _extract_component_item(
    comp: Any, start: Any, end: Any, s_name: str, s_uid: str, flt: _ItemFilter
) -> dict[str, Any] | None:
    summary = get_component_summary(comp)
    if flt.query_cf and flt.query_cf not in summary.lower():
        return None
    pc_prop = comp.get_first_property(ICalGLib.PropertyKind.PERCENTCOMPLETE_PROPERTY)
    if flt.is_task and not flt.include_completed:
        stat_p = comp.get_first_property(ICalGLib.PropertyKind.STATUS_PROPERTY)
        done = ICalGLib.PropertyStatus.COMPLETED
        if (
            getattr(comp, "get_status", lambda: None)() == done
            or (stat_p and stat_p.get_status() == done)
            or (pc_prop and pc_prop.get_percentcomplete() == 100)
        ):
            return None

    rid_val = comp.get_recurrenceid()
    rid_raw = rid_val.as_ical_string() if rid_val else None
    s_str, e_str = ical_time_to_local_string(start), ical_time_to_local_string(end)
    item: dict[str, Any] = {
        "uid": comp.get_uid(),
        "summary": summary.strip() if summary else "",
        "calendar": s_name,
        "calendar_uid": s_uid,
        "start": s_str,
    }
    if rid_raw and rid_raw != "00000000T000000":
        item["rid"] = rid_raw
    if s_str != e_str:
        item["end"] = e_str
    if isinstance(loc := getattr(comp, "get_location", lambda: None)(), str) and loc.strip():
        item["location"] = loc.strip()

    org_prop = comp.get_first_property(ICalGLib.PropertyKind.ORGANIZER_PROPERTY)
    if org_prop and isinstance(org_val := org_prop.get_organizer(), str):
        if cleaned_org := _strip_mailto(org_val):
            item["organizer"] = cleaned_org

    att_list: list[dict[str, str]] = []
    self_partstat: str | None = None
    att_prop = comp.get_first_property(ICalGLib.PropertyKind.ATTENDEE_PROPERTY)
    while att_prop:
        if isinstance(raw_email := att_prop.get_attendee(), str) and raw_email:
            email = _strip_mailto(raw_email)
            cn = att_prop.get_first_parameter(ICalGLib.ParameterKind.CN_PARAMETER)
            cn_val = cn.get_cn() if cn else None
            p_p = att_prop.get_first_parameter(ICalGLib.ParameterKind.PARTSTAT_PARAMETER)
            st = PARTSTAT_MAP.get(p_p.get_partstat(), "NEEDS-ACTION") if p_p else "NEEDS-ACTION"
            if email.lower() in flt.user_emails:
                self_partstat = st
            att_list.append(
                {"email": email, "name": cn_val if isinstance(cn_val, str) else email, "status": st}
            )
        att_prop = comp.get_next_property(ICalGLib.PropertyKind.ATTENDEE_PROPERTY)

    if self_partstat:
        item["self_partstat"] = self_partstat
    if att_list:
        item["attendee_count"] = len(att_list)
        if flt.include_attendees:
            item["attendees"] = att_list[: flt.max_attendees]
            if len(att_list) > flt.max_attendees:
                item["attendees_truncated"] = True
    if flt.is_task and pc_prop:
        item["pc"] = pc_prop.get_percentcomplete()
    return item


def _format_summary_markdown(grouped: dict[str, list[dict[str, Any]]], is_task: bool) -> str:
    if not grouped:
        return "No items found for this period."
    out: list[str] = []
    for s_name, items in grouped.items():
        out.append(f"### {s_name}")
        for it in items:
            try:
                t_s = datetime.fromisoformat(it["start"]).strftime("%H:%M")
                if "end" in it:
                    t_s += f" - {datetime.fromisoformat(it['end']).strftime('%H:%M')}"
            except (ValueError, TypeError, KeyError):
                t_s = it.get("start", "")
            desc = (
                f"{it['summary']} ({it['pc']}% complete)"
                if is_task and "pc" in it
                else it["summary"]
            )
            out.append(f"* **{t_s}**: {desc}")
        out.append("")
    return "\n".join(out).strip() or "No items found for this period."


def _resolve_date_bounds(
    now: datetime, date_str: str | None, days_back: int, days_ahead: int
) -> tuple[datetime, datetime]:
    if not date_str:
        s = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        e = (now + timedelta(days=days_ahead)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return s, e
    low = date_str.lower()
    if low in ("today", "tomorrow"):
        target = now.date() if low == "today" else (now + timedelta(days=1)).date()
    else:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(
                f"Invalid date format '{date_str}'. Use 'today', 'tomorrow', or 'YYYY-MM-DD'."
            ) from exc
    return datetime.combine(target, datetime.min.time()), datetime.combine(
        target, datetime.max.time()
    )


def _fetch_source_items(
    source: Any, source_type: ECal.ClientSourceType, start_ts: int, end_ts: int, flt: _ItemFilter
) -> tuple[str, list[dict[str, Any]]]:
    client = ECal.Client.connect_sync(source, source_type, 30, None)
    s_name, s_uid = source.get_display_name(), source.get_uid()
    s_items: list[dict[str, Any]] = []

    def _cb(c: Any, s: Any, e: Any, _d: Any, _k: Any) -> bool:
        if (it := _extract_component_item(c, s, e, s_name, s_uid, flt)) is not None:
            s_items.append(it)
        return True

    client.generate_instances_sync(start_ts, end_ts, None, _cb, None)
    s_items.sort(key=lambda x: x.get("start", ""))
    return s_name, s_items


async def _run_cal_op(label: str, fn: Callable[[], str]) -> str:
    def _wrapped() -> str:
        try:
            return fn()
        except (EdsMcpError, GLib.Error, RuntimeError) as exc:
            if not isinstance(exc, EdsMcpError):
                logger.exception("Failed calendar operation: %s", label)
            return error_from_exception(exc)

    return await asyncio.to_thread(_wrapped)


async def get_items_logic(
    source_type: ECal.ClientSourceType,
    days_ahead: int = 7,
    days_back: int = 0,
    query: str | None = None,
    uid: str | None = None,
    date_str: str | None = None,
    summary_only: bool = False,
    include_attendees: bool = False,
    max_attendees: int = 50,
    include_completed: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Fetch items (Events, Tasks, or Memos) for a date range."""
    if limit < 1 or offset < 0 or max_attendees < 1:
        return error_envelope(ErrorCode.VALIDATION_ERROR, "Invalid pagination or attendee bounds.")

    def _logic() -> str:
        reg = EDataServer.SourceRegistry.new_sync(None)
        ext = SOURCE_EXT_MAP[source_type]
        if uid:
            src = reg.ref_source(uid)
            if not src or not src.get_enabled():
                raise ResourceNotFoundError(
                    f"Source '{uid}' {'not found' if not src else 'is disabled'}."
                )
            sources = [src]
        else:
            sources = [s for s in reg.list_sources(ext) if s.get_enabled()]
        if not sources:
            raise ResourceNotFoundError(f"No enabled sources found for {ext}.")

        start_t, end_t = _resolve_date_bounds(datetime.now(), date_str, days_back, days_ahead)
        flt = _ItemFilter(
            source_type == ECal.ClientSourceType.TASKS,
            query.lower() if query else None,
            _get_user_mail_identities(reg),
            include_attendees,
            max_attendees,
            include_completed,
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        flat: list[dict[str, Any]] = []
        s_ts, e_ts = int(start_t.timestamp()), int(end_t.timestamp())
        for source in sources:
            try:
                s_name, s_items = _fetch_source_items(source, source_type, s_ts, e_ts, flt)
                if s_items:
                    grouped[s_name] = s_items
                    flat.extend(s_items)
            except (GLib.Error, RuntimeError) as exc:
                logger.exception("Failed source '%s': %s", source.get_display_name(), exc)

        if summary_only:
            return _format_summary_markdown(grouped, flt.is_task)
        flat.sort(key=lambda x: x.get("start", ""))
        return paginated_envelope(flat[offset : offset + limit], total=len(flat), offset=offset)

    return await _run_cal_op("get_items", _logic)
