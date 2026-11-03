#!/bin/bash
# Throwaway Odysseus on its own port and data dir, wired to scripts/dev/fake_dmr.py.
# Safe to run next to the Mac app (7860) and your real models: it uses a scratch
# DB, no auth, no scheduler, and never talks to the real model runner.
#
#   scripts/dev/scratch_server.sh start [DIR]   # default DIR: /tmp/odysseus-scratch
#   scripts/dev/scratch_server.sh stop  [DIR]
#
# Then point a browser or scripts/dev/ui_check.js at http://127.0.0.1:7863/.
set -u
cmd="${1:-start}"; E="${2:-/tmp/odysseus-scratch}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_PORT=7863; FAKE_PORT=12499

if [ "$cmd" = stop ]; then
  kill "$(cat "$E/server.pid" 2>/dev/null)" "$(cat "$E/fake.pid" 2>/dev/null)" 2>/dev/null
  echo "stopped"; exit 0
fi

rm -rf "$E"; mkdir -p "$E/data"
python3 -I "$ROOT/scripts/dev/fake_dmr.py" "$FAKE_PORT" "$E/dmr.jsonl" > "$E/fake.log" 2>&1 &
echo $! > "$E/fake.pid"
cd "$ROOT" || exit 1
AUTH_ENABLED=false ODYSSEUS_DATA_DIR="$E/data" DATABASE_URL="sqlite:///$E/data/app.db" \
  ODYSSEUS_INPROCESS_TASKS=0 APP_PORT=$APP_PORT PYTHONPATH="$ROOT" \
  nohup "$ROOT/.venv/bin/python" -m uvicorn app:app --host 127.0.0.1 --port $APP_PORT > "$E/server.log" 2>&1 &
echo $! > "$E/server.pid"
for i in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$APP_PORT/" && break; sleep 1; done
curl -s -X POST "http://127.0.0.1:$APP_PORT/api/model-endpoints" -F name="Fake Runner" \
  -F base_url="http://127.0.0.1:$FAKE_PORT/engines/v1" -F skip_probe=true > /dev/null
# Probe the fake runner now (refresh=true) and wait until its models are cached,
# otherwise the first page load sees an empty picker for ~30 s.
for i in $(seq 1 20); do
  curl -s -m 20 "http://127.0.0.1:$APP_PORT/api/models?refresh=true" | grep -q 'big-chat' && break; sleep 1
done
echo "up: http://127.0.0.1:$APP_PORT/  (fake runner :$FAKE_PORT, log $E/dmr.jsonl)"
