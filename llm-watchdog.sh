#!/bin/bash
# llm-watchdog.sh — protects system RAM from multiple concurrent models or memory spikes.
# Runs via launchd every 10s. If it detects dangerously high memory usage or multiple
# large models resident in Docker Model Runner or Rapid-MLX, it unloads the models or
# force-terminates runaway inference processes to protect host RAM from kernel panics.

# Ensure Docker socket path is explicit even under launchd
if [ -z "${DOCKER_HOST:-}" ] && [ -S "/Users/shamit/.docker/run/docker.sock" ]; then
    export DOCKER_HOST="unix:///Users/shamit/.docker/run/docker.sock"
fi

# The WATCHDOG_* variables exist only so the script can be tested; launchd sets none of them.
DOCKER="${WATCHDOG_DOCKER:-/usr/local/bin/docker}"
LOG="${WATCHDOG_LOG:-/Users/shamit/Library/Logs/llm-watchdog.log}"
# Rapid-MLX (MLX server for Odysseus): asked on /health, because its model is not a Docker model and
# its process RSS stays ~1 GB while the weights are resident (MLX memory is not counted in RSS)
RAPID_MLX_URL="${WATCHDOG_RAPID_MLX_URL:-http://127.0.0.1:8081}"
# Models that take 6GB-16GB+ of RAM each
BIG_PATTERN='(30b|32b|35b|70b|80b|12b|14b|gemma3|stable-diffusion)'
# Massive models (30B+) that cannot safely coexist with ANY other model
HUGE_PATTERN='(30b|32b|35b|70b|80b)'
MAX_RSS_MB=28672  # 28 GB (headroom on 48GB host; was 18GB, too low for 35B model at large context)

# docker not running -> no Docker models
loaded=""
if "$DOCKER" info >/dev/null 2>&1; then
    loaded="$("$DOCKER" model ps 2>/dev/null | tail -n +2 | awk '{print $1}')"
fi
docker_loaded="$loaded"

# A loaded Rapid-MLX model joins the list under its served name, so the same size patterns apply.
# Unreachable or standby (nothing in memory) -> not counted.
rapid_loaded=""
health="$(/usr/bin/curl -s -m 3 "$RAPID_MLX_URL/health" 2>/dev/null)"
if echo "$health" | grep -Eq '"model_loaded" *: *true'; then
    rapid_name="$(echo "$health" | sed -n 's/.*"model_name" *: *"\([^"]*\)".*/\1/p')"
    rapid_loaded="rapid-mlx/${rapid_name:-unknown}"
    loaded="$(printf '%s\n%s\n' "$loaded" "$rapid_loaded" | sed '/^$/d')"
fi

# Calculate total RSS of AI inference processes
total_rss_mb=$(ps axo rss,comm,args 2>/dev/null | awk '
    tolower($0) ~ /ollama|com\.docker\.model|llama|vllm/ && $0 !~ /awk|grep/ {
        mb += $1 / 1024
    }
    END { printf "%d", mb }')

# If no models are reported in ps and memory is well within limits, exit cleanly
if [ -z "$loaded" ] && { [ -z "$total_rss_mb" ] || [ "$total_rss_mb" -le "$MAX_RSS_MB" ]; }; then
    exit 0
fi

total_count=$(echo "$loaded" | grep -c . || true)
big_count="$(echo "$loaded" | grep -icE "$BIG_PATTERN" || true)"
huge_count="$(echo "$loaded" | grep -icE "$HUGE_PATTERN" || true)"

trigger_reason=""

if [ "$big_count" -ge 2 ]; then
    trigger_reason="$big_count large models loaded concurrently"
elif [ "$huge_count" -ge 1 ] && [ "$total_count" -ge 2 ]; then
    trigger_reason="35B+ model loaded concurrently with another model ($total_count total)"
elif [ -n "$total_rss_mb" ] && [ "$total_rss_mb" -gt "$MAX_RSS_MB" ] 2>/dev/null; then
    trigger_reason="AI memory usage (${total_rss_mb} MB) exceeded safe limit (${MAX_RSS_MB} MB)"
fi

if [ -n "$trigger_reason" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING: $trigger_reason" >> "$LOG"
    [ -n "$loaded" ] && echo "$loaded" | sed 's/^/    /' >> "$LOG"
    
    # 1. Attempt graceful unload via docker model command
    "$DOCKER" model unload --all >> "$LOG" 2>&1 || true
    notice="models unloaded to protect RAM"

    # 2. Critical verification: Docker Model Runner often skips or returns
    # "No models are running" when a model is actively executing a request.
    # Check if inference processes (llama-server) are still resident and holding memory.
    sleep 1.2
    llama_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
    llama_count=$(echo "$llama_pids" | grep -c . || true)
    
    new_rss_mb=$(ps axo rss,comm,args 2>/dev/null | awk '
        tolower($0) ~ /ollama|com\.docker\.model|llama|vllm/ && $0 !~ /awk|grep/ {
            mb += $1 / 1024
        }
        END { printf "%d", mb }')

    # If docker model unload left multiple llama-servers running, or left ANY llama-server running
    # after a huge/concurrent trigger, or memory remains above the limit: force kill!
    if [ -n "$llama_pids" ] && { [ "$llama_count" -ge 2 ] || [ "$huge_count" -ge 1 ] || [ "$big_count" -ge 2 ] || { [ -n "$new_rss_mb" ] && [ "$new_rss_mb" -gt "$MAX_RSS_MB" ]; }; }; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') EMERGENCY: docker model unload failed to clear inference process(es) (PID: $llama_pids); force terminating llama-server to protect host memory!" >> "$LOG"
        kill -TERM $llama_pids 2>/dev/null || true
        sleep 1
        remaining_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
        if [ -n "$remaining_pids" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') EMERGENCY: SIGKILL sent to stubborn llama-server (PID: $remaining_pids)" >> "$LOG"
            kill -9 $remaining_pids 2>/dev/null || true
        fi
        "$DOCKER" model unload --all >> "$LOG" 2>&1 || true
        notice="CRITICAL: models force-terminated to prevent memory exhaustion"
    fi

    if [ -n "$rapid_loaded" ]; then
        echo "    ($rapid_loaded left loaded: Rapid-MLX cannot unload its primary model remotely, it frees itself when idle)" >> "$LOG"
        notice="$notice (Rapid-MLX model frees itself when idle)"
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') -> unloaded/mitigated all models" >> "$LOG"
    [ -z "${WATCHDOG_NO_NOTIFY:-}" ] && osascript -e "display notification \"$trigger_reason — $notice\" with title \"LLM Watchdog\"" 2>/dev/null || true
fi

exit 0
