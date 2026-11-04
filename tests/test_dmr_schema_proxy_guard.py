"""The memory guard in front of n8n's model traffic: dmr_schema_proxy.py + src/dmr_admission.py.

Runs the real proxy file against a fake model runner over real HTTP. Memory is faked, nothing is
loaded or unloaded, and the proxy writes its logs under a temporary HOME.
"""

import http.client
import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src import dmr_admission as adm

_CANDIDATES = [
    Path(os.environ.get("DMR_SCHEMA_PROXY", "")),
    Path.home() / "Documents/Docker/llm-proxy/dmr_schema_proxy.py",
    Path.home() / ".local/bin/dmr_schema_proxy.py",
]
PROXY = next((p for p in _CANDIDATES if p.is_file()), None)
pytestmark = pytest.mark.skipif(PROXY is None, reason="dmr_schema_proxy.py is not on this machine")

GGUF_8B = {"qwen3.block_count": "36", "qwen3.attention.head_count_kv": "8", "qwen3.attention.key_length": "128"}


def _entry(tag, size, gguf=None, context=None):
    config = {"format": "gguf", "size": size, **({"gguf": gguf} if gguf else {}), **({"context_size": context} if context else {})}
    return {"id": f"sha256:{tag}", "tags": [tag], "config": config}


MODELS = [_entry("big:35b", "14.29GiB"), _entry("small:8b", "4.68GiB", GGUF_8B, 32768)]


class Runner:
    """A fake model runner (what the proxy forwards to) that also owns the fake Mac's free memory."""

    def __init__(self):
        self.ps, self.available, self.calls = [], 40.0, []

    def snapshot(self):
        return {"total_gb": 48.0, "used_gb": 48.0 - self.available, "available_gb": self.available, "pressure": 1}


@pytest.fixture
def stack(tmp_path, monkeypatch):
    runner = Runner()

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            runner.calls.append(("GET", self.path))
            self._send(200, runner.ps if self.path == "/engines/ps" else [] if self.path == "/engines/_configure" else MODELS)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"unparsed": raw.decode()}  # the proxy must forward a body it cannot read, untouched
            runner.calls.append(("POST", self.path, body))
            if self.path == "/engines/unload":
                runner.ps = [e for e in runner.ps if e["model_name"] not in body["models"]]
                runner.available += 10.7  # the 8B's memory comes back
            self._send(200, {"ok": True})

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    (tmp_path / "Library/Logs").mkdir(parents=True)
    (tmp_path / ".local/share").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ODYSSEUS_RAM_RESERVE_GB", raising=False)
    monkeypatch.setattr(sys, "argv", ["dmr_schema_proxy.py", "0", str(upstream.server_address[1])])
    spec = importlib.util.spec_from_file_location("dmr_schema_proxy_under_test", PROXY)
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    assert proxy.dmr_admission is adm, "the proxy did not find Odysseus's admission check"
    # The real check, with the fake Mac and no waiting.
    monkeypatch.setattr(adm, "gate", lambda model, up: _gate(runner, model, up))  # the proxy holds this same module
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield runner, server.server_address[1], tmp_path
    server.shutdown()
    upstream.shutdown()


_real_gate = adm.gate


def _gate(runner, model, upstream):
    return _real_gate(model, upstream, snapshot=runner.snapshot, sleep=lambda s: None)


def _chat(port, model="big:35b", path="/engines/v1/chat/completions", raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = raw if raw is not None else json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]})
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, dict(resp.getheaders()), resp.read()


def _chats(runner):
    return [c for c in runner.calls if c[0] == "POST" and c[1].endswith("/chat/completions")]


def test_a_model_that_cannot_fit_is_refused_with_the_reason_and_never_reaches_the_runner(stack):
    runner, port, _ = stack
    runner.available = 11.5
    status, headers, body = _chat(port)
    error = json.loads(body)["error"]
    assert status == 503 and error["type"] == "insufficient_memory"
    assert "needs about 17 GB" in error["message"] and "short" in error["message"]
    assert headers.get("Retry-After") == "30"
    assert _chats(runner) == []


def test_a_model_that_fits_is_forwarded_and_the_earlier_rewrites_still_happen(stack):
    runner, port, _ = stack
    status, _, body = _chat(port)
    assert status == 200 and json.loads(body) == {"ok": True}
    (_, _, sent), = _chats(runner)
    assert sent["max_tokens"] == 12288 and sent["chat_template_kwargs"] == {"enable_thinking": False}


def test_a_model_that_is_already_loaded_is_not_second_guessed(stack):
    runner, port, _ = stack
    runner.ps, runner.available = [{"model_name": "big:35b", "mode": "completion"}], 0.5
    assert _chat(port)[0] == 200
    assert len(_chats(runner)) == 1


def test_an_idle_model_is_unloaded_first_so_models_run_one_after_the_other(stack):
    runner, port, _ = stack
    runner.ps, runner.available = [{"model_name": "small:8b", "mode": "completion", "in_use": False}], 12.0
    assert _chat(port)[0] == 200
    posts = [c for c in runner.calls if c[0] == "POST"]
    assert [c[1] for c in posts] == ["/engines/unload", "/engines/v1/chat/completions"]
    assert posts[0][2] == {"models": ["small:8b"]}


def test_a_model_that_is_mid_reply_is_not_unloaded_under_it(stack, monkeypatch):
    runner, port, _ = stack
    runner.ps, runner.available = [{"model_name": "small:8b", "mode": "completion", "in_use": True}], 12.0
    clock = iter(range(0, 1000))
    monkeypatch.setattr(adm, "gate", lambda model, up: _real_gate(
        model, up, snapshot=runner.snapshot, sleep=lambda s: None, clock=lambda: float(next(clock)), wait_s=5.0))
    status, _, body = _chat(port)
    assert status == 503 and "still generating" in json.loads(body)["error"]["message"]
    assert not [c for c in runner.calls if c[0] == "POST"]  # nothing unloaded, nothing forwarded


def test_other_requests_and_other_paths_are_not_checked(stack):
    runner, port, _ = stack
    runner.available = 1.0
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/engines/v1/models")
    assert conn.getresponse().status == 200
    assert _chat(port, path="/engines/v1/embeddings")[0] == 200
    assert _chat(port, raw="not json")[0] == 200


def test_the_guard_can_be_switched_off_with_a_flag_file(stack):
    runner, port, home = stack
    runner.available = 1.0
    assert _chat(port)[0] == 503
    (home / ".local/share/dmr-guard.off").write_text("")
    assert _chat(port)[0] == 200


def test_the_proxy_does_not_import_from_documents(stack):
    # A launchd job that touches ~/Documents freezes on macOS's privacy prompt (this happened on 2026-11-04).
    # The proxy fixture's HOME is temporary, so check the default path it would use for the real user.
    source = PROXY.read_text()
    assert 'os.path.expanduser("~/.local/share/dmr-guard")' in source
    assert "Documents" not in source.split("GUARD_LIB =")[1].split("\n")[0]


def test_the_installed_copy_of_the_guard_matches_this_checkout():
    installed = Path.home() / ".local/share/dmr-guard/src"
    if not installed.is_dir():
        pytest.skip("the guard is not installed (scripts/dev/install_dmr_guard.sh)")
    repo = Path(__file__).resolve().parent.parent / "src"
    for name in ("dmr_admission.py", "ram_math.py", "memory_guard.py"):
        assert (installed / name).read_text() == (repo / name).read_text(), (
            f"{name} differs from the copy the proxy uses: run scripts/dev/install_dmr_guard.sh --restart")
