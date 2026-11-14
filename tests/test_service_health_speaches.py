"""Tests for speaches_health — env-driven probe, status classification, sanitization."""
import types

from src import service_health as sh


def _resp(status_code):
    return types.SimpleNamespace(status_code=status_code)


def _raise(*_a, **_k):
    raise ConnectionRefusedError("refused")


BOTH = {"TTS_OPENAI_API_BASE": "http://127.0.0.1:8000/v1",
        "STT_OPENAI_API_BASE": "http://127.0.0.1:8000/v1"}


def test_speaches_disabled_without_env():
    s = sh.speaches_health({})
    assert s["status"] == sh.DISABLED


def test_speaches_ok_probes_health_once_for_shared_server():
    seen = []

    def getter(url, timeout):
        seen.append(url)
        return _resp(200)

    s = sh.speaches_health(BOTH, http_get=getter)
    assert s["status"] == sh.OK
    # Same server for TTS and STT → one non-intrusive /health request.
    assert seen == ["http://127.0.0.1:8000/health"]
    assert s["meta"]["reachable"] == ["stt", "tts"]


def test_speaches_down_when_unreachable():
    s = sh.speaches_health(BOTH, http_get=_raise)
    assert s["status"] == sh.DOWN
    assert s["meta"]["error"] == "connection_refused"


def test_speaches_down_on_server_error():
    s = sh.speaches_health(BOTH, http_get=lambda url, timeout: _resp(503))
    assert s["status"] == sh.DOWN
    assert s["meta"]["error"] == "http_error"


def test_speaches_degraded_when_only_one_server_answers():
    env = {"TTS_OPENAI_API_BASE": "http://127.0.0.1:8000/v1",
           "STT_OPENAI_API_BASE": "http://127.0.0.1:9000/v1"}

    def getter(url, timeout):
        if ":9000" in url:
            raise ConnectionRefusedError()
        return _resp(200)

    s = sh.speaches_health(env, http_get=getter)
    assert s["status"] == sh.DEGRADED
    assert s["meta"]["reachable"] == ["tts"]
    assert s["meta"]["failed"] == ["stt"]


def test_speaches_meta_strips_credentials():
    env = {"TTS_OPENAI_API_BASE": "http://user:hunter2@speaches:8000/v1?key=abc"}
    s = sh.speaches_health(env, http_get=lambda url, timeout: _resp(200))
    blob = repr(s)
    assert "hunter2" not in blob and "key=abc" not in blob
