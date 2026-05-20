#!/usr/bin/env python3
import sys
import os

# Add src to path to use project imports if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from gi.repository import Gio

EVOLUTION_BUS_NAME = "org.gnome.Evolution"
EVOLUTION_OBJECT_PATH = "/org/gnome/evolution/McpAutomationBridge"
EVOLUTION_INTERFACE_NAME = "org.gnome.Evolution.McpAutomationBridge"

def ping():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            EVOLUTION_BUS_NAME,
            EVOLUTION_OBJECT_PATH,
            EVOLUTION_INTERFACE_NAME,
            None
        )
        owner = proxy.get_name_owner()
        if owner:
            print(f"Success: Evolution Automation Bridge found. Owner: {owner}")
            return True
        else:
            print("Error: Evolution is not running or the MCP automation bridge plugin is disabled.")
            return False
    except Exception as e:
        print(f"Error connecting to D-Bus: {e}")
        return False

if __name__ == "__main__":
    if ping():
        sys.exit(0)
    else:
        sys.exit(1)
