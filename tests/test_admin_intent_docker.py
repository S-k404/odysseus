"""Regression: _detect_admin_intent matches keywords as substrings, and the admin keyword
"doc" is inside "docker". A first message such as "List my running docker containers and
their status." therefore switched on admin mode and offered the whole admin tool block
(manage_tokens, manage_settings, manage_mcp, manage_endpoints, create_session, ...) to a
model that only had to list containers.
"""

from src.agent_loop import _detect_admin_intent


def _admin(text):
    return _detect_admin_intent([{"role": "user", "content": text}])


def test_docker_and_look_alike_words_do_not_trigger_admin_mode():
    for p in (
        "List my running docker containers and their status.",
        "docker ps",
        "How do I write a Dockerfile for a flask app?",
        "Restart the docker-compose stack",
        "Is the doctor available on Friday?",
        "Summarise the doctrine of precedent",
    ):
        assert _admin(p) is False, f"admin mode must stay off for: {p!r}"


def test_real_admin_requests_still_trigger_admin_mode():
    for p in (
        "edit this doc",
        "list my docs",
        "open the document",
        "configure my settings",
        "add an MCP server",
        "list all sessions",
        "docker setup: change the settings",  # a real admin word next to docker still counts
    ):
        assert _admin(p) is True, f"admin mode must stay on for: {p!r}"
