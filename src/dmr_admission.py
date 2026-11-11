"""Admission control for Docker Model Runner, for clients that do not go through Odysseus.

n8n's Assistant calls the model runner directly, so Odysseus's own guard (``docker_model_runner.
ram_block_reason`` and ``_local_model_slot``) never sees it, and its 35B could be loaded next to an
8B and push the Mac into swap. ``~/.local/bin/dmr_schema_proxy.py`` sits in front of that traffic and
asks ``gate()`` before it forwards a chat request. The rules are the same as Odysseus's:

* a model that is already loaded goes straight through;
* otherwise it is loaded only if it fits: free memory, plus what unloading the other models gives
  back, less the reserve (``ram_math.ram_reserve_gb``);
* other models are unloaded first, one big model at a time, but never one that is mid-reply: the
  request waits for it to finish (up to ``WAIT_S``) and is refused if it would not fit even then.

Standard library only (the proxy runs outside Odysseus's virtualenv) and fail-open: if anything here
breaks, the request is forwarded as it would have been without a guard.
"""

import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src import memory_guard
from src.ram_math import estimate_load_gb, ram_reserve_gb

logger = logging.getLogger(__name__)

WAIT_S = 60.0       # how long a request waits for a busy model to finish before it is refused
POLL_S = 1.0
SETTLE_TRIES = 8    # after an unload: seconds to wait for the runner to hand its memory back
SETTLE_QUIET_GB = 0.15


def _norm(name: Optional[str]) -> str:
    """Model names as DMR spells them differently: case, ``docker.io/`` prefix, ``:latest``."""
    n = (name or "").strip().lower()
    for prefix in ("index.docker.io/", "docker.io/"):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n[: -len(":latest")] if n.endswith(":latest") else n


@dataclass
class Decision:
    action: str                                   # "go" | "make_room" | "wait" | "refuse"
    unload: List[str] = field(default_factory=list)
    message: str = ""


def _entry(models: List[dict], name: str) -> Optional[dict]:
    want = _norm(name)
    for entry in models:
        if isinstance(entry, dict) and any(_norm(tag) == want for tag in (entry.get("tags") or [])):
            return entry
    return None


def decide(
    model: str,
    ps: List[dict],
    models: List[dict],
    snap: Optional[Dict[str, object]],
    context_of: Callable[[str], Optional[int]],
    reserve: Optional[float] = None,
) -> Decision:
    """What to do with a request for ``model``, given what is loaded and what the Mac has free."""
    resident = [e for e in ps if isinstance(e, dict) and e.get("model_name") and e.get("mode") != "embedding"]
    if any(_norm(e["model_name"]) == _norm(model) for e in resident):
        return Decision("go")
    entry = _entry(models, model)
    need = estimate_load_gb(entry, context_of(model)) if entry else None
    if need is None or not snap:
        return Decision("go")  # an unknown model or unreadable memory is not ours to refuse

    def size(e: dict) -> float:
        name = e["model_name"]
        return estimate_load_gb(_entry(models, name), context_of(name)) or 0.0

    idle = [e for e in resident if not e.get("in_use")]
    busy = [e for e in resident if e.get("in_use")]
    total = float(snap["total_gb"])
    keep_back = ram_reserve_gb(total) if reserve is None else reserve
    spare = float(snap["available_gb"]) + sum(size(e) for e in idle) - keep_back
    if int(snap.get("pressure", 1)) >= 4:
        return Decision("refuse", message=(
            f"The Mac's memory pressure is critical right now, so {model} was not loaded. Close some apps and try again."))
    if need > spare + sum(size(e) for e in busy):
        used = float(snap["used_gb"]) - sum(size(e) for e in idle)
        return Decision("refuse", message=(
            f"{model} needs about {need:.0f} GB of memory, but only about {max(spare, 0):.0f} GB can be spared "
            f"right now ({used:.0f} of {total:.0f} GB are in use by other apps), {need - max(spare, 0):.0f} GB short. "
            "Odysseus's memory guard stopped the load so the Mac does not swap itself to a halt. Close some apps, "
            "or use a smaller model."))
    if busy:
        names = ", ".join(e["model_name"] for e in busy)
        return Decision("wait", message=f"{names} is still generating and {model} needs its memory; try again in a moment.")
    if idle:
        return Decision("make_room", unload=[e["model_name"] for e in idle])
    return Decision("go")


def _get_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _post_json(url: str, body: dict, timeout: float = 60.0) -> object:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        try:
            return json.loads(r.read())
        except Exception:
            return {}


def _context(upstream: str, models: List[dict], name: str, get: Callable[..., object]) -> Optional[int]:
    """Context size DMR serves ``name`` with: a ``configure`` override, else the packaged size."""
    try:
        overrides = get(f"{upstream}/engines/_configure")
    except Exception:
        overrides = []
    for cfg in overrides if isinstance(overrides, list) else []:
        if isinstance(cfg, dict) and _norm(cfg.get("Model")) == _norm(name):
            size = (cfg.get("Config") or {}).get("context-size")
            if isinstance(size, int) and size > 0:
                return size
    size = (((_entry(models, name) or {}).get("config") or {}).get("context_size"))
    return size if isinstance(size, int) and size > 0 else None


def _settle(snapshot: Callable[[], Optional[Dict[str, object]]], sleep: Callable[[float], None]) -> None:
    """Wait until memory stops coming back: a model's RAM returns when its runner process exits."""
    sleep(1.0)
    last = snapshot()
    for _ in range(SETTLE_TRIES):
        if not last:
            return
        sleep(1.0)
        now = snapshot()
        if not now:
            return
        quiet = float(last["used_gb"]) - float(now["used_gb"]) < SETTLE_QUIET_GB
        last = now
        if quiet:
            sleep(0.5)
            return


def gate(
    model: str,
    upstream: str,
    *,
    get: Callable[..., object] = _get_json,
    post: Callable[..., None] = _post_json,
    snapshot: Callable[[], Optional[Dict[str, object]]] = memory_guard.snapshot,
    sleep: Callable[[float], None] = time.sleep,
    wait_s: float = WAIT_S,
    clock: Callable[[], float] = time.monotonic,
) -> Optional[str]:
    """None to forward the request, or the message to answer with when it must not run.

    ``upstream`` is the runner's root, e.g. ``http://127.0.0.1:12434``.
    """
    try:
        deadline = clock() + wait_s
        unloads = 0
        while True:
            ps, models = get(f"{upstream}/engines/ps"), get(f"{upstream}/models")
            if not isinstance(ps, list) or not isinstance(models, list):
                return None  # not a model runner we understand
            d = decide(model, ps, models, snapshot(), lambda m: _context(upstream, models, m, get))
            if d.action == "go":
                return None
            if d.action == "refuse":
                return d.message
            if d.action == "make_room":
                if unloads >= 2:
                    if clock() >= deadline:
                        return f"Cannot load {model}: previous model(s) ({', '.join(d.unload)}) could not be unloaded."
                    sleep(POLL_S)
                    continue
                unloads += 1
                logger.info("[dmr-admission] unloading %s before loading %s", ", ".join(d.unload), model)
                res = post(f"{upstream}/engines/unload", {"models": d.unload})
                if isinstance(res, dict) and res.get("unloaded_runners") == 0:
                    # Model is currently busy generating; wait for it rather than failing open
                    if clock() >= deadline:
                        return f"{', '.join(d.unload)} is still generating and {model} needs its memory; try again in a moment."
                    sleep(POLL_S)
                    continue
                _settle(snapshot, sleep)
                continue
            if clock() >= deadline:  # wait
                return d.message
            sleep(POLL_S)
    except Exception as e:  # fail open
        logger.warning("[dmr-admission] could not check %s, letting it through: %s", model, e)
        return None
