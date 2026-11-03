"""One server per data directory: src/instance_lock.py."""

import asyncio
import json
import time

import pytest

from src import instance_lock as il


def _claim(path, **fields):
    claim = {"id": "other", "pid": 999999, "host": "elsewhere", "runtime": "docker",
             "port": "7000", "heartbeat": time.time()}
    claim.update(fields)
    path.write_text(json.dumps(claim))


def test_acquire_writes_claim(tmp_path):
    lock = il.InstanceLock(str(tmp_path), port="7860")
    lock.acquire()
    data = json.loads((tmp_path / il.LOCK_NAME).read_text())
    assert data["id"] == lock.claim["id"]
    assert data["port"] == "7860"


def test_fresh_claim_from_other_host_blocks_start(tmp_path):
    _claim(tmp_path / il.LOCK_NAME)
    with pytest.raises(il.DataDirInUse, match="Docker container on port 7000"):
        il.InstanceLock(str(tmp_path)).acquire()


def test_stale_heartbeat_is_taken_over(tmp_path):
    _claim(tmp_path / il.LOCK_NAME, heartbeat=time.time() - il.STALE_AFTER_SECONDS - 5)
    lock = il.InstanceLock(str(tmp_path))
    lock.acquire()
    assert json.loads((tmp_path / il.LOCK_NAME).read_text())["id"] == lock.claim["id"]


def test_dead_process_on_same_host_is_taken_over(tmp_path, monkeypatch):
    lock = il.InstanceLock(str(tmp_path))
    _claim(tmp_path / il.LOCK_NAME, host=lock.claim["host"], pid=424242)
    monkeypatch.setattr(il, "_pid_alive", lambda pid: False)
    lock.acquire()


def test_live_process_on_same_host_blocks_start(tmp_path, monkeypatch):
    lock = il.InstanceLock(str(tmp_path))
    _claim(tmp_path / il.LOCK_NAME, host=lock.claim["host"], pid=424242, runtime="native")
    monkeypatch.setattr(il, "_pid_alive", lambda pid: True)
    with pytest.raises(il.DataDirInUse, match="native server"):
        lock.acquire()


def test_corrupt_claim_is_ignored(tmp_path):
    (tmp_path / il.LOCK_NAME).write_text("{not json")
    il.InstanceLock(str(tmp_path)).acquire()


def test_release_removes_only_own_claim(tmp_path):
    async def run():
        lock = il.InstanceLock(str(tmp_path))
        lock.acquire()
        lock.start_heartbeat()
        await lock.release()
        assert not (tmp_path / il.LOCK_NAME).exists()

        lock = il.InstanceLock(str(tmp_path))
        lock.acquire()
        _claim(tmp_path / il.LOCK_NAME)  # someone else took over
        await lock.release()
        assert (tmp_path / il.LOCK_NAME).exists()

    asyncio.run(run())


def test_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_SINGLE_INSTANCE", "0")
    assert not il.enabled()
    monkeypatch.delenv("ODYSSEUS_SINGLE_INSTANCE")
    assert il.enabled()


def _stopping_holder(tmp_path, monkeypatch, **fields):
    lock = il.InstanceLock(str(tmp_path))
    _claim(tmp_path / il.LOCK_NAME, host=lock.claim["host"], pid=424242, runtime="native", **fields)
    monkeypatch.setattr(il, "_pid_alive", lambda pid: True)
    return lock


def test_server_that_is_shutting_down_is_waited_for(tmp_path, monkeypatch):
    # Quit and reopen the Mac app: the old server is still closing its MCP servers.
    lock = _stopping_holder(tmp_path, monkeypatch, stopping=True)
    path = tmp_path / il.LOCK_NAME
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:  # the old server finishes and removes its claim
            path.unlink()

    monkeypatch.setattr(il.time, "sleep", fake_sleep)
    lock.acquire()

    assert len(sleeps) == 3
    assert json.loads(path.read_text())["id"] == lock.claim["id"]


def test_live_server_that_is_not_stopping_is_refused_without_waiting(tmp_path, monkeypatch):
    lock = _stopping_holder(tmp_path, monkeypatch)
    monkeypatch.setattr(il.time, "sleep", lambda s: pytest.fail("must not wait for a live server"))
    with pytest.raises(il.DataDirInUse):
        lock.acquire()


def test_server_that_never_finishes_stopping_is_refused_after_the_wait(tmp_path, monkeypatch):
    lock = _stopping_holder(tmp_path, monkeypatch, stopping=True)
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(il.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(il.time, "sleep", lambda s: None)
    with pytest.raises(il.DataDirInUse, match="native server"):
        lock.acquire(wait_seconds=25)


def test_stopping_flag_is_written_and_kept_by_later_heartbeat_writes(tmp_path):
    lock = il.InstanceLock(str(tmp_path))
    lock.acquire()
    assert "stopping" not in json.loads((tmp_path / il.LOCK_NAME).read_text())

    lock.mark_stopping()
    lock._write()  # what the heartbeat does

    assert json.loads((tmp_path / il.LOCK_NAME).read_text())["stopping"] is True
