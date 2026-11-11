import logging
import os
from collections.abc import Callable
from typing import Any

from . import BridgeCallError, BridgeUnavailableError
from .env import setup_environment

setup_environment()

from gi.repository import Gio, GLib  # noqa: E402

logger = logging.getLogger(__name__)

EVOLUTION_BUS_NAME = "org.gnome.Evolution"
EVOLUTION_OBJECT_PATH = "/org/gnome/evolution/McpAutomationBridge"
EVOLUTION_INTERFACE_NAME = "org.gnome.Evolution.McpAutomationBridge"
BRIDGE_READ_FALLBACK_ENV = "EDS_MCP_ENABLE_EVOLUTION_BRIDGE_READS"
BRIDGE_CALL_TIMEOUT_MS = 10_000

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off"})


def get_dbus_proxy() -> Gio.DBusProxy:
    """Acquires D-Bus proxy for Evolution MCP automation bridge."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            EVOLUTION_BUS_NAME,
            EVOLUTION_OBJECT_PATH,
            EVOLUTION_INTERFACE_NAME,
            None,
        )
    except GLib.Error as exc:
        raise BridgeUnavailableError(
            f"Session D-Bus unavailable or Evolution bridge unreachable: {exc.message}"
        ) from exc

    if proxy.get_name_owner() is None:
        raise BridgeUnavailableError(
            "Evolution is not running or MCP automation bridge plugin is disabled."
        )
    return proxy


def is_bridge_reachable(
    proxy_getter: Callable[[], Gio.DBusProxy] | None = None,
) -> bool:
    """Return True if org.gnome.Evolution.McpAutomationBridge is active on session D-Bus."""
    getter = proxy_getter or get_dbus_proxy
    try:
        proxy = getter()
        return proxy.get_name_owner() is not None
    except (BridgeUnavailableError, ConnectionError, GLib.Error, OSError, RuntimeError):
        return False


def bridge_read_fallback_enabled(
    proxy_getter: Callable[[], Gio.DBusProxy] | None = None,
) -> bool:
    """Return whether read-only operations may fall back to Evolution's D-Bus bridge.

    Defaults to enabled when the bridge service is reachable on session D-Bus.
    Set EDS_MCP_ENABLE_EVOLUTION_BRIDGE_READS=0 to explicitly opt out.
    """
    raw = os.environ.get(BRIDGE_READ_FALLBACK_ENV, "").strip().lower()
    if raw in _FALSY_ENV:
        return False
    if raw in _TRUTHY_ENV:
        return True
    return is_bridge_reachable(proxy_getter=proxy_getter)


def call_bridge_method(
    method_name: str,
    variant_signature: str,
    parameters: tuple[Any, ...],
    proxy_getter: Callable[[], Gio.DBusProxy] | None = None,
) -> Any:
    """Call method on Evolution automation bridge and unpack result."""
    getter = proxy_getter or get_dbus_proxy
    proxy = getter()
    try:
        result = proxy.call_sync(
            method_name,
            GLib.Variant(variant_signature, parameters),
            Gio.DBusCallFlags.NONE,
            BRIDGE_CALL_TIMEOUT_MS,
            None,
        )
    except (GLib.Error, TypeError, RuntimeError, ConnectionError, OSError) as exc:
        err_msg = getattr(exc, "message", None) or str(exc)
        is_timeout = "timed out" in err_msg.lower() or "timeout" in err_msg.lower()
        raise BridgeCallError(
            f"D-Bus call '{method_name}' failed: {err_msg}",
            retryable=is_timeout,
            hint="Ensure Evolution is responsive and the latest MCP automation bridge plugin is installed.",
        ) from exc
    return result.unpack()
