import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, ECal, ICalGLib

logger = logging.getLogger(__name__)

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

            result.append({
                "uid": source.get_uid(),
                "display_name": source.get_display_name(),
                "enabled": enabled and selected, # User usually cares about what's "checked" in UI
                "parent": source.get_parent(),
                "raw_enabled": enabled,
                "raw_selected": selected
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
        start_time = now - timedelta(days=days_back)
        end_time = now + timedelta(days=days_ahead)
        
        # EDS uses timestamps for instance generation
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        all_events = []
        for source in target_sources:
            try:
                client = ECal.Client.connect_sync(source, ECal.ClientSourceType.EVENTS, 30, None)
                
                # Generate all instances (including recurring) within the time range
                # This is much more robust than manually parsing components
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
                            
                        start_str = start.as_ical_string() if start else "Unknown"
                        uid = ""
                        if hasattr(comp, 'get_uid'):
                            uid = comp.get_uid()
                        elif comp.get_id():
                            uid = comp.get_id().get_uid()
                            
                        all_events.append({
                            "calendar": source.get_display_name(),
                            "summary": summary,
                            "start": start_str,
                            "uid": uid,
                            "is_recurring": False # Hard to tell precisely without occurrence objects, but instance handles it
                        })
                    except Exception as cb_err:
                        logger.exception(f"Error processing calendar event in '{source.get_display_name()}'")
                    return True

                client.generate_instances_sync(start_ts, end_ts, None, _actual_cb, None)
                
            except Exception as e:
                logger.exception(f"Failed to process calendar source '{source.get_display_name()}'")
                continue

        all_events.sort(key=lambda x: x['start'])
        return json.dumps(all_events, indent=2)
    except Exception as e:
        logger.exception("Failed to fetch calendar events")
        return f"Error: {e}"
