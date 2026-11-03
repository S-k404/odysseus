# src/tts_service.py
"""Multi-provider TTS service — dispatches to local Kokoro, OpenAI-compatible API, or browser."""

import re
import io
import os
import wave
import logging
import hashlib
import httpx
from pathlib import Path
from typing import Optional, Dict, Any

from src.constants import TTS_CACHE_DIR

logger = logging.getLogger(__name__)


def _clean_tts_text(text: str) -> str:
    """Strip internal model thinking, reasoning tags, and markdown markup."""
    if not text:
        return ""
    # Strip complete and unclosed <think>/<thought>/<thinking> tags
    cleaned = re.sub(
        r"<(?:(?:mm:)?think(?:ing)?|thought)(?:\s+[^>]*)?>[\s\S]*?(?:</(?:(?:mm:)?think(?:ing)?|thought)>|$)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Strip channel thoughts (<|channel>thought ... <|channel>response)
    cleaned = re.sub(
        r"<\|channel>thought[\s\S]*?(?:<\|channel>(?:response|text)?|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip prefix thinking and untagged reasoning blocks
    reasoning_prefix_re = re.compile(
        r"^\s*(?:(?:v?iew\s+)?thinking(?:\s+process)?\s*:?|(?:thought|reasoning(?:\s+process)?|reflection|scratchpad|internal\s+monologue)\s*:?|the user |user wants|user asks|user said|we need |i need |i should |i will |i'll |i am going |i have to |i must |let me (?:think|look|see|check|read|review|analyze|parse|figure|draft|write)|they are |the question |i can |looking at |plan:\s*)",
        re.IGNORECASE,
    )
    reply_boundary_re = re.compile(
        r"\n\n(?=(?:Hey|Hi[ !]|Hello|Sure|Certainly|Yes|No[, ]|OK|Here |Absolutely|Of course|Great|Alright|Thanks|Welcome|Good |To answer|In summary|Below is|Here's|(?:Response|Reply|Answer|Final (?:Response|Answer)|Output)\s*:|---+|===+))",
        re.IGNORECASE,
    )
    trimmed = cleaned.lstrip()
    if reasoning_prefix_re.match(trimmed):
        match = reply_boundary_re.search(trimmed)
        if match:
            cleaned = trimmed[match.start() + 2:].lstrip()
            cleaned = re.sub(r"^(?:Response|Reply|Answer|Final (?:Response|Answer)|Output)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        else:
            cleaned = ""
    # Strip tool calls
    cleaned = re.sub(r"\[/?TOOL_CALL\][\s\S]*?(?:\[/TOOL_CALL\]|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<(?:[\w]+:)?(?:tool_call|function_call)>[\s\S]*?(?:</(?:[\w]+:)?(?:tool_call|function_call)>|$)", "", cleaned, flags=re.IGNORECASE)
    # Strip markdown headers/formatting
    cleaned = re.sub(r"#{1,6}\s", "", cleaned)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
    cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
    cleaned = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _safe_speed(value, default: float = 1.0) -> float:
    """Parse the stored tts_speed defensively. The settings layer tolerates
    corrupt/agent-written config, so a non-numeric or empty value (e.g. an agent
    setting "speech speed" = "fast", or a hand-edited settings.json) must not
    crash synthesis or the stats endpoint with a ValueError."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    return speed if speed > 0 else default


class TTSService:
    """Multi-provider TTS service.

    Reads provider config from data/settings.json on each call.
    Providers:
      "disabled"        — no TTS
      "browser"         — client-side Web Speech API (no server synthesis)
      "local"           — Kokoro-82M on GPU
      "endpoint:<id>"   — OpenAI-compatible /audio/speech via ModelEndpoint
    """

    def __init__(self, cache_dir: str = TTS_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._kokoro = None  # lazy-init
        
        try:
            self.max_cache_bytes = int(os.getenv("ODYSSEUS_TTS_CACHE_MAX_BYTES", 500 * 1024 * 1024))
        except ValueError:
            self.max_cache_bytes = 500 * 1024 * 1024

    # ── Settings ──

    def _load_settings(self) -> dict:
        from src.settings import load_settings
        saved = load_settings()
        env_enabled = os.getenv("TTS_ENABLED")
        tts_enabled = (env_enabled.lower() in ("true", "1", "yes")) if env_enabled is not None else saved.get("tts_enabled", True)
        tts_provider = os.getenv("TTS_PROVIDER") or saved.get("tts_provider", "disabled")
        tts_model = os.getenv("TTS_MODEL") or saved.get("tts_model", "tts-1")
        tts_voice = os.getenv("TTS_VOICE") or saved.get("tts_voice", "alloy")
        tts_speed = os.getenv("TTS_SPEED") or saved.get("tts_speed", "1")
        openai_base = os.getenv("TTS_OPENAI_API_BASE", "")
        openai_key = os.getenv("TTS_OPENAI_API_KEY", "")
        return {
            "tts_enabled": tts_enabled,
            "tts_provider": tts_provider,
            "tts_model": tts_model,
            "tts_voice": tts_voice,
            "tts_speed": tts_speed,
            "openai_api_base": openai_base,
            "openai_api_key": openai_key,
        }

    @property
    def available(self) -> bool:
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return False
        provider = settings["tts_provider"]
        if provider == "disabled":
            return False
        if provider == "browser":
            return True  # handled client-side
        if provider == "local":
            kokoro = self._get_kokoro()
            return kokoro is not None and kokoro.available
        if provider == "openai":
            return bool(settings.get("openai_api_base") or os.getenv("TTS_OPENAI_API_BASE"))
        if isinstance(provider, str) and provider.startswith("endpoint:"):
            return True  # assume reachable; errors surface at synthesis time
        return False

    # ── Cache ──

    def _cache_key(self, text: str, provider: str, model: str, voice: str, speed: float = 1.0) -> str:
        raw = f"{provider}|{model}|{voice}|{speed}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[bytes]:
        for ext in (".mp3", ".wav"):
            path = self.cache_dir / f"{key}{ext}"
            if path.exists():
                return path.read_bytes()
        return None

    def _put_cache(self, key: str, data: bytes):
        ext = ".mp3" if (len(data) >= 3 and (data[:3] == b'ID3' or (data[0] == 0xff and (data[1] & 0xe0) == 0xe0))) else ".wav"
        (self.cache_dir / f"{key}{ext}").write_bytes(data)

        self._enforce_cache_limit()

    def _enforce_cache_limit(self):
            """Evicts oldest files if the cache exceeds the configured byte limit."""
            if self.max_cache_bytes <= 0:
                return

            try:
                files = []
                total_size = 0

                # Safely scan files and sum sizes, ignoring files deleted mid-scan
                for f in self.cache_dir.iterdir():
                    try:
                        if f.is_file() and f.suffix.lower() in (".mp3", ".wav"):
                            files.append(f)
                            total_size += f.stat().st_size
                    except OSError:
                        continue

                if total_size > self.max_cache_bytes:
                    logger.info(
                        f"TTS cache ({total_size} bytes) exceeded limit ({self.max_cache_bytes} bytes). Evicting oldest files."
                    )

                    # Sort files by modification time (oldest first)
                    try:
                        files.sort(key=lambda f: f.stat().st_mtime)
                    except OSError as e:
                        logger.warning(f"Failed to sort cache files by mtime: {e}")

                    # Trim down to 80% of max capacity
                    target_size = self.max_cache_bytes * 0.8

                    while files and total_size > target_size:
                        f = files.pop(0)
                        try:
                            size = f.stat().st_size
                            f.unlink()
                            total_size -= size
                        except OSError as e:
                            logger.warning(f"Failed to evict cache file {f}: {e}")
                            continue

            except Exception as e:
                logger.warning(f"Error enforcing TTS cache limit: {e}", exc_info=True)

    def clear_cache(self):
        count = 0
        for f in self.cache_dir.glob("*.*"):
            f.unlink()
            count += 1
        logger.info(f"Cleared {count} cached TTS files")

    # ── Kokoro (local) ──

    def _get_kokoro(self):
        if self._kokoro is None:
            self._kokoro = _KokoroPipeline()
        return self._kokoro

    def _synthesize_openai(self, text: str, base_url: str, api_key: str, model: str, voice: str, speed: float = 1.0) -> Optional[bytes]:
        url = base_url.rstrip("/") + "/audio/speech"
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        # Resolve model name alias for Speaches Kokoro
        effective_model = model
        if effective_model in ("hexgrad/Kokoro-82M", "kokoro", "Kokoro-82M"):
            effective_model = "speaches-ai/Kokoro-82M-v1.0-ONNX"

        payload = {
            "model": effective_model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }

        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60)
            r.raise_for_status()
            logger.info(f"OpenAI TTS: {len(r.content)} bytes from {base_url}")
            return r.content
        except Exception as e:
            logger.error(f"OpenAI TTS synthesis failed: {e}")
            return None

    # ── API endpoint ──

    def _synthesize_api(self, text: str, endpoint_id: str, model: str, voice: str, speed: float = 1.0) -> Optional[bytes]:
        from src.database import SessionLocal, ModelEndpoint

        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == endpoint_id).first()
            if not ep:
                logger.error(f"TTS endpoint {endpoint_id} not found")
                return None
            base_url = ep.base_url.rstrip("/")
            api_key = ep.api_key
        finally:
            db.close()

        url = base_url + "/audio/speech"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        effective_model = model
        if effective_model in ("hexgrad/Kokoro-82M", "kokoro", "Kokoro-82M"):
            effective_model = "speaches-ai/Kokoro-82M-v1.0-ONNX"

        payload = {
            "model": effective_model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }

        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60)
            r.raise_for_status()
            logger.info(f"API TTS: {len(r.content)} bytes from {base_url}")
            return r.content
        except Exception as e:
            logger.error(f"API TTS synthesis failed: {e}")
            return None

    # ── Public interface ──

    def synthesize(self, text: str, use_cache: bool = True) -> Optional[bytes]:
        settings = self._load_settings()
        if settings.get("tts_enabled") is False:
            return None
        provider = settings["tts_provider"]
        model = settings["tts_model"]
        voice = settings["tts_voice"]
        speed = _safe_speed(settings.get("tts_speed", "1"))

        if provider in ("disabled", "browser"):
            return None

        text = _clean_tts_text(text)
        if not text:
            return None

        if len(text) > 5000:
            text = text[:5000]

        if use_cache:
            key = self._cache_key(text, provider, model, voice, speed)
            cached = self._get_cached(key)
            if cached:
                logger.info(f"TTS cache hit ({len(text)} chars)")
                return cached

        audio_data = None

        if provider == "local":
            kokoro = self._get_kokoro()
            if kokoro and kokoro.available:
                audio_data = kokoro.synthesize_raw(text, voice)
            else:
                logger.warning("Kokoro TTS not available")
                return None
        elif provider == "openai":
            base_url = settings.get("openai_api_base") or os.getenv("TTS_OPENAI_API_BASE", "http://speaches:8000/v1")
            api_key = settings.get("openai_api_key") or os.getenv("TTS_OPENAI_API_KEY", "")
            audio_data = self._synthesize_openai(text, base_url, api_key, model, voice, speed)
        elif isinstance(provider, str) and provider.startswith("endpoint:"):
            endpoint_id = provider.split(":", 1)[1]
            audio_data = self._synthesize_api(text, endpoint_id, model, voice, speed)
        else:
            logger.error(f"Unknown TTS provider: {provider}")
            return None

        if audio_data and use_cache:
            key = self._cache_key(text, provider, model, voice, speed)
            self._put_cache(key, audio_data)

        return audio_data

    def synthesize_to_base64(self, text: str) -> Optional[str]:
        import base64
        audio = self.synthesize(text)
        if audio:
            return base64.b64encode(audio).decode("utf-8")
        return None

    def set_voice(self, voice: str):
        """Legacy no-op — voice is now managed via admin settings."""

    def get_stats(self) -> Dict[str, Any]:
        settings = self._load_settings()
        provider = settings["tts_provider"]
        tts_enabled = settings.get("tts_enabled", True)

        cache_files = list(self.cache_dir.glob("*.wav")) + list(self.cache_dir.glob("*.mp3"))
        cache_size = sum(f.stat().st_size for f in cache_files)

        is_available = self.available and tts_enabled
        stats = {
            "available": is_available,
            "ready": is_available,
            "provider": provider,
            "model": settings["tts_model"],
            "voice": settings["tts_voice"],
            "speed": _safe_speed(settings.get("tts_speed", "1")),
            "cache_entries": len(cache_files),
            "cache_size_mb": round(cache_size / (1024 * 1024), 2),
        }

        if provider == "local":
            kokoro = self._get_kokoro()
            stats["model"] = "Kokoro-82M (GPU)" if (kokoro and kokoro.available) else "Kokoro (not loaded)"
        elif provider == "browser":
            stats["model"] = "Browser (Web Speech API)"
        elif provider.startswith("endpoint:"):
            stats["endpoint_id"] = provider.split(":", 1)[1]

        return stats


class _KokoroPipeline:
    """Encapsulates the Kokoro-82M local GPU pipeline."""

    def __init__(self):
        self.pipeline = None
        self.available = False
        self.device = None
        self._init()

    def _init(self):
        try:
            import torch
            from kokoro import KPipeline

            if not torch.cuda.is_available():
                logger.warning("CUDA not available for Kokoro TTS")
                return

            self.device = torch.device("cuda:0")
            with torch.cuda.device(0):
                self.pipeline = KPipeline(lang_code="a")
                if hasattr(self.pipeline, "model"):
                    self.pipeline.model = self.pipeline.model.to(self.device)
            self.available = True
            logger.info("Kokoro-82M TTS pipeline loaded")
        except ImportError as e:
            logger.warning(f"Kokoro TTS not available: {e}")
            logger.warning("Install with: pip install kokoro soundfile")
        except Exception as e:
            logger.error(f"Kokoro init failed: {e}", exc_info=True)

    def synthesize_raw(self, text: str, voice: str = "af_heart") -> Optional[bytes]:
        if not self.available:
            return None
        try:
            import torch
            import numpy as np

            with torch.cuda.device(self.device):
                chunks = []
                for _, _, audio in self.pipeline(text, voice=voice):
                    chunks.append(audio)

            if not chunks:
                return None

            full = np.concatenate(chunks)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes((full * 32767).astype(np.int16).tobytes())
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}", exc_info=True)
            return None


# Module-level singleton
_tts_service = None

def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
