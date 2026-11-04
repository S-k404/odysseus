"""Regression: a first message such as "What time is it in Tokyo right now?" or
"List my running docker containers and their status." matched no keyword domain,
so it was flagged low_signal and took the direct low-signal reply path: the model
got no tools at all, not even a connected Time or Docker MCP server's, and
answered the time from memory. The same wording sent as a later turn reached tool
retrieval and used the tools.

The `clock` and `containers` domains only change the classification (so the turn
is no longer low-signal). They seed no tools: a user-added MCP server has a random
id, so there is no fixed tool name to put in _DOMAIN_TOOL_MAP.

The classifier is deterministic string matching (no embeddings / no DB), so it can
be exercised directly.
"""

from src.agent_loop import _DOMAIN_TOOL_MAP, _classify_agent_request


def _classify(text):
    return _classify_agent_request([{"role": "user", "content": text}], text)


def test_clock_questions_get_the_domain_and_are_not_low_signal():
    prompts = [
        "What time is it in Tokyo right now?",
        "what time is it",
        "What's the time in London?",
        "what is the local time for Mumbai",
        "Which time zone is Denver in?",
        "timezone for New York",
        "Time in Sydney",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "clock" in intent["domains"], f"expected clock for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_container_questions_get_the_domain_and_are_not_low_signal():
    prompts = [
        "List my running docker containers and their status.",
        "docker ps",
        "Which containers are running?",
        "Show my stopped containers",
        "Is the n8n container healthy?",
        "container status for homebox",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "containers" in intent["domains"], f"expected containers for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_unrelated_requests_do_not_get_the_new_domains():
    prompts = [
        "hi",
        "What is the time complexity of quicksort?",
        "Give me the time series of this column",
        "Finish it in time for the demo",
        "I lost track of time yesterday",
        "What is a shipping container?",
        "Write a CSS container class",
        "The garden containers need watering",
        "Explain how the sun sets",
    ]
    for p in prompts:
        domains = _classify(p)["domains"]
        assert "clock" not in domains, f"clock false positive: {p!r}"
        assert "containers" not in domains, f"containers false positive: {p!r}"


def test_greetings_stay_low_signal():
    for p in ("hi", "hello there", "thanks", "hey man"):
        assert _classify(p)["low_signal"] is True, f"greeting must stay low_signal: {p!r}"


def test_new_domains_seed_no_tools():
    # Nothing fixed to seed: Time/Docker MCP server ids are random per install.
    assert "clock" not in _DOMAIN_TOOL_MAP
    assert "containers" not in _DOMAIN_TOOL_MAP
