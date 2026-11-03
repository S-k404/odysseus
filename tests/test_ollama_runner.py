"""Ollama: models are freed when Odysseus moves to a different one."""

import asyncio
import json

import httpx
import pytest

from src import llm_core
from src import ollama_runner as ollama

URL = "http://127.0.0.1:11434/v1"
# httpx is one shared module, so patching ollama.httpx patches it everywhere; keep the real class.
_REAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_UNLOAD_OTHER_LOCAL_MODELS", raising=False)


class _FakeOllama:
    """Stands in for httpx.AsyncClient against /api/ps and /api/generate."""

    def __init__(self, names, ps_status=200):
        self.names = names
        self.ps_status = ps_status
        self.requests = []

    def client(self, *args, **kwargs):
        server = self

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode() if request.content else ""
            server.requests.append((request.method, request.url.path, body))
            if request.url.path == "/api/ps":
                if server.ps_status != 200:
                    return httpx.Response(server.ps_status)
                return httpx.Response(200, json={"models": [{"name": n, "model": n} for n in server.names]})
            return httpx.Response(200, json={"done": True})

        return _REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    @property
    def unloaded(self):
        return [json.loads(b)["model"] for m, p, b in self.requests if p == "/api/generate" and json.loads(b).get("keep_alive") == 0]


def _use(monkeypatch, fake):
    monkeypatch.setattr(ollama.httpx, "AsyncClient", fake.client)


def test_only_the_other_models_are_unloaded(monkeypatch):
    fake = _FakeOllama(["llama3:8b", "qwen3:8b"])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == ["llama3:8b"]
    assert fake.unloaded == ["llama3:8b"]


def test_latest_tag_is_the_same_model(monkeypatch):
    fake = _FakeOllama(["qwen3:latest"])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3")) == []
    assert fake.unloaded == []


def test_embedding_models_stay(monkeypatch):
    fake = _FakeOllama(["nomic-embed-text:latest", "llama3:8b"])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == ["llama3:8b"]


def test_nothing_loaded_sends_no_unload(monkeypatch):
    fake = _FakeOllama([])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == []
    assert [p for _, p, _ in fake.requests] == ["/api/ps"]


def test_other_servers_are_never_probed(monkeypatch):
    fake = _FakeOllama(["llama3:8b"])
    _use(monkeypatch, fake)
    for url in ("http://127.0.0.1:12434/engines/v1", "http://localhost:1234/v1", "https://api.openai.com/v1"):
        assert asyncio.run(ollama.unload_other_models(url, "x")) == []
    assert fake.requests == []


def test_opt_out_env_is_honoured(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_UNLOAD_OTHER_LOCAL_MODELS", "false")
    fake = _FakeOllama(["llama3:8b"])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == []
    assert fake.requests == []


def test_old_ollama_without_ps_is_left_alone(monkeypatch):
    fake = _FakeOllama(["llama3:8b"], ps_status=404)
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == []
    assert fake.unloaded == []


def test_an_unreachable_server_never_raises(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        ollama.httpx, "AsyncClient",
        lambda *a, **k: _REAL_CLIENT(transport=httpx.MockTransport(refuse)),
    )
    assert asyncio.run(ollama.unload_other_models(URL, "qwen3:8b")) == []
    assert asyncio.run(ollama.unload_all(URL)) == []
    assert asyncio.run(ollama.resident_models(URL)) == []


def test_unload_all_ignores_the_opt_out_but_keeps_embeddings(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_UNLOAD_OTHER_LOCAL_MODELS", "false")
    fake = _FakeOllama(["llama3:8b", "nomic-embed-text"])
    _use(monkeypatch, fake)
    assert asyncio.run(ollama.unload_all(URL)) == ["llama3:8b"]


def test_release_on_switch_frees_the_old_ollama_model(monkeypatch):
    fake = _FakeOllama(["llama3:8b", "qwen3:8b"])
    _use(monkeypatch, fake)
    assert asyncio.run(llm_core.release_local_models([URL], keep="qwen3:8b")) == {"unloaded": ["llama3:8b"]}


def test_release_skipped_while_a_reply_is_generating(monkeypatch):
    fake = _FakeOllama(["llama3:8b"])
    _use(monkeypatch, fake)

    async def run():
        lock = asyncio.Lock()
        monkeypatch.setattr(llm_core, "_LOCAL_MODEL_LOCK", lock)
        async with lock:
            return await llm_core.release_local_models([URL], keep="qwen3:8b")

    assert asyncio.run(run()) == {"unloaded": [], "skipped": "busy"}
    assert fake.requests == []
