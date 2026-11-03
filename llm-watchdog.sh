#!/bin/bash
# llm-watchdog.sh — protects system RAM from multiple concurrent models or memory spikes.
# Runs via launchd every 30s. If it detects dangerously high memory usage or multiple
# large models resident in Docker Model Runner, it unloads models to protect host RAM.

DOCKER=/usr/local/bin/docker
LOG="$HOME/Library/Logs/llm-watchdog.log"
# Models that take 6GB-16GB+ of RAM each
BIG_PATTERN='(30b|32b|35b|70b|80b|12b|14b|gemma3|stable-diffusion)'
# Massive models (30B+) that cannot safely coexist with ANY other model
HUGE_PATTERN='(30b|32b|35b|70b|80b)'
MAX_RSS_MB=28672  # 28 GB (headroom on 48GB host; was 18GB, too low for 35B model at large context)

# docker not running -> nothing to do
"$DOCKER" info >/dev/null 2>&1 || exit 0

loaded="$("$DOCKER" model ps 2>/dev/null | tail -n +2 | awk '{print $1}')"
[ -z "$loaded" ] && exit 0

total_count=$(echo "$loaded" | grep -c .)
big_count="$(echo "$loaded" | grep -icE "$BIG_PATTERN")"
huge_count="$(echo "$loaded" | grep -icE "$HUGE_PATTERN")"

# Calculate total RSS of AI inference processes
total_rss_mb=$(ps axo rss,comm,args 2>/dev/null | awk '
    tolower($0) ~ /ollama|com\.docker\.model|llama|vllm/ && $0 !~ /awk|grep/ {
        mb += $1 / 1024
    }
    END { printf "%d", mb }')

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
    echo "$loaded" | sed 's/^/    /' >> "$LOG"
    "$DOCKER" model unload --all >> "$LOG" 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S') -> unloaded all models" >> "$LOG"
    osascript -e "display notification \"$trigger_reason — models unloaded to protect RAM\" with title \"LLM Watchdog\"" 2>/dev/null
fi

exit 0
