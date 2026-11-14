#!/usr/bin/env python3
"""Measure an OpenAI-compatible endpoint: first-token time, decode speed, prefix-cache effect, memory.

    .venv/bin/python scripts/dev/bench_endpoint.py --url http://127.0.0.1:12434/engines/v1 --model ai/qwen3:8B --label dmr
    .venv/bin/python scripts/dev/bench_endpoint.py --url http://127.0.0.1:8081/v1 --model coder --label rapid-mlx --json out.json

Three requests, all streamed:
  short  a one-line prompt: first-token time and decode tokens/s with nothing cached
  cold   a ~1500-token document plus a question: prompt processing speed
  warm   the same document with a different question: if the server keeps a prefix cache, first-token time drops
Tokens are counted from the server's usage report when it sends one, otherwise from content chunks (about one per token).
Memory is the change in "used" GB (as Activity Monitor counts it) around the whole run, so load the model first
for a steady figure, or leave it unloaded to include the load.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FILLER = (
    "The harbour at Port Elda has three piers. The north pier handles fish, the middle pier handles timber, and the "
    "south pier is kept for ferries. Each morning the harbour master records the tide, the wind, and the number of "
    "boats waiting, then hands the log to the clerk, who copies it into the ledger kept in the customs house. "
)


def document(paragraphs: int = 28) -> str:
    return "\n\n".join(f"Paragraph {i + 1}. " + FILLER for i in range(paragraphs))


def one_request(client: httpx.Client, base: str, model: str, prompt: str, max_tokens: int, no_think: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if no_think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    started = time.perf_counter()
    first: Optional[float] = None
    chunks = 0
    usage: Dict[str, Any] = {}
    with client.stream("POST", base.rstrip("/") + "/chat/completions", json=body, timeout=600) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content"):
                    chunks += 1
                    if first is None:
                        first = time.perf_counter()
    ended = time.perf_counter()
    tokens = int(usage.get("completion_tokens") or chunks)
    first = first if first is not None else ended
    decode = max(ended - first, 1e-6)
    return {
        "first_token_s": round(first - started, 3),
        "decode_tok_s": round(max(tokens - 1, 0) / decode, 1),
        "tokens": tokens,
        "prompt_tokens": usage.get("prompt_tokens"),
        "total_s": round(ended - started, 3),
        "token_source": "usage" if usage.get("completion_tokens") else "chunks",
    }


def used_gb() -> Optional[float]:
    try:
        from src import memory_guard
        snap = memory_guard.snapshot()
        return round(float(snap["used_gb"]), 2) if snap else None
    except Exception:
        return None


def run(base: str, model: str, max_tokens: int = 128, no_think: bool = False,
        request=one_request, memory=used_gb) -> Dict[str, Any]:
    doc = document()
    before = memory()
    with httpx.Client() as client:
        results = {
            "short": request(client, base, model, "Write one sentence about the sea.", max_tokens, no_think),
            "cold": request(client, base, model, doc + "\n\nQuestion: how many piers are there?", max_tokens, no_think),
            "warm": request(client, base, model, doc + "\n\nQuestion: which pier handles timber?", max_tokens, no_think),
        }
    after = memory()
    cold, warm = results["cold"]["first_token_s"], results["warm"]["first_token_s"]
    return {
        "model": model,
        "results": results,
        "prefix_cache_speedup": round(cold / warm, 2) if warm > 0 else None,
        "memory_used_change_gb": round(after - before, 2) if before is not None and after is not None else None,
    }


def table(label: str, report: Dict[str, Any]) -> str:
    rows: List[str] = [f"{label}: {report['model']}", f"{'request':8}{'first token':>13}{'tok/s':>9}{'tokens':>8}{'total':>9}"]
    for name, r in report["results"].items():
        rows.append(f"{name:8}{r['first_token_s']:>12.2f}s{r['decode_tok_s']:>9.1f}{r['tokens']:>8}{r['total_s']:>8.1f}s")
    rows.append(f"prefix-cache speedup (cold/warm first token): {report['prefix_cache_speedup']}x")
    if report["memory_used_change_gb"] is not None:
        rows.append(f"memory used change: {report['memory_used_change_gb']:+.1f} GB")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="base URL ending in /v1 (or /engines/v1)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", default="endpoint")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--no-think", action="store_true", help="send enable_thinking=false (for Qwen3-style models)")
    ap.add_argument("--json", help="also write the report to this file")
    args = ap.parse_args()
    report = run(args.url, args.model, args.max_tokens, args.no_think)
    print(table(args.label, report))
    if args.json:
        Path(args.json).write_text(json.dumps({"label": args.label, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
