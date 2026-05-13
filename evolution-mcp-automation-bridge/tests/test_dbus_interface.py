import sys
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
import unittest

class TestMcpAutomationBridge(unittest.TestCase):
    def setUp(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.proxy = Gio.DBusProxy.new_sync(
            self.bus,
            Gio.DBusProxyFlags.NONE,
            None,
            'org.gnome.Evolution',
            '/org/gnome/evolution/McpAutomationBridge',
            'org.gnome.Evolution.McpAutomationBridge',
            None
        )

    def test_interface_active(self):
        owner = self.proxy.get_name_owner()
        self.assertIsNotNone(owner, "Evolution is not running or the plugin is not loaded.")

    def test_invalid_account_returns_error(self):
        # We test that the bridge responds correctly to an invalid account
        try:
            result = self.proxy.call_sync(
                "DeleteMessage",
                GLib.Variant('(sss)', ("invalid-uid", "invalid-msg", "Inbox")),
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            success, message = result.unpack()
            self.assertFalse(success)
            self.assertIn("Account not found", message)
        except Exception as e:
            self.fail(f"D-Bus call raised unexpected exception: {e}")

if __name__ == '__main__':
    unittest.main()
