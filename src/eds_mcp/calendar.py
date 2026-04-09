import logging
import json
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

def list_calendars_logic() -> str:
    """Lists all available calendars in Evolution."""
    try:
        registry = EDataServer.SourceRegistry.new_sync(None)
        sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR)
        result = []
        for source in sources:
            enabled = source.get_enabled()
            selected = False
            
            if source.has_extension(EDataServer.SOURCE_EXTENSION_CALENDAR):
                cal_ext = source.get_extension(EDataServer.SOURCE_EXTENSION_CALENDAR)
                selected = cal_ext.get_selected()

            if enabled and selected:
                result.append({
                    "uid": source.get_uid(),
                    "name": source.get_display_name()
                })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception("Failed to list calendars")
        return f"Error: {e}"

def get_calendar_events_logic(
    days_ahead: int = 7, 
    days_back: int = 0, 
    query: Optional[str] = None, 
    calendar_uid: Optional[str] = None
) -> str:
    """Gets calendar events for a date range and optional search query."""
    try:
        registry = EDataServer.SourceRegistry.new_sync(None)
        target_sources = []
        if calendar_uid:
            source = registry.ref_source(calendar_uid)
            if source:
                target_sources.append(source)
            else:
                logger.warning(f"Could not find calendar with UID: {calendar_uid}")
        else:
            sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR)
            for source in sources:
                enabled = source.get_enabled()
                selected = False
                if source.has_extension(EDataServer.SOURCE_EXTENSION_CALENDAR):
                    cal_ext = source.get_extension(EDataServer.SOURCE_EXTENSION_CALENDAR)
                    selected = cal_ext.get_selected()
                
                if enabled and selected:
                    target_sources.append(source)
        
        if not target_sources:
            return "Error: No enabled calendar sources found."

        # Define time range
        now = datetime.now()
        start_time = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = (now + timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # EDS uses timestamps for instance generation
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        all_events = []
        for source in target_sources:
            try:
                client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
                
                # Generate all instances (including recurring) within the time range
                def _actual_cb(comp, start, end, data, cancellable):
                    try:
                        summary_obj = comp.get_summary()
                        if hasattr(summary_obj, 'get_value'):
                            summary = summary_obj.get_value()
                        elif hasattr(summary_obj, 'get_value_as_string'):
                            summary = summary_obj.get_value_as_string()
                        elif isinstance(summary_obj, ICalGLib.Property):
                            summary = summary_obj.get_value()
                        else:
                            summary = str(summary_obj) if summary_obj else "No Summary"
                            
                        if query and query.lower() not in summary.lower():
                            return True
                            
                        all_events.append({
                            "calendar": source.get_display_name(),
                            "summary": summary,
                            "start": ical_time_to_local_string(start),
                            "end": ical_time_to_local_string(end)
                        })
                    except Exception:
                        logger.exception(f"Error processing calendar event in '{source.get_display_name()}'")
                    return True

                client.generate_instances_sync(start_ts, end_ts, None, _actual_cb, None)
                
            except Exception:
                logger.exception(f"Failed to process calendar source '{source.get_display_name()}'")
                continue

        all_events.sort(key=lambda x: x['start'])
        return json.dumps(all_events, separators=(',', ':'))
    except Exception as e:
        logger.exception("Failed to fetch calendar events")
        return f"Error: {e}"

def get_free_busy_logic(email: str, days_ahead: int, days_back: int, primary_cal_uid: str) -> List[Dict[str, Any]]:
    """Fetches free/busy information for a given email address using ICalGLib for parsing."""
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

def get_shared_calendar_events_logic(
    query: str,
    days_ahead: int = 7,
    days_back: int = 0
) -> str:
    """Gets free/busy information for another user using the primary account's EWS connection."""
    # 1. Resolve query to email if needed
    email = query
    if "@" not in query:
        from .contacts import search_contacts_logic
        contacts_json = search_contacts_logic(query)
        contacts = json.loads(contacts_json)
        if contacts and contacts[0].get("emails"):
            email = contacts[0]["emails"][0]
        else:
            return json.dumps({"error": f"Could not find email for '{query}'"})

    # 2. Find primary calendar to use its connection
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
        return json.dumps({"error": "No EWS account found to support free/busy queries."})

    for s in sources:
        if s.get_parent() == ews_parent_uid and s.get_display_name() == 'Calendar':
            primary_cal_uid = s.get_uid()
            break

    if not primary_cal_uid:
        return json.dumps({"error": "Could not find primary calendar for EWS connection."})

    try:
        # We use the primary account's connection to query Free/Busy for any organizational user.
        # This avoids adding temporary sources or restarting services.
        all_events = get_free_busy_logic(email, days_ahead, days_back, primary_cal_uid)
        return json.dumps(all_events, separators=(',', ':'))

    except Exception as e:
        logger.exception("Error in get_shared_calendar_events_logic")
        return json.dumps({"error": str(e)})
