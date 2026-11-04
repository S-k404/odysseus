"""Free the RAM Odysseus can safely free, on demand and before a load the guard would refuse.

Only touches what Odysseus owns: models in Docker Model Runner / Ollama, and the
decensor model in its MCP server. It never kills other apps and never runs
``purge`` (which needs sudo). The biggest other apps are listed as a suggestion.
"""

import asyncio
import logging
import os
import re
import signal
import subprocess
from typing import Callable, Dict, List, Optional

from src import memory_guard
from src.docker_model_runner import is_ram_reason, load_block_reason, ram_reserve_gb
from src.llm_core import release_local_models

logger = logging.getLogger(__name__)

# Never suggested: macOS itself, Odysseus's own processes, and the model runners (their
# memory is the loaded model, which free_ram unloads rather than asks the user to close).
_IGNORED_APPS = {
    "kernel_task", "WindowServer", "launchd", "Python", "Odysseus", "odysseus-macos", "mds_stores", "Finder",
    "llama-server", "ollama",
}
_MIN_SUGGEST_GB = 0.5
_UNCENSOR_UNLOAD = "mcp__uncensor__unload_uncensor_model"


def runner_urls() -> List[str]:
    """One base URL per enabled Docker Model Runner / Ollama server."""
    from core.database import ModelEndpoint, SessionLocal
    from src.docker_model_runner import looks_like_dmr, runner_root
    from src.ollama_runner import looks_like_ollama

    db = SessionLocal()
    try:
        urls = [ep.base_url for ep in db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()]  # noqa: E712
    finally:
        db.close()
    seen, out = set(), []
    for url in urls:
        root = runner_root(url or "")
        if root and (looks_like_dmr(url) or looks_like_ollama(url)) and root not in seen:
            seen.add(root)
            out.append(url)
    return out


def _ps(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return ""


_TOP_UNITS = {"K": 1 / 2 ** 20, "M": 1 / 2 ** 10, "G": 1.0, "T": 2.0 ** 10}
_VIRTUAL_MACHINE = "com.apple.Virtualization.VirtualMachine"


def _footprints(run: Callable[..., str], count: int = 80) -> Dict[int, float]:
    """pid -> GiB for the biggest processes, as Activity Monitor counts them.

    ``top`` reports the memory footprint, which includes pages macOS has compressed.
    ``ps`` reports resident size, which leaves those out: it showed a 6.6 GB Docker
    virtual machine as 1.9 GB.
    """
    sizes: Dict[int, float] = {}
    for line in run("top", "-l", "1", "-o", "mem", "-n", str(count), "-stats", "pid,mem").splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+(?:\.\d+)?)([KMGT])[+-]?\s*$", line)
        if m:
            sizes[int(m.group(1))] = float(m.group(2)) * _TOP_UNITS[m.group(3)]
    return sizes


def biggest_apps(run: Callable[..., str] = _ps, limit: int = 4) -> List[Dict[str, object]]:
    """Largest other apps by memory footprint, grouped by app bundle name."""
    sizes = _footprints(run)
    paths: Dict[int, str] = {}
    for line in run("ps", "-axo", "pid=,comm=").splitlines():
        m = re.match(r"\s*(\d+)\s+(.+)$", line)
        if m:
            paths[int(m.group(1))] = m.group(2)
    docker = any("com.docker." in path or "/Docker.app/" in path for path in paths.values())
    totals: Dict[str, float] = {}
    for pid, gb in sizes.items():
        path = paths.get(pid)
        if not path:
            continue
        app = re.search(r"/([^/]+)\.app/", path)
        name = app.group(1) if app else path.rsplit("/", 1)[-1]
        if name == _VIRTUAL_MACHINE:  # Docker Desktop's VM keeps its containers' memory (and more) here
            name = "Docker's virtual machine" if docker else "A virtual machine"
        elif name in _IGNORED_APPS or name.startswith("com.apple."):
            continue
        totals[name] = totals.get(name, 0.0) + gb
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"app": name, "gb": round(gb, 1)} for name, gb in ranked[:limit] if gb >= _MIN_SUGGEST_GB]


async def _unload_decensor_model() -> Optional[str]:
    """Ask the decensor MCP server to drop its ~8 GB inpainting model; None if it isn't running."""
    try:
        from src.tool_utils import get_mcp_manager
        mgr = get_mcp_manager()
        if not mgr or "uncensor" not in getattr(mgr, "_sessions", {}):
            return None
        result = await asyncio.wait_for(mgr.call_tool(_UNCENSOR_UNLOAD, {}), timeout=10)
        # The tool says "unloaded" or "was not loaded"; only the first freed anything.
        return "decensor model" if result.get("exit_code") == 0 and str(result.get("stdout", "")).strip() == "unloaded" else None
    except Exception as e:
        logger.warning("[ram-optimizer] decensor unload failed: %s", e)
        return None


def _rapid_mlx_pidfile() -> str:
    from src.runtime_paths import get_app_root
    return os.path.join(get_app_root(), "logs", "rapid-mlx.pid")


def _rapid_mlx_models() -> List[str]:
    import httpx
    port = os.environ.get("RAPID_MLX_PORT", "8081")
    data = httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=1.5).json().get("data", [])
    return [m.get("id", "") for m in data]


def stop_rapid_mlx(
    keep: str = "",
    pidfile: Optional[str] = None,
    command_of: Callable[[int], str] = lambda pid: _ps("ps", "-o", "command=", "-p", str(pid)),
    served: Optional[Callable[[], List[str]]] = None,
    kill: Callable[[int, int], None] = os.kill,
) -> Optional[str]:
    """Stop the Rapid-MLX engine that scripts/rapid_mlx.sh started (its model is the biggest memory user there is).

    Only that engine: the process in the pid file must really be rapid-mlx (a recycled pid is never killed), and it is
    left alone when ``keep`` is a model it serves, because the chat is using it. Returns what was done, or None.
    """
    path = pidfile or _rapid_mlx_pidfile()
    try:
        pid = int(open(path).read().strip())
    except (OSError, ValueError):
        return None
    if "rapid-mlx" not in command_of(pid):
        return None
    if keep:
        try:
            names = served() if served else _rapid_mlx_models()
        except Exception:
            names = []
        if keep in names:
            return None
    try:
        kill(pid, signal.SIGTERM)
    except OSError:
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    return "unloaded the Rapid-MLX engine"


async def _settled(
    snapshot: Callable[[], Optional[Dict[str, object]]],
    sleep: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    tries: int = 8,
    pause: float = 1.0,
    quiet_gb: float = 0.15,
) -> Optional[Dict[str, object]]:
    """Memory once it has stopped coming back.

    A model's RAM returns when its runner process exits, a moment after the unload call
    answers. Reading memory straight away reports ~0 GB freed and can make the load guard
    refuse a model that fits.
    """
    last = await asyncio.to_thread(snapshot)
    for _ in range(tries):
        if not last:
            break
        await sleep(pause)
        now = await asyncio.to_thread(snapshot)
        if not now:
            break
        settled = float(last["used_gb"]) - float(now["used_gb"]) < quiet_gb
        last = now
        if settled:
            break
    return last


async def free_ram(
    endpoint_urls: List[str],
    keep: str = "",
    snapshot: Callable[[], Optional[Dict[str, object]]] = memory_guard.snapshot,
    apps: Callable[[], List[Dict[str, object]]] = biggest_apps,
    sleep: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    stop_engine: Callable[[str], Optional[str]] = stop_rapid_mlx,
) -> Dict[str, object]:
    """Unload what can be unloaded (everything except ``keep``) and report what happened."""
    before = await asyncio.to_thread(snapshot)
    steps: List[str] = []

    released = await release_local_models(endpoint_urls, keep=keep)
    steps += [f"unloaded {name}" for name in released.get("unloaded", [])]
    skipped = released.get("skipped")  # a reply is generating: unloading would cut it off
    if skipped:
        steps.append("skipped model unload: a reply is generating")

    decensor = await _unload_decensor_model()
    if decensor:
        steps.append(f"unloaded {decensor}")

    engine = await asyncio.to_thread(stop_engine, keep)
    if engine:
        steps.append(engine)

    unloaded_something = any(step.startswith("unloaded") for step in steps)
    after = await _settled(snapshot, sleep) if unloaded_something else await asyncio.to_thread(snapshot)
    freed = None
    if before and after:
        freed = round(max(float(before["used_gb"]) - float(after["used_gb"]), 0.0), 1)
    return {
        "steps": steps,
        "skipped": skipped,
        "freed_gb": freed,
        "available_gb": round(float(after["available_gb"]), 1) if after else None,
        "total_gb": round(float(after["total_gb"]), 1) if after else None,
        "suggestions": await asyncio.to_thread(apps),
    }


def _suggestion_text(suggestions: List[Dict[str, object]]) -> str:
    if not suggestions:
        return ""
    names = ", ".join(f"{s['app']} ({s['gb']:.1f} GB)" for s in suggestions)
    return f" Biggest apps using memory right now: {names}."


async def load_block_reason_after_freeing(
    target_url: str,
    model: str,
    check: Callable[[str, str], Optional[str]] = load_block_reason,
    free: Callable[..., "asyncio.Future"] = free_ram,
) -> Optional[str]:
    """``check`` (the load guard), but when only RAM is short, free what Odysseus can and check again.

    Any other refusal (a vLLM-Metal backend, say) is not about free memory and is returned unchanged.
    """
    reason = await asyncio.to_thread(check, target_url, model)
    if not is_ram_reason(reason):
        return reason
    urls = await asyncio.to_thread(runner_urls)
    report = await free(urls or [target_url], keep=model)
    logger.info("[ram-optimizer] before loading %s: %s", model, report["steps"] or "nothing to free")
    reason = await asyncio.to_thread(check, target_url, model)
    return reason + _suggestion_text(report["suggestions"]) if reason else None


# Specialist tools that load a model of their own, and the GB each needs. Before one runs, other
# models are unloaded if it would not fit: the chat model that asked for it reloads on its next
# reply through the model slot.
_HEAVY_TOOLS_GB = {
    "mcp__image_gen__generate_image": 8.0,
    "mcp__music_gen__generate_music_neural": 6.0,
    "mcp__video_gen__generate_video": 20.0,
    "mcp__uncensor__uncensor_image": 8.0,
    "mcp__uncensor__decensor_image": 8.0,
    "mcp__uncensor__uncensor_folder": 8.0,
    "mcp__uncensor__decensor_folder": 8.0,
}


async def ensure_ram_for_tool(
    qualified_name: str,
    snapshot: Callable[[], Optional[Dict[str, object]]] = memory_guard.snapshot,
    free: Callable[..., "asyncio.Future"] = free_ram,
) -> Optional[List[str]]:
    """Free memory before a heavy specialist tool runs. Returns the steps taken, None if none were needed.

    Never raises and never blocks the tool: if memory still is not enough, the tool reports it itself.
    """
    need = _HEAVY_TOOLS_GB.get(qualified_name)
    if not need:
        return None
    try:
        snap = await asyncio.to_thread(snapshot)
        if not snap:
            return None
        spare = float(snap["available_gb"]) - ram_reserve_gb(float(snap["total_gb"]))
        if need <= spare:
            return None
        urls = await asyncio.to_thread(runner_urls)
        report = await free(urls, keep="")
        logger.info("[ram-optimizer] before %s (needs ~%.0f GB): %s", qualified_name, need, report["steps"] or "nothing to free")
        return report["steps"]
    except Exception as e:
        logger.warning("[ram-optimizer] could not free memory for %s: %s", qualified_name, e)
        return None
