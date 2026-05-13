#!/usr/bin/env bash
set -euo pipefail
detect_plugin_dirs() {
  # search common locations
  for d in \
    "$(pkg-config --variable=plugindir evolution-mail-3.0 2>/dev/null || true)" \
    /usr/lib/evolution/plugins \
    /usr/lib64/evolution/plugins \
    /usr/lib/x86_64-linux-gnu/evolution/plugins \
    /usr/lib/aarch64-linux-gnu/evolution/plugins
  do
    [[ -n "$d" && -d "$d" ]] && echo "$d"
  done
}

for d in $(detect_plugin_dirs); do
  if [[ -f "$d/libevolution-custom-instrumentation.so" ]]; then
    echo "Removing $d/libevolution-custom-instrumentation.so"
    sudo rm -f "$d/libevolution-custom-instrumentation.so"
  fi
  if [[ -f "$d/evolution-custom-instrumentation.eplug" ]]; then
    echo "Removing $d/evolution-custom-instrumentation.eplug"
    sudo rm -f "$d/evolution-custom-instrumentation.eplug"
  fi
done

# Clean up old module location too
sudo rm -f /usr/lib/evolution/modules/libevolution-custom-instrumentation.so

evolution --force-shutdown >/dev/null 2>&1 || true
echo "Uninstalled."
