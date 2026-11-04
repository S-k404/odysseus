#!/bin/bash
# Install the memory guard for n8n's model traffic (dmr_schema_proxy.py on :12436).
#
# The proxy is a launchd job, and macOS blocks launchd jobs from ~/Documents until a privacy prompt is
# approved (the first attempt froze on it), so it cannot import the guard from this checkout. This copies
# the three stdlib-only modules it needs to ~/.local/share/dmr-guard/src/. Run it again after changing
# src/dmr_admission.py, src/ram_math.py or src/memory_guard.py; tests/test_dmr_schema_proxy_guard.py fails
# while the copy and the checkout differ.
#
#   scripts/dev/install_dmr_guard.sh            copy the modules
#   scripts/dev/install_dmr_guard.sh --restart  copy them and restart the proxy (n8n's Assistant is cut off for ~5 s)
set -eu
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${DMR_GUARD_LIB:-$HOME/.local/share/dmr-guard}/src"
mkdir -p "$DEST"
for f in dmr_admission.py ram_math.py memory_guard.py; do
  install -m 644 "$HERE/src/$f" "$DEST/$f"
  echo "installed $DEST/$f"
done
if [ "${1:-}" = "--restart" ]; then
  launchctl kickstart -k "gui/$(id -u)/com.shamit.dmr-schema-proxy"
  echo "restarted com.shamit.dmr-schema-proxy"
fi
