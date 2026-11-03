"""Free Ollama's memory when Odysseus moves to a different model.

Ollama keeps a model loaded for five minutes after its last request, so switching
models leaves the old one resident next to the new one, and on a Mac that means swap.
Same contract as ``docker_model_runner.unload_other_models``: callers hold Odysseus's
local-model lock, embedding models stay, nothing here raises.
"""

import logging
import os
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from src.docker_model_runner import runner_root, unload_enabled

logger = logging.getLogger(__name__)

DEFAULT_ROOT = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")


def looks_like_ollama(endpoint_url: str) -> bool:
    parsed = urlparse(endpoint_url or "")
    return parsed.port == 11434 or "ollama" in (parsed.hostname or "").lower()


def _same_model(loaded: str, wanted: str) -> bool:
    """``qwen3`` and ``qwen3:latest`` are one model to Ollama."""
    def norm(name: str) -> str:
        name = (name or "").strip()
        return name[: -len(":latest")] if name.endswith(":latest") else name
    return bool(wanted) and norm(loaded) == norm(wanted)


async def _loaded(client: httpx.AsyncClient, root: str) -> Optional[List[str]]:
    """Names of the models Ollama has in memory, or None if this isn't Ollama."""
    r = await client.get(f"{root}/api/ps")
    if not r.is_success:
        return None
    data = r.json()
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None
    names = []
    for entry in models:
        name = entry.get("name") or entry.get("model") if isinstance(entry, dict) else None
        if name:
            names.append(name)
    return names


async def _unload(client: httpx.AsyncClient, root: str, names: List[str]) -> List[str]:
    done = []
    for name in names:
        # keep_alive 0 on an empty generate request is Ollama's documented way to unload.
        r = await client.post(f"{root}/api/generate", json={"model": name, "keep_alive": 0}, timeout=60.0)
        if r.is_success:
            done.append(name)
        else:
            logger.warning("[ollama] unloading %s failed (HTTP %s)", name, r.status_code)
    return done


async def unload_other_models(endpoint_url: str, model: str) -> List[str]:
    """Unload every Ollama model except ``model``; returns the names unloaded."""
    root = runner_root(endpoint_url)
    if not unload_enabled() or not root or not looks_like_ollama(endpoint_url):
        return []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            loaded = await _loaded(client, root)
            # Embedding models are small and RAG/memory lookups use them alongside chat.
            others = [n for n in loaded or [] if not _same_model(n, model) and "embed" not in n.lower()]
            if not others:
                return []
            logger.info("[ollama] unloading %s before loading %s", ", ".join(others), model)
            return await _unload(client, root, others)
    except Exception as e:
        logger.warning("[ollama] could not unload other models: %s", e)
        return []


async def resident_models(endpoint_url: str = DEFAULT_ROOT) -> List[str]:
    root = runner_root(endpoint_url)
    if not root:
        return []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            return [n for n in await _loaded(client, root) or [] if "embed" not in n.lower()]
    except Exception:
        return []


async def unload_all(endpoint_url: str = DEFAULT_ROOT) -> List[str]:
    """Unload every chat model regardless of the opt-out: for the memory emergency."""
    root = runner_root(endpoint_url)
    names = await resident_models(endpoint_url)
    if not root or not names:
        return []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            return await _unload(client, root, names)
    except Exception as e:
        logger.warning("[ollama] emergency unload failed: %s", e)
        return []
