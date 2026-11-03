"""Docker service names rewritten for native runs: src/native_hosts.py."""

from src import native_hosts as nh


def test_speaches_url_points_at_published_port():
    assert nh.host_url("http://speaches:8000/v1", {}) == "http://127.0.0.1:8000/v1"
    assert nh.host_url("http://speaches:8000/v1", {"SPEACHES_PORT": "8010"}) == "http://127.0.0.1:8010/v1"


def test_other_services_use_their_compose_ports():
    assert nh.host_url("http://searxng:8080", {}) == "http://127.0.0.1:8080"
    assert nh.host_url("http://chromadb:8000/api", {}) == "http://127.0.0.1:8100/api"
    assert nh.host_url("http://ntfy/topic", {}) == "http://127.0.0.1:8091/topic"


def test_unrelated_values_are_left_alone():
    for value in ("http://localhost:8080", "https://api.example.com/v1", "speaches", "", "http://speaches:9999"):
        assert nh.host_url(value, {}) is None


def test_apply_rewrites_env_natively(monkeypatch):
    monkeypatch.setattr(nh, "in_container", lambda: False)
    env = {
        "TTS_OPENAI_API_BASE": "http://speaches:8000/v1",
        "STT_OPENAI_API_BASE": "http://speaches:8000/v1",
        "SEARXNG_INSTANCE": "http://localhost:8080",
        "CHROMADB_HOST": "chromadb",
        "CHROMADB_PORT": "8000",
    }
    changed = nh.apply(env)
    assert env["TTS_OPENAI_API_BASE"] == "http://127.0.0.1:8000/v1"
    assert env["STT_OPENAI_API_BASE"] == "http://127.0.0.1:8000/v1"
    assert env["SEARXNG_INSTANCE"] == "http://localhost:8080"
    assert (env["CHROMADB_HOST"], env["CHROMADB_PORT"]) == ("127.0.0.1", "8100")
    assert "SEARXNG_INSTANCE" not in changed


def test_apply_does_nothing_inside_docker(monkeypatch):
    monkeypatch.setattr(nh, "in_container", lambda: True)
    env = {"TTS_OPENAI_API_BASE": "http://speaches:8000/v1"}
    assert nh.apply(env) == {}
    assert env["TTS_OPENAI_API_BASE"] == "http://speaches:8000/v1"
