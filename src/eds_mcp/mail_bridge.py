import os
import logging
from typing import Any, Callable, Optional

from .env import setup_environment
setup_environment()

from gi.repository import Gio, GLib  # noqa: E402

logger = logging.getLogger(__name__)

EVOLUTION_BUS_NAME = "org.gnome.Evolution"
EVOLUTION_OBJECT_PATH = "/org/gnome/evolution/McpAutomationBridge"
EVOLUTION_INTERFACE_NAME = "org.gnome.Evolution.McpAutomationBridge"
BRIDGE_READ_FALLBACK_ENV = "EDS_MCP_ENABLE_EVOLUTION_BRIDGE_READS"
BRIDGE_CALL_TIMEOUT_MS = 10_000


def bridge_read_fallback_enabled() -> bool:
    """Return whether read-only operations may call in-process Evolution bridge."""
    return os.environ.get(BRIDGE_READ_FALLBACK_ENV, "").lower() in {"1", "true", "yes", "on"}


def get_dbus_proxy() -> Gio.DBusProxy:
    """Acquires D-Bus proxy for Evolution MCP automation bridge."""
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
    if proxy.get_name_owner() is None:
        raise ConnectionError("Evolution is not running or MCP automation bridge plugin disabled. Start Evolution first.")
    return proxy


def call_bridge_method(
    method_name: str,
    variant_signature: str,
    parameters: tuple,
    proxy_getter: Optional[Callable[[], Gio.DBusProxy]] = None,
) -> Any:
    """Call method on Evolution automation bridge and unpack result."""
    getter = proxy_getter or get_dbus_proxy
    proxy = getter()
    result = proxy.call_sync(
        method_name,
        GLib.Variant(variant_signature, parameters),
        Gio.DBusCallFlags.NONE,
        BRIDGE_CALL_TIMEOUT_MS,
        None,
    )
    return result.unpack()
