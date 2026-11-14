"""Shared plumbing for the neural media tools (neural music, video).

Each generation runs in a short-lived worker process (mcp_servers/media_workers/). The
model is loaded when the owner asks for a clip and its memory is returned the moment the
worker exits, so nothing stays resident between requests, and a crash or out-of-memory
kill cannot take the MCP server down.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_DIR = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent)
WORKERS_DIR = Path(__file__).resolve().parent / "media_workers"
MIN_RESERVE_GB = 4.0

_python_cache: Dict[tuple, Optional[str]] = {}


def error(message: str, **extra: Any) -> str:
    return json.dumps({"status": "error", "error": message, **extra}, indent=2)


def hf_cache_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def model_downloaded(repo_id: str) -> bool:
    """Whether a Hugging Face model is already in the local cache (no network)."""
    snapshots = hf_cache_dir() / ("models--" + repo_id.replace("/", "--")) / "snapshots"
    try:
        return snapshots.is_dir() and any(snapshots.iterdir())
    except OSError:
        return False


def _has_modules(python: str, modules: tuple) -> bool:
    code = "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in sys.argv[1:]) else 1)"
    try:
        return subprocess.run([python, "-I", "-c", code, *modules], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def find_python(modules: tuple) -> Optional[str]:
    """First interpreter that can import every module (read-only use; nothing is installed)."""
    if modules in _python_cache:
        return _python_cache[modules]
    candidates: List[str] = []
    if os.environ.get("ODYSSEUS_MEDIA_PYTHON"):
        candidates.append(os.environ["ODYSSEUS_MEDIA_PYTHON"])
    candidates += [
        sys.executable,
        str(REPO_DIR / ".venv" / "bin" / "python"),
        str(REPO_DIR.parent / "odysseus-image-tools" / ".venv" / "bin" / "python"),
    ]
    found = next((c for c in dict.fromkeys(candidates) if Path(c).is_file() and _has_modules(c, modules)), None)
    _python_cache[modules] = found
    return found


def memory_snapshot() -> Optional[Dict[str, Any]]:
    try:
        sys.path.insert(0, str(REPO_DIR))
        from src import memory_guard
        return memory_guard.snapshot()
    except Exception:
        return None


def not_enough_memory(need_gb: float, snapshot: Optional[Callable[[], Optional[Dict[str, Any]]]] = None) -> Optional[str]:
    """A message if loading ``need_gb`` would not fit in free memory (less a reserve), else None."""
    snap = (snapshot or memory_snapshot)()
    if not snap:
        return None
    spare = float(snap["available_gb"]) - max(MIN_RESERVE_GB, 0.10 * float(snap["total_gb"]))
    if need_gb <= spare:
        return None
    return (
        f"This needs about {need_gb:.0f} GB of free memory, but only about {max(spare, 0):.0f} GB can be spared "
        f"right now ({float(snap['used_gb']):.0f} of {float(snap['total_gb']):.0f} GB are in use). Use Optimise memory "
        "(the menu bar item or the model picker) or close some apps, then try again."
    )


def run_worker(python: str, worker: str, args: List[str], timeout: int) -> Dict[str, Any]:
    """Run a worker script; it prints one JSON object as its last stdout line."""
    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1", TOKENIZERS_PARALLELISM="false")
    try:
        proc = subprocess.run([python, str(WORKERS_DIR / worker), *args], capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Generation did not finish within {timeout // 60} minutes and was stopped."}
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if lines:
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            pass
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
    if proc.returncode < 0:
        # Killed by a signal: on a Mac under memory pressure that is almost always the OOM killer.
        return {"status": "error", "error": "The generation process was killed (most likely out of memory). "
                                            "Free memory with Optimise memory and try a shorter or smaller clip."}
    return {"status": "error", "error": "The generation process failed: " + (" | ".join(tail) or f"exit code {proc.returncode}")}


def needs_download_message(repo_id: str, size: str) -> str:
    return json.dumps({
        "status": "needs_download",
        "model": repo_id,
        "message": (
            f"The first use downloads {repo_id} from huggingface.co ({size}) into the local Hugging Face cache. "
            "Tell the user and call this tool again with allow_download=true once they agree."
        ),
    }, indent=2)


def serve(name: str, tools: List[dict], handlers: Dict[str, Callable[[Dict[str, Any]], str]]) -> None:
    """Minimal MCP stdio loop (same protocol as the other built-in servers here)."""

    def send(obj: dict) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        req_id, method = req.get("id"), req.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": name, "version": "1.0.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
        elif method == "tools/call":
            params = req.get("params", {})
            handler = handlers.get(params.get("name"))
            if handler:
                try:
                    text = handler(params.get("arguments", {}) or {})
                except Exception as exc:  # a tool bug must come back as text, not kill the server
                    text = error(f"{type(exc).__name__}: {exc}")
            else:
                text = error(f"Unknown tool: {params.get('name')}")
            send({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}]}})
        elif req_id is not None:
            send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
