"""Keep local models from taking the Mac down: src/memory_guard.py + the load check."""

import asyncio
import sys

import pytest

from src import docker_model_runner as dmr
from src import memory_guard as mg

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                   610833.
Pages active:                                 893577.
Pages inactive:                               786503.
Pages wired down:                             294539.
Pages purgeable:                               19128.
"Translation faults":                     2811657452.
File-backed pages:                            420211.
Anonymous pages:                             1081258.
Pages stored in compressor:                   965505.
Pages occupied by compressor:                 496546.
"""
GIB = 2 ** 30
URL = "http://127.0.0.1:12434/engines/v1"


def _fake_run(pressure="1"):
    answers = {
        ("sysctl", "-n", "hw.memsize"): str(48 * GIB),
        ("vm_stat",): VM_STAT,
        ("sysctl", "-n", "kern.memorystatus_vm_pressure_level"): pressure,
        ("sysctl", "-n", "vm.swapusage"): "total = 3072.00M  used = 1536.00M  free = 1536.00M  (encrypted)",
    }
    return lambda *cmd: answers[cmd]


def test_vm_stat_is_parsed_including_quoted_labels():
    pages = mg.parse_vm_stat(VM_STAT)
    assert pages["page_size"] == 16384
    assert pages["anonymous pages"] == 1081258 and pages["pages occupied by compressor"] == 496546


def test_snapshot_counts_memory_like_activity_monitor(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    snap = mg.snapshot(_fake_run("2"))
    used = (1081258 + 294539 + 496546) * 16384 / GIB
    assert snap["used_gb"] == pytest.approx(used) and snap["available_gb"] == pytest.approx(48 - used)
    assert snap["swap_used_gb"] == pytest.approx(1.5) and snap["pressure_name"] == "warning"


def test_snapshot_is_none_off_macos_or_when_unreadable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert mg.snapshot(_fake_run()) is None
    monkeypatch.setattr(sys, "platform", "darwin")
    assert mg.snapshot(lambda *cmd: "") is None


# ── refusing a load that cannot fit ──────────────────────────────────────────

def _entry(name, size):
    return {"id": f"sha256:{name}", "tags": [name], "config": {"format": "gguf", "size": size}}


ENTRIES = [_entry("big:35b", "14.29GiB"), _entry("small:8b", "4.68GiB"), _entry("other:30b", "17.28GiB")]


def _setup(monkeypatch, available, resident=(), pressure=1, total=48.0):
    monkeypatch.setattr(dmr, "_runner_models", lambda url, timeout=3.0: ENTRIES)
    monkeypatch.setattr(dmr, "resident_models", lambda url, timeout=3.0: list(resident))
    monkeypatch.setattr(dmr, "_maybe_dmr", lambda root: True)
    monkeypatch.setattr(mg, "snapshot", lambda: {
        "total_gb": total, "used_gb": total - available, "available_gb": available,
        "pressure": pressure, "swap_used_gb": 0.0,
    })
    monkeypatch.delenv("ODYSSEUS_RAM_GUARD", raising=False)


def test_load_that_does_not_fit_is_refused_with_a_clear_reason(monkeypatch):
    _setup(monkeypatch, available=11.5)
    reason = dmr.ram_block_reason(URL, "big:35b")
    assert reason and "needs about 17 GB" in reason and "ODYSSEUS_RAM_GUARD=0" in reason


def test_load_that_fits_is_allowed(monkeypatch):
    _setup(monkeypatch, available=30.0)
    assert dmr.ram_block_reason(URL, "big:35b") is None


def test_other_resident_models_are_counted_as_reclaimable(monkeypatch):
    # 8 GB free, but the 17 GB model in memory is unloaded before this one loads.
    _setup(monkeypatch, available=8.0, resident=["other:30b"])
    assert dmr.ram_block_reason(URL, "big:35b") is None


def test_a_model_that_is_already_loaded_is_never_refused(monkeypatch):
    _setup(monkeypatch, available=1.0, resident=["big:35b"])
    assert dmr.ram_block_reason(URL, "big:35b") is None


def test_critical_pressure_refuses_even_a_small_model(monkeypatch):
    _setup(monkeypatch, available=40.0, pressure=4)
    assert "memory pressure is critical" in dmr.ram_block_reason(URL, "small:8b")


def test_guard_can_be_switched_off_and_skips_unknown_models(monkeypatch):
    _setup(monkeypatch, available=1.0)
    assert dmr.ram_block_reason(URL, "no-such-model") is None
    monkeypatch.setenv("ODYSSEUS_RAM_GUARD", "0")
    assert dmr.ram_block_reason(URL, "big:35b") is None


def test_only_the_model_runner_is_checked(monkeypatch):
    _setup(monkeypatch, available=1.0)
    assert dmr.ram_block_reason("http://127.0.0.1:8080/v1", "big:35b") is None
    assert dmr.ram_block_reason("https://api.openai.com/v1", "gpt-4o") is None


@pytest.mark.parametrize(("raw", "gib"), [("14.29GiB", 14.29), ("934.69MiB", 0.9128), ("4.28GB", 3.986), ("junk", None)])
def test_model_sizes_are_parsed(raw, gib):
    got = dmr._weights_gb({"config": {"size": raw}})
    assert got == pytest.approx(gib, rel=1e-3) if gib else got is None


# ── unloading when pressure stays critical ───────────────────────────────────

def _watch(snaps, resident, sustain=2):
    calls = {"unload": 0, "sleeps": []}
    stream = iter(snaps)

    async def sleep(seconds):
        calls["sleeps"].append(seconds)
        if len(calls["sleeps"]) > 12:
            raise asyncio.CancelledError

    async def unload_all():
        calls["unload"] += 1
        return ["big:35b"]

    async def resident_fn():
        return resident

    async def run():
        try:
            await mg.watch(unload_all, resident_fn, sustain=sustain, snapshot_fn=lambda: next(stream), sleep=sleep)
        except (asyncio.CancelledError, StopIteration, RuntimeError):
            pass

    asyncio.run(run())
    return calls


def _snap(pressure):
    return {"pressure": pressure, "available_gb": 0.5, "swap_used_gb": 9.0, "pressure_name": "critical"}


def test_models_are_unloaded_after_sustained_critical_pressure(monkeypatch):
    monkeypatch.setattr(mg, "record_event", lambda *a, **k: None)
    assert _watch([_snap(1), _snap(4), _snap(4)] + [_snap(1)] * 20, ["big:35b"])["unload"] == 1


def test_a_single_critical_reading_is_not_enough(monkeypatch):
    monkeypatch.setattr(mg, "record_event", lambda *a, **k: None)
    assert _watch([_snap(4), _snap(1), _snap(4), _snap(1)] + [_snap(1)] * 20, ["big:35b"])["unload"] == 0


def test_nothing_is_unloaded_when_no_model_is_in_memory(monkeypatch):
    monkeypatch.setattr(mg, "record_event", lambda *a, **k: None)
    assert _watch([_snap(4)] * 6 + [_snap(1)] * 20, [])["unload"] == 0


def test_guard_is_off_outside_macos_and_when_disabled(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert not mg.enabled()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert mg.enabled()
    monkeypatch.setenv("ODYSSEUS_MEMORY_GUARD", "0")
    assert not mg.enabled()
