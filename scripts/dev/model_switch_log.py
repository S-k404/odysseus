"""What the fake runner received: chat requests (with messages), unloads, stream ends.

    python3 scripts/dev/model_switch_log.py [FIRST_LINE]

FIRST_LINE skips earlier requests (model_switch_check.js writes marks.json with the
line each step started at). Title and memory helper calls show as one line each.
Set DMR_LOG to read a log other than the scratch server's.
"""
import json
import os
import sys

LOG = os.environ.get("DMR_LOG", "/tmp/odysseus-scratch/dmr.jsonl")
HELPERS = ("Generate a short title", "You are a memory extraction")

rows = [json.loads(line) for line in open(LOG) if line.strip()]
first = int(sys.argv[1]) if len(sys.argv) > 1 else 0
t0 = rows[first]["t"] if first < len(rows) else 0

for r in rows[first:]:
    path = r.get("path", "")
    if r.get("method") == "GET":
        continue
    t = f"+{r['t'] - t0:6.1f}s"
    if r.get("event"):
        print(f"{t} {r['event']:<14} {r['model']}")
    elif path == "/engines/unload":
        print(f"{t} UNLOAD {r['models']} -> loaded {r['loaded_after']}")
    elif path.endswith("/chat/completions"):
        msgs = r.get("messages") or []
        if msgs and msgs[0][1].startswith(HELPERS):
            print(f"{t} (helper call on {r['model']})")
            continue
        print(f"{t} CHAT -> {r['model']}  tools_offered={r['n_tools']}  msgs={len(msgs)}  loaded {r['loaded_after']}")
        for role, content in msgs[1:]:  # [0] is the system prompt
            tail = f" ... {content[-50:]!r}" if len(content) > 130 else ""
            print(f"           {role:<9} {content[:70]!r}{tail}")
