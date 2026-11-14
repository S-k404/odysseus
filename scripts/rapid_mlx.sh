#!/bin/bash
# Rapid-MLX as a local engine for Odysseus (Apple Silicon): a model loads only when a request needs it and is
# freed after it has been idle, so it costs RAM only while in use. Telemetry off, and it never downloads a model.
#
#   scripts/rapid_mlx.sh start <model> [served-name]   <model>: a local MLX folder, or an alias already on disk
#   scripts/rapid_mlx.sh status
#   scripts/rapid_mlx.sh stop
#
# Then in Odysseus: model picker "+" (add models) -> OpenAI-compatible endpoint -> http://127.0.0.1:8081/v1
# Environment: RAPID_MLX_HOME (venv folder, default ../odysseus-mlx), RAPID_MLX_PORT (8081),
#              RAPID_MLX_IDLE_SECONDS (60: how long an idle model stays in memory),
#              RAPID_MLX_ARGS (extra flags for `rapid-mlx serve`). A named alias picks its tool-call parser by itself;
#              a bare local folder needs one for tool calling, e.g. RAPID_MLX_ARGS="--enable-auto-tool-choice --tool-call-parser qwen".
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${RAPID_MLX_HOME:-$ROOT/../odysseus-mlx}"
BIN="$HOME_DIR/.venv/bin/rapid-mlx"
PORT="${RAPID_MLX_PORT:-8081}"
IDLE="${RAPID_MLX_IDLE_SECONDS:-60}"
PIDFILE="$ROOT/logs/rapid-mlx.pid"
LOG="$ROOT/logs/rapid-mlx.log"

alive() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-status}" in
  start)
    MODEL="${2:-}"; NAME="${3:-}"
    [ -x "$BIN" ] || { echo "rapid-mlx is not installed at $BIN (uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python rapid-mlx)"; exit 1; }
    [ -n "$MODEL" ] || { echo "usage: $0 start <model> [served-name]"; exit 1; }
    alive && { echo "already running (pid $(cat "$PIDFILE")) on :$PORT"; exit 0; }
    [ -n "$NAME" ] || NAME="$(basename "$MODEL")"
    mkdir -p "$ROOT/logs"
    RAPID_MLX_TELEMETRY=0 DO_NOT_TRACK=1 nohup "$BIN" serve "$MODEL" --port "$PORT" --served-model-name "$NAME" \
      --lazy-load --idle-unload-seconds "$IDLE" --disable-model-downloads --log-file "$LOG" ${RAPID_MLX_ARGS:-} >> "$LOG.out" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 60); do
      curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/v1/models" && { echo "up: http://127.0.0.1:$PORT/v1 (model \"$NAME\", loads on first request, freed after ${IDLE}s idle)"; exit 0; }
      alive || break
      sleep 1
    done
    echo "did not start; see $LOG.out"; exit 1 ;;
  stop)
    if alive; then kill "$(cat "$PIDFILE")"; rm -f "$PIDFILE"; echo "stopped"; else rm -f "$PIDFILE"; echo "not running"; fi ;;
  status)
    if alive; then
      echo "running: pid $(cat "$PIDFILE"), :$PORT, memory $(ps -o rss= -p "$(cat "$PIDFILE")" | awk '{printf "%.1f GB", $1/1048576}')"
      curl -s -m 3 "http://127.0.0.1:$PORT/v1/models" | head -c 200; echo
    else echo "not running"; fi ;;
  *) echo "usage: $0 start <model> [served-name] | stop | status"; exit 1 ;;
esac
