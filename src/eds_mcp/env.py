import os
import sys
import logging

def setup_environment():
    """
    Sets up the environment for PyGObject and EDS.
    This is necessary when running in a virtual environment on systems like Ubuntu
    where the introspection bindings are installed globally.
    """
    # 1. Add system paths for Python 3.x dist-packages
    # We use a broad range of potential paths to support various distributions
    potential_paths = [
        '/usr/lib/python3/dist-packages',
        '/usr/local/lib/python3/dist-packages',
        # Arch Linux and others
        f'/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages',
    ]
    
    for path in potential_paths:
        if os.path.exists(path) and path not in sys.path:
            sys.path.append(path)

    # 2. Set GI_TYPELIB_PATH for introspection data
    # Standard location for x86_64, adjust if needed for other architectures
    typelib_paths = [
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
        "/usr/lib/girepository-1.0",
        "/usr/local/lib/girepository-1.0"
    ]
    
    existing_typelib = os.environ.get("GI_TYPELIB_PATH", "")
    new_paths = [p for p in typelib_paths if os.path.exists(p)]
    
    if new_paths:
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(new_paths) + (os.pathsep + existing_typelib if existing_typelib else "")

    # 3. Pre-initialize GI versions to avoid late-binding warnings/errors
    try:
        import gi
        gi.require_version('EDataServer', '1.2')
        gi.require_version('ECal', '2.0')
        gi.require_version('EBook', '1.2')
        gi.require_version('EBookContacts', '1.2')
        gi.require_version('GLib', '2.0')
    except (ImportError, ValueError) as e:
        # We don't log here to avoid noise if this is called before logging is set up
        # but we ensure it's available for check_gi_dependencies
        pass

    # 4. Configure basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )

def check_gi_dependencies():
    """Validates that the required GObject introspection libraries are available."""
    try:
        import gi
        gi.require_version('EDataServer', '1.2')
        gi.require_version('ECal', '2.0')
        gi.require_version('EBook', '1.2')
        gi.require_version('EBookContacts', '1.2')
        gi.require_version('GLib', '2.0')
        return True
    except Exception as e:
        logging.error(f"Missing system dependencies (PyGObject/EDS): {e}")
        return False
