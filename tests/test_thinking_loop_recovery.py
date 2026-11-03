"""A model that loops in its reasoning is cut off and retried without thinking.

Seen on a local qwen3.6: after a tool call it spent 6,500 tokens cycling through
"I'll write the response. I'll use the list. I'll be concise. ..." and never
answered. Each sentence differs, so the single-token and 4-gram checks missed it.
"""
import asyncio
import json

import pytest

from src import llm_core

LOOP = [
    "I'll write the response.", "I'll use the list.", "I'll group them.",
    "I'll mention `Steam.dll`.", "I'll mention `Dungeon with Girl`.", "I'll ask.",
    "I'll write the response.", "I'll be concise.",
]
URL = "http://127.0.0.1:12434/engines/v1"


# ── the guard ────────────────────────────────────────────────────────────────

def _feed(guard, text, chunk=7, thinking=True):
    for i in range(0, len(text), chunk):
        hit = guard.check(text[i:i + chunk], thinking=thinking)
        if hit:
            return hit
    return None


def test_cycle_of_different_sentences_is_a_thinking_loop():
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    hit = _feed(guard, "\n\n".join(LOOP * 30))

    assert hit and guard.thinking_loop
    message = json.loads(hit.split("data: ", 1)[1])["text"]
    assert "stuck repeating itself while thinking" in message and "turn thinking off" in message


def test_same_text_is_left_alone_unless_it_is_reasoning():
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    assert _feed(guard, "\n\n".join(LOOP * 30), thinking=False) is None
    assert not guard.thinking_loop


@pytest.mark.parametrize("text", [
    "\n".join(f"Step {i}: check whether item {i} matches the expected result." for i in range(80)),
    "\n".join(f"- **File {i}**: description of file number {i}" for i in range(60)),
    "\n".join(["}"] * 40 + ["Wait."] * 40),                       # one-word lines carry no signal
    "\n".join("Let me double check that." if i % 5 == 0 else f"Option {i} changes section {i}." for i in range(60)),
    "\n".join(["我先分析一下问题。", "然后写答案。"] * 60),             # no latin words to compare
])
def test_ordinary_reasoning_is_not_flagged(text):
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    assert _feed(guard, text) is None


def test_newline_only_chunks_still_separate_sentences():
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    pieces = []
    for sentence in LOOP * 30:
        pieces += [sentence, "\n\n"]  # the blank line arrives as its own delta
    assert any(guard.check(p, thinking=True) for p in pieces)


# ── the stream ───────────────────────────────────────────────────────────────

def _sse(**delta):
    return "data: " + json.dumps({"choices": [{"index": 0, "delta": delta}]})


def _looping_reasoning():
    return [_sse(reasoning_content=s + "\n\n") for s in LOOP * 40] + ["data: [DONE]"]


def _answer(text="Here is the list."):
    return [_sse(content=text), "data: [DONE]"]


class _Resp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _Client:
    """Serves one scripted response per request and records open/close order."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.payloads = []
        self.events = []

    def stream(self, method, url, **kw):
        n = len(self.payloads)
        self.payloads.append(kw["json"])
        client, lines = self, self.scripts[n]

        class _Ctx:
            async def __aenter__(self):
                client.events.append(f"open {n}")
                return _Resp(lines)

            async def __aexit__(self, *exc):
                client.events.append(f"close {n}")
                return False

        return _Ctx()


def _run(monkeypatch, scripts, model="qwen3.6-35b-a3b-gguf:UD", url=URL, **kwargs):
    client = _Client(scripts)
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: client)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda u: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *a, **k: None)

    async def go():
        return [c async for c in llm_core._stream_llm_inner(
            url, model, [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "list them"}],
            **kwargs,
        )]

    return "".join(asyncio.run(go())), client


def test_looping_reasoning_is_cut_and_answered_without_thinking(monkeypatch):
    blob, client = _run(monkeypatch, [_looping_reasoning(), _answer()], reasoning_effort="high")

    assert "Answering without thinking" in blob and "Here is the list." in blob
    assert blob.count("data: [DONE]") == 1
    assert "event: error" not in blob
    # the looping connection is closed before the retry opens (one model, one slot)
    assert client.events == ["open 0", "close 0", "open 1", "close 1"]
    first, retry = client.payloads
    assert first["reasoning_effort"] == "high"
    assert retry["reasoning_effort"] == "none"
    assert retry["chat_template_kwargs"] == {"enable_thinking": False}
    assert retry["messages"][0]["content"].startswith("You are helpful.")
    assert "repeated itself" in retry["messages"][0]["content"]
    assert retry["messages"][-1] == {"role": "user", "content": "list them"}


def test_a_second_loop_is_an_error_not_another_retry(monkeypatch):
    blob, client = _run(monkeypatch, [_looping_reasoning(), _looping_reasoning()])

    assert blob.count("event: error") == 1 and "stuck repeating itself" in blob
    assert len(client.payloads) == 2
    assert client.events == ["open 0", "close 0", "open 1", "close 1"]


def test_no_retry_once_an_answer_has_started(monkeypatch):
    lines = [_sse(content="Sure, here"), *[_sse(reasoning_content=s + "\n\n") for s in LOOP * 40]]
    blob, client = _run(monkeypatch, [lines])

    assert "event: error" in blob and len(client.payloads) == 1


def test_ordinary_stream_makes_one_request(monkeypatch):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet"]
    lines = [_sse(reasoning_content=f"{words[i % 10]} needs {words[(i * 3) % 10]} before {words[(i * 7) % 10]} step {i}.\n\n")
             for i in range(60)] + _answer()
    blob, client = _run(monkeypatch, [lines])

    assert "Here is the list." in blob and "Answering without thinking" not in blob
    assert len(client.payloads) == 1 and "chat_template_kwargs" not in client.payloads[0]


# ── "thinking off" reaches llama.cpp-style servers ───────────────────────────

def test_thinking_off_sets_the_template_flag_for_local_qwen3(monkeypatch):
    _, client = _run(monkeypatch, [_answer()], reasoning_effort="none")
    assert client.payloads[0]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize(("url", "model"), [
    ("https://api.openai.com/v1", "gpt-4o"),              # cloud: strict about unknown fields
    ("https://api.example-cloud.com/v1", "qwen3-8b"),     # thinking model, but not self-hosted
    (URL, "qwen2.5-coder-1.5b-instruct"),                 # local, not a thinking model
])
def test_thinking_off_flag_is_not_sent_elsewhere(monkeypatch, url, model):
    _, client = _run(monkeypatch, [_answer()], url=url, model=model, reasoning_effort="none")
    assert "chat_template_kwargs" not in client.payloads[0]
