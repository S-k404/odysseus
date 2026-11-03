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


def test_the_same_loop_in_answer_text_is_stopped_but_not_retried():
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    hit = _feed(guard, "\n\n".join(LOOP * 30), thinking=False)

    assert hit and not guard.thinking_loop  # nothing to retry once an answer has started
    assert "started repeating itself" in json.loads(hit.split("data: ", 1)[1])["text"]


@pytest.mark.parametrize("text", [
    "\n".join(
        f"Now {w} the {n} part: it {v} the earlier {m}, so I keep it and move on to {k}."
        for i, (w, n, v, m, k) in enumerate(zip(
            ["check", "weigh", "compare", "recount", "test", "trace", "probe", "audit"] * 10,
            ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"] * 8,
            ["matches", "extends", "contradicts", "refines", "supports"] * 16,
            ["estimate", "bound", "claim", "figure", "premise", "result", "sketch", "model"] * 10,
            [f"case {j * 7 % 31}" for j in range(80)],
        ))
    ),
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


# ── varied loops, ceilings, and the other provider paths ─────────────────────

def test_loop_with_varying_details_is_caught_by_compression():
    guard = llm_core._DegenerateStreamGuard("qwen3.6")
    text = "".join(f"I'll mention `File{i}.dll`.\n\nI'll write the response.\n\nI'll be concise.\n\n" for i in range(80))
    hit = _feed(guard, text)

    assert hit and guard.thinking_loop and "compress" in json.loads(hit.split("data: ", 1)[1])["text"]


@pytest.mark.parametrize("text", [
    "\n".join(f"| row {i} | {i * 37 % 101} | {i * 91 % 211} | item-{i % 13} |" for i in range(120)),   # a table
    "\n".join(f"user{i},{i * 7919 % 10007},{(i * 31) % 97}" for i in range(200)),                       # csv
    json.dumps([{"id": i, "name": f"thing {i}", "score": i * 3 % 17} for i in range(80)], indent=2),     # json
])
def test_legitimately_repetitive_answers_are_not_flagged(text):
    assert _feed(llm_core._DegenerateStreamGuard("qwen3.6"), text, thinking=False) is None


def test_thinking_past_its_ceiling_is_cut_even_without_a_loop():
    guard = llm_core._DegenerateStreamGuard("qwen3.6", thinking_budget_tokens=200)
    words = [f"idea{i}" for i in range(400)]
    hit = None
    for i in range(0, len(words), 5):
        hit = guard.check(f"Consider {words[i]} and {words[i + 1]} then {words[i + 2]}. ", thinking=True)
        if hit:
            break

    assert hit and guard.thinking_loop and guard.reason_kind == "budget"
    assert "limit of about 200 tokens" in hit


def test_ceiling_comes_from_the_pill_budget_for_local_servers_only():
    assert llm_core._local_thinking_cap(URL, 2048) == 3072
    assert llm_core._local_thinking_cap(URL, 0) == llm_core._LOCAL_THINKING_HARD_CAP_TOKENS
    assert llm_core._local_thinking_cap("https://api.openai.com/v1", 2048) is None


def test_runaway_thinking_is_retried_without_thinking(monkeypatch):
    lines = [_sse(reasoning_content=f"Consider angle number {i} of the question and its consequences. ") for i in range(3000)]
    lines += ["data: [DONE]"]
    blob, client = _run(monkeypatch, [lines, _answer()], thinking_budget=100)

    assert "Thinking ran past its limit" in blob and "Here is the list." in blob
    assert len(client.payloads) == 2 and client.payloads[1]["reasoning_effort"] == "none"


def test_retry_nudges_models_that_have_no_thinking_switch(monkeypatch):
    _, client = _run(monkeypatch, [_looping_reasoning(), _answer()])
    assert client.payloads[1]["presence_penalty"] == 1.0
    assert "presence_penalty" not in client.payloads[0]


def test_gpt_oss_is_asked_for_low_effort_not_none(monkeypatch):
    _, client = _run(monkeypatch, [_answer()], model="gpt-oss:20b", reasoning_effort="none")
    assert client.payloads[0]["reasoning_effort"] == "low"


# Ollama's native API streams newline-delimited JSON, not SSE.
def _nd(thinking="", content="", done=False):
    return json.dumps({"model": "qwen3:8b", "message": {"role": "assistant", "thinking": thinking, "content": content}, "done": done})


def test_ollama_native_loop_is_cut_and_retried_with_think_off(monkeypatch):
    looping = [_nd(thinking=s + "\n\n") for s in LOOP * 40]
    blob, client = _run(monkeypatch, [looping, [_nd(content="Here is the list."), _nd(done=True)]],
                        model="qwen3:8b", url="http://127.0.0.1:11434")

    assert "Here is the list." in blob and "Answering without thinking" in blob
    assert blob.count("data: [DONE]") == 1 and "event: error" not in blob
    assert client.events == ["open 0", "close 0", "open 1", "close 1"]
    assert "think" not in client.payloads[0] or client.payloads[0]["think"] is not False
    assert client.payloads[1]["think"] is False


def test_anthropic_loop_is_stopped_with_an_error(monkeypatch):
    def evt(delta):
        return "data: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": delta})

    lines = [evt({"type": "text_delta", "text": s + "\n\n"}) for s in LOOP * 40]
    blob, client = _run(monkeypatch, [lines], model="claude-sonnet-4", url="https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": "k"})

    assert "event: error" in blob and "started repeating itself" in blob
    assert len(client.payloads) == 1
