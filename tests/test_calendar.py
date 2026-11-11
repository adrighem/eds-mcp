"""Isolated unit tests for calendar events, tasks, memos, and free/busy queries."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from eds_mcp.env import setup_environment

setup_environment()

from gi.repository import ICalGLib  # noqa: E402

from eds_mcp import (  # noqa: E402
    ValidationError,
)
from eds_mcp.calendar import (  # noqa: E402
    create_calendar_event_logic,
    delete_calendar_event_logic,
    get_calendar_events_logic,
    get_tasks_logic,
    update_calendar_event_logic,
)
from eds_mcp.calendar_events import (  # noqa: E402
    build_vevent_component,
    ical_time_to_local_string,
)
from eds_mcp.calendar_freebusy import (  # noqa: E402
    get_shared_calendar_events_logic,
)


def test_ical_time_to_local_string_utc():
    itt = ICalGLib.Time.new_null_time()
    itt.set_date(2026, 6, 15)
    itt.set_time(10, 0, 0)
    itt.set_is_date(False)
    itt.set_timezone(ICalGLib.Timezone.get_utc_timezone())

    result = ical_time_to_local_string(itt)
    assert "2026-06-15" in result


def test_ical_time_to_local_string_fallback_on_overflow(mocker):
    itt = MagicMock()
    itt.is_utc.return_value = False
    itt.get_timezone.return_value = None
    itt.as_timet.side_effect = OverflowError("Timestamp overflow")
    itt.as_ical_string.return_value = "20260615T100000"

    assert ical_time_to_local_string(itt) == "20260615T100000"


def test_ical_time_to_local_string_none():
    assert ical_time_to_local_string(None) == "Unknown"


def test_build_vevent_component_structured_and_all_day():
    comp = build_vevent_component(
        summary="Sprint Review",
        start="2026-11-20T14:00:00Z",
        end="2026-11-20T15:00:00Z",
        timezone="UTC",
        location="Meeting Room 3",
        description="Demo new features",
        attendees=["colleague@example.com"],
    )
    ical_str = comp.as_ical_string()
    assert "Sprint Review" in ical_str
    assert "Meeting Room 3" in ical_str
    assert "Demo new features" in ical_str
    assert "colleague@example.com" in ical_str

    # All-day event
    comp_allday = build_vevent_component(
        summary="Company Holiday",
        start="2026-12-25",
        end="2026-12-25",
    )
    allday_str = comp_allday.as_ical_string()
    assert "Company Holiday" in allday_str
    assert "VALUE=DATE" in allday_str


def test_build_vevent_component_validations():
    with pytest.raises(ValidationError, match="required"):
        build_vevent_component(summary="No Dates")

    with pytest.raises(ValidationError, match="greater than or equal to start"):
        build_vevent_component(
            summary="Backwards Time",
            start="2026-11-20T15:00:00Z",
            end="2026-11-20T14:00:00Z",
        )

    with pytest.raises(ValidationError, match="Invalid iCal data"):
        build_vevent_component(ical_data="INVALID NOT ICAL")


@pytest.mark.asyncio
async def test_create_and_delete_calendar_event_logic(mocker):
    mock_registry = mocker.MagicMock()
    mock_source = mocker.MagicMock()
    mock_registry.ref_source.return_value = mock_source
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    mock_client = mocker.MagicMock()
    mock_client.create_object_sync.return_value = (True, "new-event-uid")
    mocker.patch("gi.repository.ECal.Client.connect_sync", return_value=mock_client)

    # Success creation
    res_raw = await create_calendar_event_logic(
        calendar_uid="cal-1",
        summary="Project Kickoff",
        start="2026-11-21T09:00:00Z",
        end="2026-11-21T10:00:00Z",
    )
    res = json.loads(res_raw)
    assert res["status"] == "created"
    assert res["uid"] == "new-event-uid"

    # Missing calendar
    mock_registry.ref_source.return_value = None
    res_missing = json.loads(
        await create_calendar_event_logic(
            calendar_uid="nonexistent",
            summary="Test",
            start="2026-11-21T09:00:00Z",
            end="2026-11-21T10:00:00Z",
        )
    )
    assert res_missing["error"]["code"] == "NOT_FOUND"

    # Delete success
    mock_registry.ref_source.return_value = mock_source
    mock_client.remove_object_sync.return_value = True
    res_del = json.loads(await delete_calendar_event_logic("cal-1", "new-event-uid"))
    assert res_del["status"] == "deleted"
    assert res_del["uid"] == "new-event-uid"


@pytest.mark.asyncio
async def test_update_calendar_event_logic(mocker):
    mock_registry = mocker.MagicMock()
    mock_source = mocker.MagicMock()
    mock_registry.ref_source.return_value = mock_source
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    mock_client = mocker.MagicMock()
    existing_comp = ICalGLib.Component.new(ICalGLib.ComponentKind.VEVENT_COMPONENT)
    mock_client.get_object_sync.return_value = (True, existing_comp)
    mock_client.modify_object_sync.return_value = True
    mocker.patch("gi.repository.ECal.Client.connect_sync", return_value=mock_client)

    res_raw = await update_calendar_event_logic(
        calendar_uid="cal-1",
        event_uid="ev-123",
        summary="Updated Title",
        description="Updated notes",
    )
    res = json.loads(res_raw)
    assert res["status"] == "updated"
    assert res["uid"] == "ev-123"


@pytest.mark.asyncio
async def test_attendee_compaction_and_self_partstat(mocker):
    mock_registry = mocker.MagicMock()
    mock_cal_source = mocker.MagicMock()
    mock_cal_source.get_enabled.return_value = True
    mock_cal_source.get_uid.return_value = "cal-work"
    mock_cal_source.get_display_name.return_value = "Work"

    # Setup user identity
    mock_id_source = mocker.MagicMock()
    mock_id_source.get_enabled.return_value = True
    mock_id_ext = mocker.MagicMock()
    mock_id_ext.get_address.return_value = "me@company.com"
    mock_id_source.get_extension.return_value = mock_id_ext

    def mock_list_sources(ext):
        if ext == "Calendar":
            return [mock_cal_source]
        if ext == "Mail Identity":
            return [mock_id_source]
        return []

    mock_registry.list_sources.side_effect = mock_list_sources
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    mock_client = mocker.MagicMock()

    def mock_generate_instances(start, end, cancellable, cb, data):
        # Create mock event component
        comp = MagicMock()
        comp.get_uid.return_value = "event-attendees"
        comp.get_summary.return_value.get_value.return_value = "Architecture Review"
        comp.get_recurrenceid.return_value = None
        comp.get_location.return_value = "HQ Room 4"

        # Organizer
        org_prop = MagicMock()
        org_prop.get_organizer.return_value = "mailto:organizer@company.com"
        comp.get_first_property.side_effect = lambda kind: (
            org_prop if kind == ICalGLib.PropertyKind.ORGANIZER_PROPERTY else None
        )

        # Attendees
        att1 = MagicMock()
        att1.get_attendee.return_value = "mailto:me@company.com"
        att1.get_first_parameter.side_effect = lambda kind: (
            MagicMock(get_partstat=lambda: ICalGLib.ParameterPartstat.ACCEPTED)
            if kind == ICalGLib.ParameterKind.PARTSTAT_PARAMETER
            else MagicMock(get_cn=lambda: "Vincent")
        )

        att2 = MagicMock()
        att2.get_attendee.return_value = "mailto:peer@company.com"
        att2.get_first_parameter.side_effect = lambda kind: (
            MagicMock(get_partstat=lambda: ICalGLib.ParameterPartstat.TENTATIVE)
            if kind == ICalGLib.ParameterKind.PARTSTAT_PARAMETER
            else MagicMock(get_cn=lambda: "Peer")
        )

        # Iterator for attendees
        att_props = [att1, att2]
        iter_state = {"idx": 0}

        def mock_first_prop(kind):
            if kind == ICalGLib.PropertyKind.ORGANIZER_PROPERTY:
                return org_prop
            if kind == ICalGLib.PropertyKind.ATTENDEE_PROPERTY:
                iter_state["idx"] = 1
                return att1
            return None

        def mock_next_prop(kind):
            if kind == ICalGLib.PropertyKind.ATTENDEE_PROPERTY and iter_state["idx"] < len(
                att_props
            ):
                idx = iter_state["idx"]
                iter_state["idx"] += 1
                return att_props[idx]
            return None

        comp.get_first_property.side_effect = mock_first_prop
        comp.get_next_property.side_effect = mock_next_prop

        fake_time = MagicMock()
        fake_time.is_utc.return_value = True
        fake_time.as_timet.return_value = 1714896000

        cb(comp, fake_time, fake_time, None, None)

    mock_client.generate_instances_sync.side_effect = mock_generate_instances
    mocker.patch("gi.repository.ECal.Client.connect_sync", return_value=mock_client)

    # 1. Default (include_attendees=False)
    res_default = json.loads(await get_calendar_events_logic(include_attendees=False))
    item = res_default["items"][0]
    assert item["organizer"] == "organizer@company.com"
    assert item["attendee_count"] == 2
    assert item["self_partstat"] == "ACCEPTED"
    assert "attendees" not in item

    # 2. include_attendees=True with max_attendees=1
    res_full = json.loads(await get_calendar_events_logic(include_attendees=True, max_attendees=1))
    item_full = res_full["items"][0]
    assert len(item_full["attendees"]) == 1
    assert item_full["attendees_truncated"] is True
    assert item_full["attendees"][0]["email"] == "me@company.com"


@pytest.mark.asyncio
async def test_get_tasks_completed_filtering(mocker):
    mock_registry = mocker.MagicMock()
    mock_source = mocker.MagicMock()
    mock_source.get_enabled.return_value = True
    mock_source.get_uid.return_value = "tasks-1"
    mock_source.get_display_name.return_value = "My Tasks"
    mock_registry.list_sources.return_value = [mock_source]
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    def mock_generate_tasks(start, end, cancellable, cb, data):
        # Task 1: Completed via 100%
        t1 = MagicMock()
        t1.get_uid.return_value = "t1"
        t1.get_summary.return_value.get_value.return_value = "Finished Task"
        t1.get_recurrenceid.return_value = None
        t1.get_first_property.side_effect = lambda k: (
            MagicMock(get_percentcomplete=lambda: 100)
            if k == ICalGLib.PropertyKind.PERCENTCOMPLETE_PROPERTY
            else None
        )
        t1.get_status.return_value = ICalGLib.PropertyStatus.NONE

        # Task 2: Active task 40%
        t2 = MagicMock()
        t2.get_uid.return_value = "t2"
        t2.get_summary.return_value.get_value.return_value = "In-progress Task"
        t2.get_recurrenceid.return_value = None
        t2.get_first_property.side_effect = lambda k: (
            MagicMock(get_percentcomplete=lambda: 40)
            if k == ICalGLib.PropertyKind.PERCENTCOMPLETE_PROPERTY
            else None
        )
        t2.get_status.return_value = ICalGLib.PropertyStatus.INPROCESS

        fake_time = MagicMock(is_utc=lambda: True, as_timet=lambda: 1714896000)
        cb(t1, fake_time, fake_time, None, None)
        cb(t2, fake_time, fake_time, None, None)

    mock_client = mocker.MagicMock()
    mock_client.generate_instances_sync.side_effect = mock_generate_tasks
    mocker.patch("gi.repository.ECal.Client.connect_sync", return_value=mock_client)

    # include_completed=False by default on get_tasks_logic
    res_active = json.loads(await get_tasks_logic(include_completed=False))
    assert res_active["meta"]["total"] == 1
    assert res_active["items"][0]["summary"] == "In-progress Task"

    # include_completed=True
    res_all = json.loads(await get_tasks_logic(include_completed=True))
    assert res_all["meta"]["total"] == 2


@pytest.mark.asyncio
async def test_get_items_pagination_bounds(mocker):
    mock_registry = mocker.MagicMock()
    mock_source = mocker.MagicMock(
        get_enabled=lambda: True, get_uid=lambda: "s1", get_display_name=lambda: "Events"
    )
    mock_registry.list_sources.return_value = [mock_source]
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    def mock_gen(start, end, cancellable, cb, data):
        fake_time = MagicMock(is_utc=lambda: True, as_timet=lambda: 1714896000)
        for i in range(5):
            c = MagicMock()
            c.get_uid.return_value = f"ev-{i}"
            c.get_summary.return_value.get_value.return_value = f"Event {i}"
            c.get_recurrenceid.return_value = None
            c.get_first_property.return_value = None
            cb(c, fake_time, fake_time, None, None)

    mock_client = mocker.MagicMock()
    mock_client.generate_instances_sync.side_effect = mock_gen
    mocker.patch("gi.repository.ECal.Client.connect_sync", return_value=mock_client)

    # Page 1: limit=2, offset=0
    res1 = json.loads(await get_calendar_events_logic(limit=2, offset=0))
    assert res1["meta"]["total"] == 5
    assert res1["meta"]["returned"] == 2
    assert res1["meta"]["has_more"] is True

    # Page 3: limit=2, offset=4
    res3 = json.loads(await get_calendar_events_logic(limit=2, offset=4))
    assert res3["meta"]["returned"] == 1
    assert res3["meta"]["has_more"] is False


@pytest.mark.asyncio
async def test_shared_calendar_error_envelopes(mocker):
    # Query without @ and contact not found
    mocker.patch("eds_mcp.contacts.search_contacts_logic", return_value=json.dumps({"items": []}))
    res_notfound = json.loads(await get_shared_calendar_events_logic("Nonexistent User"))
    assert res_notfound["error"]["code"] == "NOT_FOUND"
    assert "Could not find email" in res_notfound["error"]["message"]

    # EWS account missing
    mocker.patch(
        "eds_mcp.calendar_freebusy.find_primary_ews_calendar",
        return_value=(None, "No EWS account found"),
    )
    res_no_ews = json.loads(await get_shared_calendar_events_logic("user@company.com"))
    assert res_no_ews["error"]["code"] == "NOT_FOUND"
    assert "No EWS account" in res_no_ews["error"]["message"]
