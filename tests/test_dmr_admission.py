"""src/dmr_admission.py: one big model at a time, only if it fits, never cutting off a reply.

Everything is stubbed: no model runner is contacted and nothing is loaded or unloaded.
"""

import pytest

from src import dmr_admission as adm

URL = "http://127.0.0.1:12434"
# qwen3-8b: 4.68 GiB file, 36 layers, 8 KV heads, 128-wide heads -> ~10.7 GB loaded at 32k.
GGUF_8B = {"qwen3.block_count": "36", "qwen3.attention.head_count_kv": "8", "qwen3.attention.key_length": "128"}


def _entry(tag, size, gguf=None, context=None):
    config = {"format": "gguf", "size": size}
    if gguf:
        config["gguf"] = gguf
    if context:
        config["context_size"] = context  # what the runner serves it with, as DMR's /models reports it
    return {"id": f"sha256:{tag}", "tags": [tag], "config": config}


MODELS = [_entry("big:35b", "14.29GiB"), _entry("small:8b", "4.68GiB", GGUF_8B, context=32768), _entry("embed:small", "0.2GiB")]


def _ctx(model):
    return 32768 if model == "small:8b" else None


def _snap(available, pressure=1, total=48.0):
    return {"total_gb": total, "used_gb": total - available, "available_gb": available, "pressure": pressure}


def _ps(*names, busy=(), embedding=()):
    rows = [{"model_name": n, "mode": "completion", "in_use": n in busy} for n in names]
    return rows + [{"model_name": n, "mode": "embedding"} for n in embedding]


def _decide(model, ps, available, **kw):
    return adm.decide(model, ps, MODELS, _snap(available, **kw), _ctx, reserve=4.8)


# ── the decision ─────────────────────────────────────────────────────────────

def test_a_model_that_is_already_loaded_goes_straight_through():
    assert _decide("big:35b", _ps("big:35b"), available=1.0).action == "go"


def test_names_match_whatever_the_case_prefix_or_latest_tag():
    assert adm._norm("Docker.io/AI/SmolLM2:latest") == "ai/smollm2"
    assert _decide("BIG:35B", _ps("big:35b"), available=1.0).action == "go"


def test_a_model_that_fits_with_nothing_else_loaded_goes_through():
    assert _decide("big:35b", _ps(), available=30.0).action == "go"


def test_a_model_that_does_not_fit_is_refused_with_the_shortfall():
    d = _decide("big:35b", _ps(), available=11.5)  # needs ~17.4, 11.5 - 4.8 reserve = 6.7 spare
    assert d.action == "refuse"
    assert "needs about 17 GB" in d.message and "11 GB short" in d.message


def test_idle_models_are_unloaded_when_that_makes_room():
    d = _decide("big:35b", _ps("small:8b"), available=12.0)  # 12 + 10.7 evicted - 4.8 = 17.9 >= 17.4
    assert (d.action, d.unload) == ("make_room", ["small:8b"])


def test_evicting_does_not_help_when_even_that_is_not_enough():
    assert _decide("big:35b", _ps("small:8b"), available=8.0).action == "refuse"


def test_a_model_that_is_mid_reply_is_waited_for_not_unloaded():
    d = _decide("big:35b", _ps("small:8b", busy=("small:8b",)), available=12.0)
    assert d.action == "wait" and "still generating" in d.message


def test_it_is_refused_rather_than_made_to_wait_when_it_would_not_fit_afterwards_either():
    assert _decide("big:35b", _ps("small:8b", busy=("small:8b",)), available=5.0).action == "refuse"


def test_embedding_runners_are_left_alone():
    d = _decide("big:35b", _ps(embedding=("embed:small",)), available=30.0)
    assert (d.action, d.unload) == ("go", [])


def test_what_it_cannot_judge_is_let_through():
    assert _decide("no-such-model", _ps(), available=1.0).action == "go"
    assert adm.decide("big:35b", [], MODELS, None, _ctx, reserve=4.8).action == "go"


def test_critical_memory_pressure_refuses_everything_that_is_not_loaded():
    d = _decide("big:35b", _ps(), available=40.0, pressure=4)
    assert d.action == "refuse" and "pressure is critical" in d.message


def test_the_reserve_follows_the_same_setting_as_odysseus(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_RAM_RESERVE_GB", "0")
    assert adm.decide("big:35b", _ps(), MODELS, _snap(18.0), _ctx).action == "go"
    monkeypatch.delenv("ODYSSEUS_RAM_RESERVE_GB")
    assert adm.decide("big:35b", _ps(), MODELS, _snap(18.0), _ctx).action == "refuse"


# ── the gate: talking to the runner ──────────────────────────────────────────

class Runner:
    """A fake model runner and Mac: unloading the listed models hands their memory back."""

    def __init__(self, ps, available, handed_back=0.0):
        self.ps, self.available, self.handed_back = ps, available, handed_back
        self.posted, self.slept = [], 0

    def get(self, url, timeout=3.0):
        if url.endswith("/engines/ps"):
            return self.ps
        if url.endswith("/engines/_configure"):
            return []
        return MODELS

    def post(self, url, body, timeout=60.0):
        assert url.endswith("/engines/unload")
        self.posted.append(body)
        self.ps = [e for e in self.ps if e["model_name"] not in body["models"]]
        self.available += self.handed_back

    def snapshot(self):
        return _snap(self.available)

    def sleep(self, seconds):
        self.slept += 1

    def gate(self, model="big:35b", **kw):
        return adm.gate(model, URL, get=self.get, post=self.post, snapshot=self.snapshot, sleep=self.sleep,
                        clock=kw.pop("clock", None) or (lambda: 0.0), **kw)


@pytest.fixture(autouse=True)
def _default_reserve(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_RAM_RESERVE_GB", raising=False)


def test_the_gate_unloads_the_idle_model_waits_for_its_memory_and_lets_the_request_through():
    runner = Runner(_ps("small:8b"), available=12.0, handed_back=10.7)
    assert runner.gate() is None
    assert runner.posted == [{"models": ["small:8b"]}]
    assert runner.slept >= 1  # it waited for the memory to come back


def test_the_gate_answers_with_the_reason_when_a_model_cannot_fit():
    message = Runner(_ps(), available=11.5).gate()
    assert message and "needs about 17 GB" in message


def test_a_busy_model_that_finishes_lets_the_request_through():
    runner = Runner(_ps("small:8b", busy=("small:8b",)), available=12.0, handed_back=10.7)
    original = runner.sleep

    def finish_reply(seconds):
        original(seconds)
        runner.ps[0]["in_use"] = False

    runner.sleep = finish_reply
    assert runner.gate(clock=_ticking_clock()) is None
    assert runner.posted == [{"models": ["small:8b"]}]


def test_a_model_that_is_still_busy_when_the_wait_is_over_is_refused_not_cut_off():
    runner = Runner(_ps("small:8b", busy=("small:8b",)), available=12.0)
    message = runner.gate(wait_s=3.0, clock=_ticking_clock())
    assert message and "still generating" in message
    assert runner.posted == []  # nothing was unloaded under it


def test_a_runner_that_will_not_let_go_does_not_hold_the_request_forever():
    class Stubborn(Runner):
        def post(self, url, body, timeout=60.0):
            self.posted.append(body)

    runner = Stubborn(_ps("small:8b"), available=12.0)
    assert runner.gate() is None
    assert len(runner.posted) == 2


def test_the_gate_fails_open():
    def boom(url, timeout=3.0):
        raise OSError("connection refused")

    assert adm.gate("big:35b", URL, get=boom, snapshot=lambda: _snap(1.0)) is None
    assert adm.gate("big:35b", URL, get=lambda url, timeout=3.0: {"not": "a list"}, snapshot=lambda: _snap(1.0)) is None


def _ticking_clock():
    t = {"now": 0.0}

    def clock():
        t["now"] += 1.0
        return t["now"]

    return clock
