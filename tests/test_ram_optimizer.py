"""Free RAM on demand and before a refused load: src/ram_optimizer.py + /api/local-models/optimize."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import docker_model_runner as dmr
from src import memory_guard as mg
from src import ram_optimizer as ro

URL = "http://127.0.0.1:12434/engines/v1"
# `top -stats pid,mem`: the memory footprint (compressed pages included), with a unit suffix.
TOP_OUTPUT = """\
PID    MEM
101    6618M
102    3584M
103    2G
104    1464M
105    1233M
106    18G
107    400M-
108    120K
"""
PS_OUTPUT = """\
  101 /System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine
  102 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
  103 /Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper
  104 /System/Library/CoreServices/WindowServer
  105 /opt/homebrew/bin/Python
  106 /opt/homebrew/bin/llama-server
  107 /System/Library/PrivateFrameworks/Foo.framework/com.apple.foo
  108 /usr/sbin/cfprefsd
  200 /Applications/Docker.app/Contents/MacOS/com.docker.virtualization
"""


def _run(top=TOP_OUTPUT, ps=PS_OUTPUT):
    return lambda *cmd: top if cmd[0] == "top" else ps


def _snap(used, total=48.0):
    return {"total_gb": total, "used_gb": used, "available_gb": total - used, "pressure": 1}


def test_biggest_apps_rank_by_footprint_group_helpers_and_skip_system_and_own_processes():
    apps = ro.biggest_apps(_run())
    assert apps == [
        {"app": "Docker's virtual machine", "gb": 6.5},
        {"app": "Google Chrome", "gb": 5.5},
    ]


def test_a_virtual_machine_is_not_called_docker_unless_docker_is_running():
    ps = "\n".join(line for line in PS_OUTPUT.splitlines() if "docker" not in line.lower())
    assert ro.biggest_apps(_run(ps=ps))[0] == {"app": "A virtual machine", "gb": 6.5}


def test_biggest_apps_is_empty_when_top_or_ps_say_nothing():
    assert ro.biggest_apps(lambda *cmd: "") == []


def test_decensor_step_only_counts_when_the_model_was_actually_loaded(monkeypatch):
    from src import tool_utils

    class Manager:
        _sessions = {"uncensor": object()}

        def __init__(self, reply):
            self.reply = reply

        async def call_tool(self, name, arguments):
            assert name == "mcp__uncensor__unload_uncensor_model"
            return self.reply

    for reply, expected in (
        ({"stdout": "unloaded", "stderr": "", "exit_code": 0}, "decensor model"),
        ({"stdout": "was not loaded", "stderr": "", "exit_code": 0}, None),
        ({"stdout": "", "stderr": "boom", "exit_code": 1}, None),
    ):
        monkeypatch.setattr(tool_utils, "get_mcp_manager", lambda r=reply: Manager(r))
        assert asyncio.run(ro._unload_decensor_model()) == expected

    class Absent:
        _sessions = {}

    monkeypatch.setattr(tool_utils, "get_mcp_manager", lambda: Absent())
    assert asyncio.run(ro._unload_decensor_model()) is None


def test_free_ram_reports_what_was_unloaded_and_the_gain(monkeypatch):
    seen = {}

    async def release(urls, keep=""):
        seen["call"] = (urls, keep)
        return {"unloaded": ["qwen3-8b", "qwen2.5:1.5b"]}

    async def decensor():
        return "decensor model"

    monkeypatch.setattr(ro, "release_local_models", release)
    monkeypatch.setattr(ro, "_unload_decensor_model", decensor)
    snaps = _snapshots(34.0, 22.5, 22.5)

    report = asyncio.run(ro.free_ram([URL], keep="qwen3.6", snapshot=snaps, apps=lambda: [], sleep=_no_sleep))

    assert seen["call"] == ([URL], "qwen3.6")
    assert report["steps"] == ["unloaded qwen3-8b", "unloaded qwen2.5:1.5b", "unloaded decensor model"]
    assert report["freed_gb"] == 11.5 and report["available_gb"] == 25.5 and report["total_gb"] == 48.0


def _snapshots(*used):
    """A snapshot function that walks through ``used`` and then repeats the last value."""
    values = list(used)
    return lambda: _snap(values.pop(0) if len(values) > 1 else values[0])


async def _no_sleep(seconds):
    return None


def test_free_ram_waits_for_the_runner_to_hand_its_memory_back_before_measuring(monkeypatch):
    async def release(urls, keep=""):
        return {"unloaded": ["big"]}

    async def decensor():
        return None

    monkeypatch.setattr(ro, "release_local_models", release)
    monkeypatch.setattr(ro, "_unload_decensor_model", decensor)
    # Right after the unload call memory has barely moved; the 19 GB comes back over the next seconds.
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    snaps = _snapshots(40.0, 39.9, 31.0, 21.5, 21.4)
    report = asyncio.run(ro.free_ram([URL], snapshot=snaps, apps=lambda: [], sleep=sleep))

    assert report["freed_gb"] == 18.6 and len(slept) == 3


def test_free_ram_does_not_wait_when_nothing_was_unloaded(monkeypatch):
    async def release(urls, keep=""):
        return {"unloaded": []}

    async def decensor():
        return None

    async def sleep(seconds):
        raise AssertionError("nothing was unloaded, so there is nothing to wait for")

    monkeypatch.setattr(ro, "release_local_models", release)
    monkeypatch.setattr(ro, "_unload_decensor_model", decensor)

    report = asyncio.run(ro.free_ram([URL], snapshot=_snapshots(31.0), apps=lambda: [], sleep=sleep))

    assert report["steps"] == [] and report["freed_gb"] == 0.0


def test_the_wait_for_memory_gives_up_after_a_few_seconds():
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    used = iter(range(40, 0, -1))  # memory that never stops falling
    asyncio.run(ro._settled(lambda: _snap(float(next(used))), sleep, tries=3))

    assert len(slept) == 3


def test_free_ram_says_so_when_a_reply_is_generating(monkeypatch):
    async def release(urls, keep=""):
        return {"unloaded": [], "skipped": "busy"}

    async def decensor():
        return None

    monkeypatch.setattr(ro, "release_local_models", release)
    monkeypatch.setattr(ro, "_unload_decensor_model", decensor)

    report = asyncio.run(ro.free_ram([URL], snapshot=lambda: None, apps=lambda: []))

    assert report["skipped"] == "busy" and report["steps"] == ["skipped model unload: a reply is generating"]
    assert report["freed_gb"] is None


def _guard(monkeypatch, reasons):
    """Make the load guard answer from ``reasons`` in turn, and record whether RAM was freed."""
    answers = iter(reasons)
    freed = []

    async def free(urls, keep=""):
        freed.append(keep)
        return {"steps": ["unloaded x"], "suggestions": [{"app": "Google Chrome", "gb": 5.0}]}

    monkeypatch.setattr(ro, "runner_urls", lambda: [URL])
    return (lambda url, model: next(answers)), free, freed


def test_a_load_that_fits_after_freeing_goes_ahead(monkeypatch):
    check, free, freed = _guard(monkeypatch, ["big needs about 18 GB, but only about 8 GB can be spared right now", None])

    assert asyncio.run(ro.load_block_reason_after_freeing(URL, "big", check=check, free=free)) is None
    assert freed == ["big"]


def test_a_load_that_still_does_not_fit_names_the_biggest_apps(monkeypatch):
    short = "big needs about 18 GB, but only about 8 GB can be spared right now"
    check, free, freed = _guard(monkeypatch, [short, short])

    reason = asyncio.run(ro.load_block_reason_after_freeing(URL, "big", check=check, free=free))

    assert reason.startswith(short) and "Google Chrome (5.0 GB)" in reason


def test_other_refusals_and_no_refusal_free_nothing(monkeypatch):
    for reason in ("would run on Docker's vLLM-Metal backend", None):
        check, free, freed = _guard(monkeypatch, [reason])
        assert asyncio.run(ro.load_block_reason_after_freeing(URL, "big", check=check, free=free)) == reason
        assert freed == []


def test_the_guards_own_ram_messages_are_recognised(monkeypatch):
    entries = [{"id": "sha256:big", "tags": ["big:35b"], "config": {"format": "gguf", "size": "14.29GiB"}}]
    monkeypatch.setattr(dmr, "_runner_models", lambda url, timeout=3.0: entries)
    monkeypatch.setattr(dmr, "resident_models", lambda url, timeout=3.0: [])
    monkeypatch.setattr(dmr, "_maybe_dmr", lambda root: True)
    monkeypatch.delenv("ODYSSEUS_RAM_GUARD", raising=False)
    for pressure, available in ((1, 11.5), (4, 40.0)):
        monkeypatch.setattr(mg, "snapshot", lambda p=pressure, a=available: {
            "total_gb": 48.0, "used_gb": 48.0 - a, "available_gb": a, "pressure": p, "swap_used_gb": 0.0})
        assert dmr.is_ram_reason(dmr.ram_block_reason(URL, "big:35b"))
    assert not dmr.is_ram_reason("would run on Docker's vLLM-Metal backend")
    assert not dmr.is_ram_reason(None)


def test_optimize_endpoint_frees_everything_but_the_model_the_user_is_moving_to(monkeypatch):
    from routes import local_model_routes as routes
    from src.auth_helpers import require_user

    calls = {}

    async def free(urls, keep=""):
        calls["args"] = (urls, keep)
        return {"steps": ["unloaded old"], "freed_gb": 9.4}

    monkeypatch.setattr(routes, "_runner_urls", lambda: [URL])
    monkeypatch.setattr(routes, "free_ram", free)
    app = FastAPI()
    app.include_router(routes.setup_local_model_routes())
    app.dependency_overrides[require_user] = lambda: "admin"

    res = TestClient(app).post("/api/local-models/optimize", json={"model": " keep-me "})

    assert res.status_code == 200 and res.json() == {"steps": ["unloaded old"], "freed_gb": 9.4}
    assert calls["args"] == ([URL], "keep-me")
