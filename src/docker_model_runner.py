"""Docker Model Runner helpers: real serving context and one-model-at-a-time.

Docker Model Runner (DMR) serves an OpenAI-compatible API under ``/v1`` or
``/engines/v1`` plus its own management API at the server root:

* ``GET  /models``          — pulled models, each with the packaged
                              ``config.context_size``
* ``GET  /engines/_configure`` — runtime overrides from ``docker model
                              configure`` (``Config["context-size"]``)
* ``GET  /engines/ps``      — models currently loaded in memory
* ``POST /engines/unload``  — ``{"models": [...]}`` frees those runners
* ``GET  /engines/status``  — installed backends (llama.cpp, vllm, mlx, …)

DMR keeps a model loaded after use and starts llama.cpp with ``--no-mmap``,
so switching models leaves the previous one fully resident until its idle
timeout. On a laptop two large models at once push macOS into swap; this
module lets Odysseus unload the previous model before the next one loads.

On macOS, safetensors models go to the vLLM-Metal backend, which reserves
about 90% of RAM whatever the model's size, so a 4 GB model can still take
the whole Mac down. Those loads are refused unless explicitly allowed.
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Roots that answered /engines/ps with something other than DMR's list are
# remembered briefly so plain llama.cpp / Ollama / LM Studio servers are not
# probed on every request.
_NOT_DMR_UNTIL: Dict[str, float] = {}
_NOT_DMR_TTL = 300.0

# Short cache of /models and /engines/status per root: they only change when
# models are pulled or backends installed, and the guard runs per request.
_CACHE: Dict[str, Tuple[float, object]] = {}
_CACHE_TTL = 30.0


def unload_enabled() -> bool:
    return os.getenv("ODYSSEUS_UNLOAD_OTHER_LOCAL_MODELS", "true").lower() not in {"0", "false", "no", "off"}


def runner_root(endpoint_url: str) -> Optional[str]:
    """Server root for an OpenAI-style endpoint URL (strips /engines…, /v1…)."""
    parsed = urlparse(endpoint_url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path
    for marker in ("/engines", "/v1"):
        idx = path.find(marker)
        if idx >= 0:
            path = path[:idx]
            break
    return f"{parsed.scheme}://{parsed.netloc}{path.rstrip('/')}"


def allow_vllm_metal() -> bool:
    return os.getenv("ODYSSEUS_ALLOW_VLLM_METAL", "false").lower() in {"1", "true", "yes", "on"}


def looks_like_dmr(endpoint_url: str) -> bool:
    """Only Docker Model Runner addresses are probed, so llama.cpp, Ollama and
    LM Studio servers never see the extra management requests."""
    parsed = urlparse(endpoint_url or "")
    return (
        parsed.port == 12434
        or "/engines" in parsed.path
        or (parsed.hostname or "").endswith("model-runner.docker.internal")
    )


def _maybe_dmr(root: str) -> bool:
    return _NOT_DMR_UNTIL.get(root, 0.0) < time.monotonic()


def _mark_not_dmr(root: str) -> None:
    _NOT_DMR_UNTIL[root] = time.monotonic() + _NOT_DMR_TTL


def _cached_get(root: str, path: str, timeout: float):
    """GET ``root + path`` as JSON through the short cache; None on failure."""
    key = root + path
    hit = _CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        r = httpx.get(f"{root}{path}", timeout=timeout)
    except Exception:
        return None
    if r.status_code == 404:
        _mark_not_dmr(root)
        return None
    try:
        data = r.json() if r.is_success else None
    except ValueError:
        data = None
    if data is not None:
        _CACHE[key] = (time.monotonic() + _CACHE_TTL, data)
    return data


def _runner_models(endpoint_url: str, timeout: float = 3.0) -> Optional[list]:
    """DMR's /models list, or None if ``endpoint_url`` isn't DMR."""
    root = runner_root(endpoint_url)
    if not root or not looks_like_dmr(endpoint_url) or not _maybe_dmr(root):
        return None
    entries = _cached_get(root, "/models", timeout)
    if entries is None:
        return None
    # Untagged variants (left behind by `docker model package`) have no tags.
    if not isinstance(entries, list) or not all(isinstance(e, dict) and "id" in e and "config" in e for e in entries):
        _mark_not_dmr(root)
        return None
    return entries


def _model_entry(entries: list, model: str) -> Optional[dict]:
    for entry in entries:
        if model in (entry.get("tags") or []):
            return entry
    return None


def _weights_key(entry: dict) -> Optional[tuple]:
    """What identifies an entry's weights, ignoring the packaged context size."""
    cfg = entry.get("config") or {}
    key = tuple(cfg.get(k) for k in ("format", "architecture", "parameters", "quantization", "size"))
    return key if all(key) else None


def hide_untagged_duplicates(
    endpoint_url: str, model_ids: List[str], keep: Optional[List[str]] = None, timeout: float = 1.5
) -> List[str]:
    """Drop untagged ``sha256:…`` ids that a listed, tagged model already covers.

    ``docker model package`` leaves the original blob behind, untagged, next to
    the repackaged one, so /v1/models shows the same weights twice. The tagged
    entry is the one to use. An untagged model with no listed tagged twin stays,
    and so does anything in ``keep`` (pinned by the user).
    """
    if not model_ids or not looks_like_dmr(endpoint_url):
        return model_ids
    entries = _runner_models(endpoint_url, timeout)
    if not entries:
        return model_ids
    listed = set(model_ids)
    twins = {
        key
        for e in entries
        if any(t in listed for t in e.get("tags") or []) and (key := _weights_key(e))
    }
    hidden = {e["id"] for e in entries if not e.get("tags") and _weights_key(e) in twins}
    hidden -= set(keep or [])
    return [m for m in model_ids if m not in hidden]


def load_block_reason(endpoint_url: str, model: str, timeout: float = 3.0) -> Optional[str]:
    """Why loading ``model`` would take the Mac down, or None if it's safe."""
    if not model or allow_vllm_metal():
        return None
    entries = _runner_models(endpoint_url, timeout)
    entry = _model_entry(entries, model) if entries else None
    if not entry or (entry.get("config") or {}).get("format") != "safetensors":
        return None
    status = _cached_get(runner_root(endpoint_url) or "", "/engines/status", timeout)
    if not isinstance(status, dict):
        return None
    vllm = str(status.get("vllm") or "")
    mlx = str(status.get("mlx") or "")
    if "metal" not in vllm.lower() or mlx.startswith("Running"):
        return None
    return (
        f"{model} would run on Docker's vLLM-Metal backend, which reserves about 90% "
        "of the Mac's RAM no matter how small the model is. Odysseus blocked it to keep "
        "the Mac responsive. Use a GGUF build of the model instead, or set "
        "ODYSSEUS_ALLOW_VLLM_METAL=1 to load it anyway."
    )


def runner_context_size(endpoint_url: str, model: str, timeout: float = 3.0) -> Optional[int]:
    """Context size DMR serves ``model`` with, or None if this isn't DMR."""
    root = runner_root(endpoint_url)
    if not model:
        return None
    entries = _runner_models(endpoint_url, timeout)
    if entries is None:
        return None
    # `docker model configure --context-size` overrides the packaged size and
    # is only visible through /engines/_configure.
    try:
        r = httpx.get(f"{root}/engines/_configure", timeout=timeout)
        overrides = r.json() if r.is_success else []
    except Exception:
        overrides = []
    for cfg in overrides if isinstance(overrides, list) else []:
        if isinstance(cfg, dict) and cfg.get("Model") == model:
            size = (cfg.get("Config") or {}).get("context-size")
            if isinstance(size, int) and size > 0:
                return size
    entry = _model_entry(entries, model)
    size = ((entry or {}).get("config") or {}).get("context_size")
    if isinstance(size, int) and size > 0:
        return size
    return None


async def unload_other_models(endpoint_url: str, model: str) -> List[str]:
    """Unload every DMR model except ``model``; returns the names unloaded.

    Callers must hold Odysseus's local-model lock so none of these models is
    mid-generation for Odysseus. Embedding runners are left alone: they are
    small and RAG/memory lookups use them alongside chat. Never raises.
    """
    root = runner_root(endpoint_url)
    if not unload_enabled() or not root or not looks_like_dmr(endpoint_url) or not _maybe_dmr(root):
        return []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{root}/engines/ps")
            if r.status_code == 404:
                _mark_not_dmr(root)
                return []
            if not r.is_success:
                return []
            loaded = r.json()
            if not isinstance(loaded, list):
                _mark_not_dmr(root)
                return []
            others = [
                e.get("model_name") for e in loaded
                if isinstance(e, dict)
                and e.get("model_name")
                and e.get("model_name") != model
                and e.get("mode") != "embedding"
            ]
            if not others:
                return []
            logger.info("[model-runner] unloading %s before loading %s", ", ".join(others), model)
            r = await client.post(f"{root}/engines/unload", json={"models": others}, timeout=60.0)
            if not r.is_success:
                logger.warning("[model-runner] unload failed (HTTP %s): %s", r.status_code, r.text[:200])
                return []
            return others
    except Exception as e:
        logger.warning("[model-runner] could not unload other models: %s", e)
        return []
