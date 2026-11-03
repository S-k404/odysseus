"""Docker Model Runner helpers: vLLM-Metal guard, unload, release on switch."""

import asyncio

import pytest

from src import docker_model_runner as dmr
from src import llm_core

URL = "http://127.0.0.1:12434/v1"

MODELS = [
    {"id": "sha256:a", "tags": ["ai/qwen3:8B"], "config": {"format": "gguf", "context_size": 32768}},
    {"id": "sha256:b", "tags": ["mlx-community/coder-7b:latest"], "config": {"format": "safetensors"}},
    {"id": "sha256:c", "config": {"format": "gguf"}},  # untagged variant
]
METAL = {"llama.cpp": "Running: llama.cpp metal", "vllm": "Running: vllm-metal v0.2", "mlx": "Not Installed"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    dmr._CACHE.clear()
    dmr._NOT_DMR_UNTIL.clear()
    monkeypatch.delenv("ODYSSEUS_ALLOW_VLLM_METAL", raising=False)
    monkeypatch.delenv("ODYSSEUS_UNLOAD_OTHER_LOCAL_MODELS", raising=False)


def _serve(monkeypatch, status=METAL, models=MODELS):
    calls = []

    def fake_get(root, path, timeout):
        calls.append(path)
        return {"/models": models, "/engines/status": status}.get(path)

    monkeypatch.setattr(dmr, "_cached_get", fake_get)
    return calls


def test_vllm_metal_model_is_blocked(monkeypatch):
    _serve(monkeypatch)
    reason = dmr.load_block_reason(URL, "mlx-community/coder-7b:latest")
    assert reason and "vLLM-Metal" in reason and "ODYSSEUS_ALLOW_VLLM_METAL" in reason


def test_gguf_model_is_allowed(monkeypatch):
    calls = _serve(monkeypatch)
    assert dmr.load_block_reason(URL, "ai/qwen3:8B") is None
    assert "/engines/status" not in calls


def test_safetensors_allowed_when_not_vllm_metal(monkeypatch):
    _serve(monkeypatch, status={"vllm": "Running: vllm v0.9 (cuda)", "mlx": "Not Installed"})
    assert dmr.load_block_reason(URL, "mlx-community/coder-7b:latest") is None
    _serve(monkeypatch, status={"vllm": "Running: vllm-metal", "mlx": "Running: mlx-lm"})
    assert dmr.load_block_reason(URL, "mlx-community/coder-7b:latest") is None


def test_override_allows_vllm_metal(monkeypatch):
    _serve(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_ALLOW_VLLM_METAL", "1")
    assert dmr.load_block_reason(URL, "mlx-community/coder-7b:latest") is None


def test_non_runner_endpoints_are_never_probed(monkeypatch):
    calls = _serve(monkeypatch)
    assert dmr.load_block_reason("http://127.0.0.1:8080/v1", "anything") is None
    assert dmr.load_block_reason("https://api.openai.com/v1", "gpt-x") is None
    assert calls == []


def test_context_size_uses_tagged_entry(monkeypatch):
    _serve(monkeypatch)
    monkeypatch.setattr(dmr.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("no configure")))
    assert dmr.runner_context_size(URL, "ai/qwen3:8B") == 32768


def _weights(size, context):
    return {"format": "gguf", "architecture": "qwen3", "parameters": "8.19B",
            "quantization": "MOSTLY_Q4_K_M", "size": size, "context_size": context}


TWINS = [
    # `docker model package` left the 8k original behind next to the 32k repackage.
    {"id": "sha256:orig", "config": _weights("4.68GiB", 8192)},
    {"id": "sha256:pkg", "tags": ["ai/qwen3:8B"], "config": _weights("4.68GiB", 32768)},
    {"id": "sha256:solo", "config": _weights("9.99GiB", 8192)},  # no tagged twin
    {"id": "sha256:bare", "config": {"format": "gguf"}},  # too little metadata to match
]
PICKER = ["ai/qwen3:8B", "sha256:orig", "sha256:solo", "sha256:bare"]


def test_untagged_copy_of_a_tagged_model_is_hidden(monkeypatch):
    _serve(monkeypatch, models=TWINS)
    assert dmr.hide_untagged_duplicates(URL, PICKER) == ["ai/qwen3:8B", "sha256:solo", "sha256:bare"]


def test_untagged_copy_is_kept_when_its_tagged_twin_is_not_listed(monkeypatch):
    _serve(monkeypatch, models=TWINS)
    assert dmr.hide_untagged_duplicates(URL, ["sha256:orig", "sha256:solo"]) == ["sha256:orig", "sha256:solo"]


def test_pinned_untagged_copy_is_kept(monkeypatch):
    _serve(monkeypatch, models=TWINS)
    assert "sha256:orig" in dmr.hide_untagged_duplicates(URL, PICKER, keep=["sha256:orig"])


def test_duplicates_are_left_alone_off_the_runner_or_when_it_is_down(monkeypatch):
    calls = _serve(monkeypatch, models=TWINS)
    assert dmr.hide_untagged_duplicates("http://127.0.0.1:8080/v1", PICKER) == PICKER
    assert calls == []
    _serve(monkeypatch, models=None)
    assert dmr.hide_untagged_duplicates(URL, PICKER) == PICKER


class _Resp:
    def __init__(self, data=None, status=200):
        self._data, self.status_code = data, status
        self.is_success = 200 <= status < 300
        self.text = ""

    def json(self):
        return self._data


class _FakeRunner:
    """Records /engines/unload calls; /engines/ps reports ``loaded``."""

    def __init__(self, loaded):
        self.loaded = loaded
        self.unloaded = []

    def client(self, *a, **k):
        runner = self

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                return _Resp(runner.loaded)

            async def post(self, url, json=None, timeout=None):
                runner.unloaded.append(json["models"])
                return _Resp({})

        return _Client()


def test_unload_keeps_target_and_embeddings(monkeypatch):
    runner = _FakeRunner([
        {"model_name": "big-a", "mode": "completion"},
        {"model_name": "keep-me", "mode": "completion"},
        {"model_name": "embed", "mode": "embedding"},
    ])
    monkeypatch.setattr(dmr.httpx, "AsyncClient", runner.client)
    assert asyncio.run(dmr.unload_other_models(URL, "keep-me")) == ["big-a"]
    assert runner.unloaded == [["big-a"]]


def test_release_unloads_everything_but_the_new_model(monkeypatch):
    runner = _FakeRunner([{"model_name": "old", "mode": "completion"}, {"model_name": "new", "mode": "completion"}])
    monkeypatch.setattr(dmr.httpx, "AsyncClient", runner.client)
    result = asyncio.run(llm_core.release_local_models([URL], keep="new"))
    assert result == {"unloaded": ["old"]}


def test_release_is_skipped_while_a_local_reply_is_generating(monkeypatch):
    runner = _FakeRunner([{"model_name": "old", "mode": "completion"}])
    monkeypatch.setattr(dmr.httpx, "AsyncClient", runner.client)

    async def run():
        lock = asyncio.Lock()
        monkeypatch.setattr(llm_core, "_LOCAL_MODEL_LOCK", lock)
        async with lock:
            return await llm_core.release_local_models([URL], keep="new")

    assert asyncio.run(run()) == {"unloaded": [], "skipped": "busy"}
    assert runner.unloaded == []


def test_stream_reports_blocked_model_as_error(monkeypatch):
    monkeypatch.setattr(llm_core, "load_block_reason", lambda url, model: "blocked: too big")

    async def run():
        return [c async for c in llm_core.stream_llm(URL, "coder", [{"role": "user", "content": "hi"}])]

    chunks = asyncio.run(run())
    assert len(chunks) == 1 and chunks[0].startswith("event: error") and "blocked: too big" in chunks[0]
