#!/usr/bin/env python3
"""Add Rapid-MLX (and optionally the local-deep-research connector) to Odysseus's own database.

    .venv/bin/python scripts/register_rapid_mlx.py --model qwen3.6-35b-4bit            # dry run: shows what it would do
    .venv/bin/python scripts/register_rapid_mlx.py --model qwen3.6-35b-4bit --apply    # does it (after a backup)
    .venv/bin/python scripts/register_rapid_mlx.py --model qwen3.6-35b-4bit --apply --research

Same result as "+" in the model picker and Connectors > custom MCP, for when the app can't be clicked through. It refuses to
write while Odysseus is running (quit it first), copies data/app.db to data/app.db.bak_rapidmlx_<time> before writing, and is
safe to run again: an existing entry is updated, not duplicated. The endpoint is flagged as supporting native tool calls, so
agent mode sends real tool schemas whatever the model is called.
"""

import argparse
import json
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_LDR = str(ROOT.parent / "odysseus-ldr" / ".venv" / "bin" / "ldr-mcp")
ENDPOINT_NAME = "Rapid-MLX (local, Apple Silicon)"
CONNECTOR_NAME = "Local Deep Research"


def app_is_running(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def register(db, model: str, port: int, research: bool, ldr_command: str) -> List[str]:
    """Insert or update the rows; returns what was done. ``db`` is a SQLAlchemy session."""
    from core.database import McpServer, ModelEndpoint

    done: List[str] = []
    base_url = f"http://127.0.0.1:{port}/v1"
    row = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base_url).first()
    action = "updated" if row else "added"
    if not row:
        row = ModelEndpoint(id=uuid.uuid4().hex[:8], base_url=base_url)
        db.add(row)
    row.name = ENDPOINT_NAME
    row.is_enabled = True
    row.model_type = "llm"
    row.endpoint_kind = "local"
    row.supports_tools = True  # Rapid-MLX returns structured tool calls; don't depend on the model's name
    row.cached_models = json.dumps([model])
    row.pinned_models = json.dumps([model])
    done.append(f"{action} model endpoint {base_url} with model {model!r}")

    if research:
        env: Dict[str, Any] = {
            "LDR_LLM_PROVIDER": "openai_endpoint",
            "LDR_LLM_OPENAI_ENDPOINT_URL": base_url,
            "LDR_LLM_OPENAI_ENDPOINT_API_KEY": "none",
            "LDR_LLM_MODEL": model,
            "DO_NOT_TRACK": "1",
        }
        server = db.query(McpServer).filter(McpServer.name == CONNECTOR_NAME).first()
        action = "updated" if server else "added"
        if not server:
            server = McpServer(id=uuid.uuid4().hex[:8], name=CONNECTOR_NAME)
            db.add(server)
        server.transport = "stdio"
        server.command = ldr_command
        server.args = "[]"
        server.env = json.dumps(env)
        server.is_enabled = True
        done.append(f"{action} connector {CONNECTOR_NAME!r} ({ldr_command})")
    db.commit()
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="the name Rapid-MLX serves (rapid_mlx.sh start <model> [name])")
    ap.add_argument("--port", type=int, default=8081, help="Rapid-MLX port (default 8081)")
    ap.add_argument("--research", action="store_true", help="also add the local-deep-research connector")
    ap.add_argument("--ldr-command", default=DEFAULT_LDR)
    ap.add_argument("--app-port", type=int, default=7860, help="port Odysseus runs on (refuses to write while it answers)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()

    plan = [f"model endpoint http://127.0.0.1:{args.port}/v1 with model {args.model!r} (native tool calls on)"]
    if args.research:
        plan.append(f"connector {CONNECTOR_NAME!r} -> {args.ldr_command}, using the same model")
    print("Would add or update:\n  - " + "\n  - ".join(plan))
    if not args.apply:
        print("\nDry run. Add --apply to write it.")
        return 0
    if app_is_running(args.app_port):
        print(f"\nOdysseus is running on :{args.app_port}. Quit it first (Cmd-Q), then run this again.")
        return 1
    if args.research and not Path(args.ldr_command).exists():
        print(f"\n{args.ldr_command} does not exist; install local-deep-research there or pass --ldr-command.")
        return 1

    from core.database import SessionLocal
    from src.runtime_paths import get_app_root

    db_file = Path(get_app_root()) / "data" / "app.db"
    if db_file.exists():
        backup = db_file.with_name(f"app.db.bak_rapidmlx_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(db_file, backup)
        print(f"\nBacked up {db_file.name} -> {backup.name}")
    db = SessionLocal()
    try:
        for line in register(db, args.model, args.port, args.research, args.ldr_command):
            print("done: " + line)
    finally:
        db.close()
    print("\nStart the engine with: scripts/rapid_mlx.sh start " + args.model + "   then open Odysseus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
