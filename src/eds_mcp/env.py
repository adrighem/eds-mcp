import logging
import os
import stat
import sys
import warnings

logger = logging.getLogger(__name__)

_REQUIRED_GI_NAMESPACES: tuple[tuple[str, str], ...] = (
    ("EDataServer", "1.2"),
    ("Camel", "1.2"),
    ("Secret", "1"),
    ("ECal", "2.0"),
    ("ICalGLib", "3.0"),
    ("EBook", "1.2"),
    ("EBookContacts", "1.2"),
    ("GLib", "2.0"),
    ("Gio", "2.0"),
)


def _ensure_session_bus_environment() -> None:
    """Infer the user D-Bus session bus when MCP launchers strip session env."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    fallback_runtime_dir = f"/run/user/{os.getuid()}"

    if not runtime_dir and os.path.isdir(fallback_runtime_dir):
        try:
            if os.stat(fallback_runtime_dir).st_uid == os.getuid():
                runtime_dir = fallback_runtime_dir
                os.environ["XDG_RUNTIME_DIR"] = runtime_dir
        except OSError as exc:
            logger.debug("Could not stat fallback runtime dir: %s", exc)

    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not runtime_dir:
        return

    bus_path = os.path.join(runtime_dir, "bus")
    try:
        bus_stat = os.stat(bus_path)
    except OSError:
        return

    if bus_stat.st_uid == os.getuid() and stat.S_ISSOCK(bus_stat.st_mode):
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"


def setup_environment() -> None:
    """
    Sets up the environment for PyGObject and EDS.
    This is necessary when running in a virtual environment on systems like Ubuntu
    where the introspection bindings are installed globally.
    """
    _ensure_session_bus_environment()

    # 1. Add system paths for Python 3.x dist-packages
    # We use a broad range of potential paths to support various distributions
    potential_paths = [
        "/usr/lib/python3/dist-packages",
        "/usr/local/lib/python3/dist-packages",
        # Arch Linux and others
        f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages",
    ]

    for path in potential_paths:
        if os.path.exists(path) and path not in sys.path:
            sys.path.append(path)

    # 2. Set GI_TYPELIB_PATH for introspection data
    # Standard location for x86_64, adjust if needed for other architectures
    typelib_paths = [
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
        "/usr/lib/girepository-1.0",
        "/usr/local/lib/girepository-1.0",
    ]

    existing_typelib = os.environ.get("GI_TYPELIB_PATH", "")
    new_paths = [p for p in typelib_paths if os.path.exists(p)]

    if new_paths:
        existing_parts = existing_typelib.split(os.pathsep) if existing_typelib else []
        merged = list(dict.fromkeys([*new_paths, *existing_parts]))
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(p for p in merged if p)

    # 3. Pre-initialize GI versions to avoid late-binding warnings/errors
    try:
        import gi

        for namespace, version in _REQUIRED_GI_NAMESPACES:
            gi.require_version(namespace, version)
    except (ImportError, ValueError):
        # We don't log here to avoid noise if this is called before logging is set up
        # but we ensure it's available for check_gi_dependencies
        pass

    # 4. Set CAMEL_PROVIDER_DIR if it's in the expected location
    camel_provider_paths = [
        "/usr/lib/evolution-data-server/camel-providers",
        "/usr/lib/x86_64-linux-gnu/evolution-data-server/camel-providers",
        "/usr/lib64/evolution-data-server/camel-providers",
    ]
    for path in camel_provider_paths:
        if os.path.exists(path):
            os.environ["CAMEL_PROVIDER_DIR"] = path
            break

    # 5. Configure basic logging before optional Camel provider init
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    try:
        import gi

        # PyGObject currently emits this while loading GLib overrides through
        # EDS/Camel imports. The deprecated API is accessed inside PyGObject's
        # override loader, not by eds-mcp code.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"GLib\.unix_signal_add_full is deprecated; use GLibUnix\.signal_add_full instead",
                category=gi.PyGIDeprecationWarning,
            )
            from gi.repository import Camel, GLib

        try:
            Camel.provider_init()
        except GLib.Error as exc:
            logger.warning("Camel provider initialization reported GLib error: %s", exc)
    except (ImportError, ValueError, RuntimeError, OSError) as exc:
        logger.debug("Camel provider initialization skipped: %s", exc)


def check_gi_dependencies() -> bool:
    """Validates that the required GObject introspection libraries are available."""
    try:
        import gi

        for namespace, version in _REQUIRED_GI_NAMESPACES:
            gi.require_version(namespace, version)
        return True
    except (ImportError, ValueError, RuntimeError) as exc:
        logger.error("Missing system dependencies (PyGObject/EDS): %s", exc)
        return False
