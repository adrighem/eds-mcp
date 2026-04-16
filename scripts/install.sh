#!/usr/bin/env bash
set -euo pipefail
LOG="/tmp/evolution_mcp_automation_bridge_install.log"
exec > >(tee -a "$LOG") 2>&1

echo "== Evolution MCP Automation Bridge installer =="

detect_plugin_dir() {
  local p
  p="$(pkg-config --variable=plugindir evolution-mail-3.0 2>/dev/null || true)"
  if [[ -n "${p:-}" && -d "$p" ]]; then
    echo "$p"
    return 0
  fi

  for c in \
    /usr/lib/evolution/plugins \
    /usr/lib64/evolution/plugins \
    /usr/lib/x86_64-linux-gnu/evolution/plugins \
    /usr/lib/aarch64-linux-gnu/evolution/plugins; do
    if [[ -d "$c" ]]; then
      echo "$c"
      return 0
    fi
  done

  # Fallback
  echo "/usr/lib/evolution/plugins"
}

PLUGINDIR="$(detect_plugin_dir)"
echo "-- Using plugin dir: $PLUGINDIR"

# Prereqs (best-effort per distro)
if command -v apt >/dev/null 2>&1; then
  sudo apt install -y build-essential pkg-config cmake \
    evolution-dev libgtk-3-dev libglib2.0-dev libebook-1.2-dev libecal2.0-dev libcamel1.2-dev || true
fi

# Build
mkdir -p build && cd build
cmake ..
cmake --build .

# Install
sudo cmake --install .

# Clean up old module if it exists
sudo rm -f /usr/lib/evolution/modules/libevolution-mcp-automation-bridge.so

# Restart Evolution (best effort)
evolution --force-shutdown >/dev/null 2>&1 || true
echo "Installed to $PLUGINDIR"
echo "Launch Evolution to use the plugin."
