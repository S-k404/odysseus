"""How much memory a Docker Model Runner model needs, and how much the Mac keeps back.

Standard library only, on purpose: ``src/docker_model_runner.py`` (the load guard) and
``~/.local/bin/dmr_schema_proxy.py`` (the guard in front of n8n's model traffic) both use
it, and the proxy runs outside Odysseus's virtualenv.
"""

import os
import re
from typing import Optional

SIZE_UNITS = {"kib": 1 / 2 ** 20, "mib": 1 / 2 ** 10, "gib": 1.0, "kb": 1e3 / 2 ** 30, "mb": 1e6 / 2 ** 30, "gb": 1e9 / 2 ** 30}


def weights_gb(entry: Optional[dict]) -> Optional[float]:
    """Model file size in GiB from DMR's ``config.size`` ("14.29GiB", "4.28GB", "934.69MiB")."""
    raw = str(((entry or {}).get("config") or {}).get("size") or "")
    m = re.match(r"\s*([\d.]+)\s*([KMG]i?B)\s*$", raw, re.I)
    return float(m.group(1)) * SIZE_UNITS[m.group(2).lower()] if m else None


def gguf_int(gguf: dict, suffix: str) -> Optional[int]:
    for key, value in gguf.items():
        if key.endswith(suffix):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None
    return None


def estimate_load_gb(entry: Optional[dict], context: Optional[int]) -> Optional[float]:
    """GiB a model needs once loaded: weights + KV cache at its served context + buffers.

    The KV cache is read from the model's own metadata (layers, KV heads, head size,
    and how often attention runs on hybrid models). Checked against measured loads:
    qwen3-8b @32k 10 GB (estimate ~11), qwen3.6-35b @128k 19 GB (estimate ~19).
    """
    weights = weights_gb(entry)
    if weights is None:
        return None
    gguf = ((entry or {}).get("config") or {}).get("gguf") or {}
    ctx = context or 0
    layers = gguf_int(gguf, ".block_count")
    kv_heads = gguf_int(gguf, ".attention.head_count_kv") or gguf_int(gguf, ".attention.head_count")
    key_len = gguf_int(gguf, ".attention.key_length")
    if not key_len:
        emb, heads = gguf_int(gguf, ".embedding_length"), gguf_int(gguf, ".attention.head_count")
        key_len = emb // heads if emb and heads else None
    if layers and kv_heads and key_len and ctx:
        value_len = gguf_int(gguf, ".attention.value_length") or key_len
        attention_layers = layers / (gguf_int(gguf, ".full_attention_interval") or 1)
        kv = ctx * attention_layers * kv_heads * (key_len + value_len) * 2 / 2 ** 30  # fp16
        return weights + kv + 1.5
    return weights * 1.15 + 1.0 + (ctx / 32768 * 2.5 if ctx else 0.0)


def ram_reserve_gb(total_gb: float) -> float:
    """GB the load guard keeps back for macOS and your apps: 10% of RAM, at least 4 GB.

    ``ODYSSEUS_RAM_RESERVE_GB`` overrides it. 0 lets a model use every free byte; a negative
    value also counts that many GB of other apps' memory as pageable, which accepts some
    swapping to fit a bigger model.
    """
    default = max(4.0, 0.10 * total_gb)
    try:
        raw = os.getenv("ODYSSEUS_RAM_RESERVE_GB", "").strip()
        return float(raw) if raw else default
    except ValueError:
        return default
