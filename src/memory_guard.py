"""Keep local models from taking the Mac down.

Two protections, both macOS only (the Docker copy runs on Linux with its own limits):

* ``snapshot()`` reads memory the way Activity Monitor does, so a model load can be
  refused up front (``docker_model_runner.ram_block_reason``) when it clearly would
  not fit and would push the Mac into swap.
* ``watch()`` runs beside the server. If the kernel reports *critical* memory
  pressure for a sustained spell while models are loaded, it unloads them. A
  failed generation is far better than a frozen Mac.

Turn both off with ``ODYSSEUS_MEMORY_GUARD=0`` (the up-front check also honours
``ODYSSEUS_RAM_GUARD=0``).
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

GIB = float(2 ** 30)
PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}


def enabled() -> bool:
    if sys.platform != "darwin":
        return False
    return os.getenv("ODYSSEUS_MEMORY_GUARD", "true").strip().lower() not in {"0", "false", "no", "off"}


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return ""


def parse_vm_stat(text: str) -> Dict[str, int]:
    """``vm_stat`` output -> {"page_size": N, "<lowercased label>": pages}."""
    m = re.search(r"page size of (\d+) bytes", text)
    out = {"page_size": int(m.group(1)) if m else 16384}
    for match in re.finditer(r"^\"?([A-Za-z][A-Za-z ()\-]*?)\"?:\s+(\d+)\.", text, re.M):
        out[match.group(1).strip().lower()] = int(match.group(2))
    return out


def _swap_gb(text: str) -> Dict[str, float]:
    out = {}
    for key in ("total", "used"):
        m = re.search(rf"{key}\s*=\s*([\d.]+)([MGK])", text)
        if m:
            out[key] = float(m.group(1)) * {"K": 1 / 2 ** 20, "M": 1 / 1024, "G": 1.0}[m.group(2)]
    return out


def snapshot(run: Callable[..., str] = _run) -> Optional[Dict[str, object]]:
    """Memory in GB the way Activity Monitor counts it; None off macOS or if unreadable.

    used = app (anonymous) + wired + compressed. File cache is reclaimable, so it
    counts as available.
    """
    if sys.platform != "darwin":
        return None
    try:
        total = int(run("sysctl", "-n", "hw.memsize").strip())
        pages = parse_vm_stat(run("vm_stat"))
        size = pages["page_size"]
        used = (pages["anonymous pages"] + pages["pages wired down"] + pages["pages occupied by compressor"]) * size
        level = int((run("sysctl", "-n", "kern.memorystatus_vm_pressure_level").strip() or "1"))
        swap = _swap_gb(run("sysctl", "-n", "vm.swapusage"))
    except (KeyError, ValueError):
        return None
    return {
        "total_gb": total / GIB,
        "used_gb": used / GIB,
        "available_gb": max(total - used, 0) / GIB,
        "wired_gb": pages.get("pages wired down", 0) * size / GIB,
        "compressed_gb": pages.get("pages occupied by compressor", 0) * size / GIB,
        "swap_used_gb": swap.get("used", 0.0),
        "swap_total_gb": swap.get("total", 0.0),
        "pressure": level,
        "pressure_name": PRESSURE_NAMES.get(level, "normal"),
    }


def event_path() -> str:
    from src.runtime_paths import get_app_root
    return os.path.join(get_app_root(), "logs", "memory-guard.json")


def record_event(snap: Dict[str, object], unloaded: List[str]) -> None:
    """Leave a note the menu bar (and you) can read about the last emergency unload."""
    try:
        os.makedirs(os.path.dirname(event_path()), exist_ok=True)
        with open(event_path(), "w", encoding="utf-8") as f:
            json.dump({
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "reason": f"memory pressure {snap.get('pressure_name')}",
                "available_gb": round(float(snap.get("available_gb", 0)), 1),
                "unloaded": unloaded,
            }, f)
    except OSError as e:
        logger.debug("could not write memory guard event: %s", e)


async def watch(
    unload_all: Callable[[], Awaitable[List[str]]],
    resident: Callable[[], Awaitable[List[str]]],
    *,
    interval: float = 5.0,
    sustain: int = 2,
    cooldown: float = 60.0,
    snapshot_fn: Callable[[], Optional[Dict[str, object]]] = snapshot,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Unload every model when memory pressure stays critical for ``sustain`` checks."""
    critical = 0
    while True:
        await sleep(interval)
        try:
            snap = await asyncio.to_thread(snapshot_fn)
            if not snap or int(snap["pressure"]) < 4:
                critical = 0
                continue
            critical += 1
            if critical < sustain:
                continue
            critical = 0
            if not await resident():
                continue
            logger.error(
                "[memory-guard] memory pressure is critical (%.1f GB available, %.1f GB swap); unloading models",
                snap["available_gb"], snap["swap_used_gb"],
            )
            unloaded = await unload_all()
            record_event(snap, unloaded)
            await sleep(cooldown)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("[memory-guard] check failed: %s", e)
