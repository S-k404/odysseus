"""Make Docker Compose service names work when Odysseus runs natively.

.env is shared by the Docker stack and the native Mac app. Inside Docker the
companion services are reached by name (``http://speaches:8000/v1``); on the
host those names don't resolve, and docker-compose.yml publishes the same
services on 127.0.0.1 under different ports. When the server is not inside a
container, URL settings that name one of those services are pointed at the
published address, so one .env works for both.
"""

import logging
import os
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# service -> {container port: (env var holding the published port, default)},
# matching the `ports:` entries in docker-compose.yml.
PUBLISHED_PORTS: Dict[str, Dict[int, Tuple[Optional[str], int]]] = {
    "speaches": {8000: ("SPEACHES_PORT", 8000)},
    "searxng": {8080: (None, 8080)},
    "chromadb": {8000: (None, 8100)},
    "ntfy": {80: (None, 8091)},
}


def in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _published(service: str, port: Optional[int], env) -> Optional[int]:
    ports = PUBLISHED_PORTS.get(service) or {}
    if port is None:
        port = next(iter(ports), None)
    mapping = ports.get(port) if port is not None else None
    if not mapping:
        return None
    var, default = mapping
    try:
        return int(env.get(var) or default) if var else default
    except ValueError:
        return default


def host_url(url: str, env=os.environ) -> Optional[str]:
    """``url`` rewritten to the host-published address, or None if unchanged."""
    if not url or "://" not in url:
        return None
    parts = urlsplit(url)
    service = (parts.hostname or "").lower()
    if service not in PUBLISHED_PORTS:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    published = _published(service, port, env)
    if published is None:
        return None
    netloc = f"127.0.0.1:{published}"
    if parts.username:
        auth = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{auth}@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def apply(env=os.environ) -> Dict[str, str]:
    """Rewrite service-name URLs in ``env`` when running natively.

    Returns the variables it changed (name -> new value).
    """
    if in_container():
        return {}
    changed: Dict[str, str] = {}
    for key, value in list(env.items()):
        new = host_url(value, env)
        if new:
            env[key] = new
            changed[key] = new
    # ChromaDB is configured as a host/port pair rather than a URL.
    if (env.get("CHROMADB_HOST") or "").lower() == "chromadb":
        env["CHROMADB_HOST"] = "127.0.0.1"
        changed["CHROMADB_HOST"] = "127.0.0.1"
        port = _published("chromadb", int(env.get("CHROMADB_PORT") or 8000), env)
        if port:
            env["CHROMADB_PORT"] = str(port)
            changed["CHROMADB_PORT"] = str(port)
    return changed
