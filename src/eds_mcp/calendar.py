import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, ECal, ICalGLib  # noqa: E402

logger = logging.getLogger(__name__)

def ical_time_to_local_string(itt: ICalGLib.Time) -> str:
    """Converts an ICalTime object to a local time string (ISO 8601)."""
    if not itt:
        return "Unknown"
    try:
        # itt.as_timet() returns UTC timestamp
        ts = itt.as_timet()
        # datetime.fromtimestamp(ts) returns local datetime based on system timezone
        return datetime.fromtimestamp(ts).isoformat()
    except Exception:
        return itt.as_ical_string()

def get_component_summary(comp) -> str:
    """Extracts a human-readable summary from a calendar/task/memo component."""
    try:
        summary_obj = comp.get_summary()
        if not summary_obj:
            return "No Summary"
            
        if hasattr(summary_obj, 'get_value'):
            return summary_obj.get_value()
        elif hasattr(summary_obj, 'get_value_as_string'):
            return summary_obj.get_value_as_string()
        elif isinstance(summary_obj, ICalGLib.Property):
            return summary_obj.get_value()
        else:
            return str(summary_obj)
    except Exception:
        return "Error extracting summary"

async def list_sources_logic(source_type: ECal.ClientSourceType) -> str:
    """Lists all available sources for a given type (Calendar, Tasks, or Memos)."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            extension = {
                ECal.ClientSourceType.EVENTS: EDataServer.SOURCE_EXTENSION_CALENDAR,
                ECal.ClientSourceType.TASKS: EDataServer.SOURCE_EXTENSION_TASK_LIST,
                ECal.ClientSourceType.MEMOS: EDataServer.SOURCE_EXTENSION_MEMO_LIST
            }[source_type]
            
            sources = registry.list_sources(extension)
            result = []
            for source in sources:
                if source.get_enabled():
                    result.append({
                        "uid": source.get_uid(),
                        "name": source.get_display_name()
                    })
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception(f"Failed to list sources for {source_type}")
            return f"Error: {e}"
            
    return await asyncio.to_thread(_logic)

async def get_items_logic(
    source_type: ECal.ClientSourceType,
    days_ahead: int = 7, 
    days_back: int = 0, 
    query: Optional[str] = None, 
    uid: Optional[str] = None
) -> str:
    """Generic logic to fetch items (Events, Tasks, or Memos) for a date range."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            extension = {
                ECal.ClientSourceType.EVENTS: EDataServer.SOURCE_EXTENSION_CALENDAR,
                ECal.ClientSourceType.TASKS: EDataServer.SOURCE_EXTENSION_TASK_LIST,
                ECal.ClientSourceType.MEMOS: EDataServer.SOURCE_EXTENSION_MEMO_LIST
            }[source_type]
            
            target_sources = []
            if uid:
                source = registry.ref_source(uid)
                if source:
                    target_sources.append(source)
            else:
                sources = registry.list_sources(extension)
                for source in sources:
                    if source.get_enabled():
                        target_sources.append(source)
            
            if not target_sources:
                return f"Error: No enabled sources found for {extension}."

            # Define time range
            now = datetime.now()
            start_time = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (now + timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59, microsecond=999999)
            
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())

            all_items = []
            for source in target_sources:
                try:
                    client = ECal.Client.connect_sync(source, source_type, 30, None)
                    
                    def _actual_cb(comp, start, end, data, cancellable):
                        summary = get_component_summary(comp)
                        if query and query.lower() not in summary.lower():
                            return True
                            
                        rid_val = comp.get_recurrenceid()
                        rid_str = rid_val.as_ical_string() if rid_val else None
                        if rid_str == "00000000T000000":
                            rid_str = None
                            
                        item = {
                            "uid": comp.get_uid(),
                            "rid": rid_str,
                            "calendar_uid": source.get_uid(),
                            "source": source.get_display_name(),
                            "summary": summary,
                            "start": ical_time_to_local_string(start),
                            "end": ical_time_to_local_string(end)
                        }
                        
                        # Add task specific fields
                        if source_type == ECal.ClientSourceType.TASKS:
                            # Percent complete
                            prop = comp.get_first_property(ICalGLib.PropertyKind.PERCENTCOMPLETE_PROPERTY)
                            if prop:
                                item["percent_complete"] = prop.get_percentcomplete()
                        
                        all_items.append(item)
                        return True

                    client.generate_instances_sync(start_ts, end_ts, None, _actual_cb, None)
                    
                except Exception:
                    logger.exception(f"Failed to process source '{source.get_display_name()}'")
                    continue

            all_items.sort(key=lambda x: x['start'])
            return json.dumps(all_items, separators=(',', ':'))
        except Exception as e:
            logger.exception("Failed to fetch items")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

# Specific wrappers for the existing functions to maintain compatibility and clarity
async def list_calendars_logic() -> str:
    return await list_sources_logic(ECal.ClientSourceType.EVENTS)

async def get_calendar_events_logic(days_ahead=7, days_back=0, query=None, calendar_uid=None) -> str:
    return await get_items_logic(ECal.ClientSourceType.EVENTS, days_ahead, days_back, query, calendar_uid)

async def list_tasks_logic() -> str:
    return await list_sources_logic(ECal.ClientSourceType.TASKS)

async def get_tasks_logic(days_ahead=30, days_back=30, query=None, task_list_uid=None) -> str:
    return await get_items_logic(ECal.ClientSourceType.TASKS, days_ahead, days_back, query, task_list_uid)

async def list_memos_logic() -> str:
    return await list_sources_logic(ECal.ClientSourceType.MEMOS)

async def get_memos_logic(query=None, memo_list_uid=None) -> str:
    # Memos don't usually have a meaningful start/end date range in the same way, 
    # but we use a large range to catch them.
    return await get_items_logic(ECal.ClientSourceType.MEMOS, days_ahead=365, days_back=365, query=query, uid=memo_list_uid)

async def get_free_busy_logic(email: str, days_ahead: int, days_back: int, primary_cal_uid: str) -> List[Dict[str, Any]]:
    """Fetches free/busy information for a given email address using ICalGLib for parsing."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            source = registry.ref_source(primary_cal_uid)
            if not source:
                return []
                
            client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
            
            now = datetime.now()
            start_time = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (now + timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59, microsecond=999999)
            
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            
            success, components = client.get_free_busy_sync(start_ts, end_ts, [email], None)
            
            fb_events = []
            for comp in components:
                ical_comp = comp.get_icalcomponent()
                prop = ical_comp.get_first_property(ICalGLib.PropertyKind.FREEBUSY_PROPERTY)
                while prop:
                    fb = prop.get_freebusy()
                    if fb:
                        fb_type_param = prop.get_first_parameter(ICalGLib.ParameterKind.FBTYPE_PARAMETER)
                        fb_type = "Busy"
                        if fb_type_param:
                            fb_enum = fb_type_param.get_fbtype()
                            if fb_enum == ICalGLib.ParameterFbtype.BUSY:
                                fb_type = "Busy"
                            elif fb_enum == ICalGLib.ParameterFbtype.BUSYTENTATIVE:
                                fb_type = "Busy (Tentative)"
                            elif fb_enum == ICalGLib.ParameterFbtype.BUSYUNAVAILABLE:
                                fb_type = "Busy (Unavailable)"
                            elif fb_enum == ICalGLib.ParameterFbtype.FREE:
                                fb_type = "Free"
                            else:
                                fb_type = str(fb_enum)
                        
                        fb_events.append({
                            "calendar": f"Free/Busy ({email})",
                            "summary": fb_type,
                            "start": ical_time_to_local_string(fb.get_start()),
                            "end": ical_time_to_local_string(fb.get_end())
                        })
                    prop = ical_comp.get_next_property(ICalGLib.PropertyKind.FREEBUSY_PROPERTY)
            return fb_events
        except Exception:
            logger.exception(f"Failed to fetch free/busy for {email}")
            return []

    return await asyncio.to_thread(_logic)

async def get_shared_calendar_events_logic(
    query: str,
    days_ahead: int = 7,
    days_back: int = 0
) -> str:
    """Gets free/busy information for another user using the primary account's EWS connection."""
    # 1. Resolve query to email if needed
    email = query
    if "@" not in query:
        from .contacts import search_contacts_logic
        contacts_json = await search_contacts_logic(query)
        contacts = json.loads(contacts_json)
        if contacts and contacts[0].get("emails"):
            email = contacts[0]["emails"][0]
        else:
            return json.dumps({"error": f"Could not find email for '{query}'"})

    # 2. Find primary calendar to use its connection
    def _find_primary():
        registry = EDataServer.SourceRegistry.new_sync(None)
        sources = registry.list_sources(None)
        ews_parent_uid = None
        primary_cal_uid = None
        
        for s in sources:
            if s.has_extension(EDataServer.SOURCE_EXTENSION_COLLECTION):
                coll = s.get_extension(EDataServer.SOURCE_EXTENSION_COLLECTION)
                if coll.get_backend_name() == 'ews':
                    ews_parent_uid = s.get_uid()
                    break
        
        if not ews_parent_uid:
            return None, "No EWS account found to support free/busy queries."

        for s in sources:
            if s.get_parent() == ews_parent_uid and s.get_display_name() == 'Calendar':
                primary_cal_uid = s.get_uid()
                break

        if not primary_cal_uid:
            return None, "Could not find primary calendar for EWS connection."
            
        return primary_cal_uid, None

    res = await asyncio.to_thread(_find_primary)
    if isinstance(res, tuple) and res[1]:
        return json.dumps({"error": res[1]})
    
    primary_cal_uid = res

    try:
        # We use the primary account's connection to query Free/Busy for any organizational user.
        all_events = await get_free_busy_logic(email, days_ahead, days_back, primary_cal_uid)
        return json.dumps(all_events, separators=(',', ':'))

    except Exception as e:
        logger.exception("Error in get_shared_calendar_events_logic")
        return json.dumps({"error": str(e)})


async def create_calendar_event_logic(calendar_uid: str, ical_data: str) -> str:
    """Creates a new calendar event natively."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            source = registry.ref_source(calendar_uid)
            if not source:
                return f"Error: Calendar {calendar_uid} not found."
                
            client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
            
            comp = ICalGLib.Component.new_from_string(ical_data)
            if not comp:
                return "Error: Invalid iCal data."
                
            success, new_uid = client.create_object_sync(comp, ECal.OperationFlags.NONE, None)
            return f"Successfully created event: {new_uid}" if success else "Failed to create event."
        except Exception as e:
            logger.exception("Failed to create event")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

async def delete_calendar_event_logic(calendar_uid: str, event_uid: str, event_rid: Optional[str] = None) -> str:
    """Deletes a calendar event or a specific recurrence instance."""
    def _logic():
        nonlocal event_rid
        if event_rid == "00000000T000000" or event_rid == "":
            event_rid = None
            
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            source = registry.ref_source(calendar_uid)
            if not source:
                return f"Error: Calendar {calendar_uid} not found."
                
            client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
            
            # Using THIS for simple removal or removing all recurring
            mod = ECal.ObjModType.THIS
            if not event_rid:
                # If no recurrence ID is provided, removing the entire series/event makes sense
                mod = ECal.ObjModType.ALL
                
            success = client.remove_object_sync(event_uid, event_rid, mod, ECal.OperationFlags.NONE, None)
            return f"Successfully deleted event {event_uid}." if success else f"Failed to delete event {event_uid}."
        except Exception as e:
            logger.exception("Failed to delete event")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)

async def update_calendar_event_logic(
    calendar_uid: str, 
    event_uid: str, 
    event_rid: Optional[str] = None,
    summary: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """Updates the summary or description of a calendar event."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            source = registry.ref_source(calendar_uid)
            if not source:
                return f"Error: Calendar {calendar_uid} not found."
            client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
            
            # Get the object
            success, icalcomp = client.get_object_sync(event_uid, event_rid, None)
            if not success or not icalcomp:
                return f"Error: Event {event_uid} not found."
                
            comp = ECal.Component.new_from_icalcomponent(icalcomp)
            
            if summary is not None:
                txt = ECal.ComponentText.new(summary, None)
                comp.set_summary(txt)
            
            if description is not None:
                txt = ECal.ComponentText.new(description, None)
                comp.set_descriptions([txt])
            
            # Save modifications
            mod = ECal.ObjModType.THIS
            if not event_rid:
                mod = ECal.ObjModType.ALL
                
            success = client.modify_object_sync(comp.get_icalcomponent(), mod, ECal.OperationFlags.NONE, None)
            
            return f"Successfully updated event {event_uid}." if success else f"Failed to update event {event_uid}."
        except Exception as e:
            logger.exception("Failed to update event")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)
