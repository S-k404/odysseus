#!/bin/bash
# aicheck.sh — one command to see EVERY AI model holding RAM on this Mac.
# Covers: Docker Model Runner (llama.cpp + vllm-metal/python) AND Ollama.
# Usage:
#   aicheck          # report what's loaded and how much memory it holds
#   aicheck kill     # unload everything (DMR models + Ollama models)

DOCKER=/usr/local/bin/docker

echo "=== Docker Model Runner (loaded models) ==="
if "$DOCKER" info >/dev/null 2>&1; then
    out="$("$DOCKER" model ps 2>/dev/null | tail -n +2)"
    if [ -n "$out" ]; then echo "$out"; else echo "  (none loaded)"; fi
else
    echo "  (docker not running)"
fi

echo ""
echo "=== Ollama (loaded models) ==="
if command -v ollama >/dev/null 2>&1 && pgrep -x ollama >/dev/null 2>&1; then
    oout="$(ollama ps 2>/dev/null | tail -n +2)"
    if [ -n "$oout" ]; then echo "$oout"; else echo "  (running, no models loaded)"; fi
else
    echo "  (not running)"
fi

echo ""
echo "=== AI-related processes (RAM, approximate) ==="
# llama = DMR llama.cpp runner; python+vllm = DMR MLX backend; ollama = Ollama
ps axo rss,comm,args 2>/dev/null | awk '
    tolower($0) ~ /ollama|com\.docker\.model|llama|vllm/ && $0 !~ /awk/ {
        mb = $1 / 1024
        if (mb > 100) { total += mb; printf "  %6.0f MB  %s\n", mb, $2 }
    }
    END { printf "  ------\n  %6.0f MB total (RSS — Metal GPU memory may be extra)\n", total }'

echo ""
echo "=== Context size (last loaded, from DMR logs) ==="
if "$DOCKER" info >/dev/null 2>&1; then
    ctx_line=$("$DOCKER" model logs 2>/dev/null | grep 'n_ctx' | tail -1)
    if [ -n "$ctx_line" ]; then
        echo "  $ctx_line"
        # Warn if dangerously high
        ctx_val=$(echo "$ctx_line" | grep -oE '[0-9]+' | tail -1)
        if [ -n "$ctx_val" ] && [ "$ctx_val" -gt 131072 ] 2>/dev/null; then
            echo "  ⚠️  WARNING: n_ctx=$ctx_val exceeds safe limit (131072). Risk of OOM."
        fi
    else
        echo "  (no n_ctx found in logs — no model loaded yet?)"
    fi
fi

if [ "$1" = "kill" ]; then
    echo ""
    echo "=== Unloading everything ==="
    "$DOCKER" model unload --all 2>/dev/null && echo "  DMR: unloaded"
    if command -v ollama >/dev/null 2>&1 && pgrep -x ollama >/dev/null 2>&1; then
        ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r m; do
            [ -n "$m" ] && ollama stop "$m" 2>/dev/null && echo "  Ollama: stopped $m"
        done
    fi
    echo "  done."
fi
