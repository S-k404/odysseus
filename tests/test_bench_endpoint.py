"""scripts/dev/bench_endpoint.py against a tiny local streaming server (no model, no network)."""

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dev" / "bench_endpoint.py"


@pytest.fixture
def bench():
    spec = importlib.util.spec_from_file_location("bench_endpoint", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Server(BaseHTTPRequestHandler):
    """Streams 20 tokens at ~100 per second. A prompt it has seen before gets its first token sooner (a prefix cache)."""

    seen = set()
    send_usage = True

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][0]["content"]
        prefix = prompt.split("\n\nQuestion:")[0]
        time.sleep(0.02 if prefix in self.seen else 0.25)
        self.seen.add(prefix)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(20):
            self.wfile.write(f'data: {json.dumps({"choices": [{"delta": {"content": f"w{i} "}}]})}\n\n'.encode())
            self.wfile.flush()
            time.sleep(0.01)
        if self.send_usage:
            self.wfile.write(f'data: {json.dumps({"choices": [], "usage": {"completion_tokens": 20, "prompt_tokens": 7}})}\n\n'.encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Server.seen = set()
    _Server.send_usage = True
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def test_it_measures_speed_prefix_cache_and_memory(bench, server):
    used = iter([30.0, 31.5])

    report = bench.run(server, "fake", max_tokens=20, memory=lambda: next(used))

    short, cold, warm = (report["results"][k] for k in ("short", "cold", "warm"))
    assert short["tokens"] == cold["tokens"] == warm["tokens"] == 20 and short["token_source"] == "usage"
    assert 30 < short["decode_tok_s"] < 200  # 19 tokens over ~0.2 s
    assert cold["first_token_s"] > warm["first_token_s"]
    assert report["prefix_cache_speedup"] > 2  # the second request had the document cached
    assert report["memory_used_change_gb"] == 1.5


def test_tokens_are_counted_from_chunks_when_the_server_reports_no_usage(bench, server):
    _Server.send_usage = False
    report = bench.run(server, "fake", max_tokens=20, memory=lambda: None)
    assert report["results"]["short"]["token_source"] == "chunks" and report["results"]["short"]["tokens"] == 20
    assert report["memory_used_change_gb"] is None


def test_the_table_is_readable(bench, server):
    text = bench.table("fake", bench.run(server, "m", memory=lambda: 10.0))
    assert text.splitlines()[0] == "fake: m" and "prefix-cache speedup" in text
    assert all(name in text for name in ("short", "cold", "warm"))
