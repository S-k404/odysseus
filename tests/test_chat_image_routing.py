import sys
for mod_name in ["src.endpoint_resolver", "src.database", "core.database"]:
    _mod = sys.modules.get(mod_name)
    if _mod is not None and not getattr(_mod, "__file__", None):
        sys.modules.pop(mod_name, None)

import json
from types import SimpleNamespace

from tests.helpers.import_state import clear_fake_endpoint_resolver_modules

clear_fake_endpoint_resolver_modules("routes.chat_routes")

from routes import chat_routes


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *conditions):
        return self

    def all(self):
        return list(self.rows)


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def query(self, model):
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


def _session(model="qwen3.5:latest", endpoint_url="http://localhost:11434/v1/chat/completions"):
    return SimpleNamespace(model=model, endpoint_url=endpoint_url)


def _endpoint(base_url, model_type="image", models=None, pinned=None, enabled=True):
    cached_models = None if models is None else json.dumps(models)
    return SimpleNamespace(
        base_url=base_url,
        model_type=model_type,
        is_enabled=enabled,
        cached_models=cached_models,
        pinned_models=None if pinned is None else json.dumps(pinned),
    )


def test_image_model_prefix_routes_to_image_generation_without_endpoint_lookup(monkeypatch):
    def fail_if_called():
        raise AssertionError("prefixed image models should not need a DB lookup")

    monkeypatch.setattr(chat_routes, "SessionLocal", fail_if_called)

    assert chat_routes._is_image_generation_session(_session(model="dall-e-3"))


def test_namespaced_gpt_image_model_routes_to_image_generation_without_endpoint_lookup(monkeypatch):
    def fail_if_called():
        raise AssertionError("provider-prefixed image models should not need a DB lookup")

    monkeypatch.setattr(chat_routes, "SessionLocal", fail_if_called)

    assert chat_routes._is_image_generation_session(_session(model="openai/gpt-5-image"))


def test_image_endpoint_does_not_catch_text_model_on_different_path(monkeypatch):
    db = _FakeDb([
        _endpoint("http://localhost:11434/v1/images", models=["sdxl-local"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert not chat_routes._is_image_generation_session(_session())
    assert db.closed


def test_image_endpoint_cache_must_contain_selected_model(monkeypatch):
    db = _FakeDb([
        _endpoint("http://localhost:11434/v1", models=["sdxl-local"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert not chat_routes._is_image_generation_session(_session(model="qwen3.5:latest"))


def test_matching_image_endpoint_routes_selected_image_model(monkeypatch):
    db = _FakeDb([
        _endpoint("http://localhost:11434/v1", models=["sdxl-local"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert chat_routes._is_image_generation_session(_session(model="sdxl-local"))


# One Docker Model Runner serves chat and image models from the same base URL, so it can
# be registered twice: a chat endpoint and an "image" endpoint. The image endpoint's model
# cache then lists the whole server, and "the cache contains the model" sent every chat to
# image generation (Qwen answered with `unsupported backend mode "image-generation"`).
DMR = "http://127.0.0.1:12434/v1"
DMR_MODELS = [
    "docker.io/ai/stable-diffusion:latest",
    "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S",
    "huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M",
]


def test_image_endpoint_sharing_a_server_with_a_chat_endpoint_does_not_catch_chat_models(monkeypatch):
    db = _FakeDb([
        _endpoint(DMR, "llm", models=DMR_MODELS),
        _endpoint(DMR, "image", models=DMR_MODELS, pinned=["docker.io/ai/stable-diffusion:latest"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)
    session = _session(model="huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S",
                       endpoint_url=DMR + "/chat/completions")

    assert not chat_routes._is_image_generation_session(session)


def test_shared_server_image_endpoint_without_pinned_models_catches_nothing_by_cache(monkeypatch):
    db = _FakeDb([
        _endpoint(DMR, "llm", models=DMR_MODELS),
        _endpoint(DMR, "image", models=DMR_MODELS),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert not chat_routes._is_image_generation_session(
        _session(model="huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M", endpoint_url=DMR + "/chat/completions"))


def test_shared_server_image_endpoint_still_claims_its_pinned_model(monkeypatch):
    db = _FakeDb([
        _endpoint(DMR, "llm", models=DMR_MODELS + ["my-custom-painter"]),
        _endpoint(DMR, "image", models=DMR_MODELS + ["my-custom-painter"], pinned=["my-custom-painter"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert chat_routes._is_image_generation_session(
        _session(model="my-custom-painter", endpoint_url=DMR + "/chat/completions"))


def test_disabled_chat_endpoint_does_not_make_an_image_endpoint_shared(monkeypatch):
    """Only an enabled chat endpoint on the same server shares it; the old cache rule still applies otherwise."""
    db = _FakeDb([
        _endpoint(DMR, "llm", models=DMR_MODELS, enabled=False),
        _endpoint(DMR, "image", models=["my-custom-painter"]),
    ])
    monkeypatch.setattr(chat_routes, "SessionLocal", lambda: db)

    assert chat_routes._is_image_generation_session(
        _session(model="my-custom-painter", endpoint_url=DMR + "/chat/completions"))
