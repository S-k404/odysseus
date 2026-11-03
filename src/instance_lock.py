"""One Odysseus server per data directory.

The Docker container and the native Mac app can both point at ./data. Two
servers on one data directory each run the task scheduler, email pollers and
nightly jobs, so scheduled tasks fire twice and both write the same SQLite
database. On startup the server claims ``<data>/.server-instance.json`` and
refreshes it every few seconds; a second server that finds a fresh claim from
another process refuses to start and says which server holds the folder.

A claim goes stale when its heartbeat stops (crash, ``kill -9``, container
removed) or when its process is gone on this machine, so a restart is never
blocked for long. A server that is shutting down marks its claim "stopping", and
a new server waits up to 30 s for it to clear instead of refusing, so quitting
and reopening the Mac app works even while the old server closes its MCP servers. Set ``ODYSSEUS_SINGLE_INSTANCE=0`` to turn the check off.
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from typing import Optional

from core.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

LOCK_NAME = ".server-instance.json"
HEARTBEAT_SECONDS = 10.0
STALE_AFTER_SECONDS = 35.0
STOPPING_WAIT_SECONDS = 30.0


class DataDirInUse(RuntimeError):
    """Another live Odysseus server already uses this data directory."""


def enabled() -> bool:
    return os.getenv("ODYSSEUS_SINGLE_INSTANCE", "true").strip().lower() not in {"0", "false", "no", "off"}


def _runtime() -> str:
    return "docker" if os.path.exists("/.dockerenv") else "native"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def describe(claim: dict) -> str:
    where = "Docker container" if claim.get("runtime") == "docker" else "native server"
    port = claim.get("port") or "?"
    return f"{where} on port {port} (pid {claim.get('pid')}, host {claim.get('host')})"


class InstanceLock:
    def __init__(self, data_dir: str, port: Optional[str] = None):
        self.path = os.path.join(data_dir, LOCK_NAME)
        self.claim = {
            "id": uuid.uuid4().hex,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "runtime": _runtime(),
            "port": port,
        }
        self._task: Optional[asyncio.Task] = None

    def _read(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _is_live_other(self, current: Optional[dict]) -> bool:
        if not current or current.get("id") == self.claim["id"]:
            return False
        try:
            age = time.time() - float(current.get("heartbeat", 0))
        except (TypeError, ValueError):
            return False
        if age > STALE_AFTER_SECONDS:
            return False
        # Same machine: trust the process table over the heartbeat, so a
        # crashed server can be restarted straight away.
        if current.get("host") == self.claim["host"]:
            pid = current.get("pid")
            if not isinstance(pid, int) or pid == self.claim["pid"] or not _pid_alive(pid):
                return False
        return True

    def _write(self) -> None:
        atomic_write_json(self.path, {**self.claim, "heartbeat": time.time()}, indent=2)

    def mark_stopping(self) -> None:
        """Shutdown has begun: a server starting now waits for this claim to clear
        instead of refusing, since closing the MCP servers takes several seconds."""
        self.claim["stopping"] = True
        try:
            self._write()
        except Exception as e:
            logger.debug("could not mark instance claim as stopping: %s", e)

    def acquire(self, wait_seconds: float = STOPPING_WAIT_SECONDS) -> None:
        deadline = time.monotonic() + wait_seconds
        announced = False
        while True:
            current = self._read()
            if not self._is_live_other(current):
                break
            # Quitting and reopening the Mac app starts the new server while the old
            # one is still shutting down; only a holder that is not stopping, or one
            # that never lets go, is a real conflict.
            if not current.get("stopping") or time.monotonic() >= deadline:
                raise DataDirInUse(
                    f"{os.path.dirname(self.path)} is already in use by another Odysseus "
                    f"{describe(current)}. Stop that server first (for the Docker copy: "
                    "`docker compose stop odysseus`), or point this one at a different "
                    "folder with ODYSSEUS_DATA_DIR."
                )
            if not announced:
                logger.info("Waiting for the previous Odysseus %s to finish shutting down...", describe(current))
                announced = True
            time.sleep(0.5)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._write()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                current = self._read()
                if self._is_live_other(current):
                    logger.error(
                        "Another Odysseus %s took over this data directory; "
                        "two servers are now sharing it.", describe(current),
                    )
                    continue
                self._write()
            except Exception as e:
                logger.debug("instance heartbeat failed: %s", e)

    def start_heartbeat(self) -> None:
        self._task = asyncio.create_task(self._heartbeat())

    async def release(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        current = self._read()
        if current and current.get("id") == self.claim["id"]:
            try:
                os.remove(self.path)
            except OSError:
                pass
