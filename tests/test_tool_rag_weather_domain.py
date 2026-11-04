"""Weather questions must reach the weather MCP server's tools.

They used to match only the "web" domain, so the model got web_search and read back whatever units the
page used (°F, mph, 12-hour times). The classifier is deterministic string matching, so it is exercised
directly, like the reverse-engineering domain.
"""

from src.agent_loop import (
    _classify_agent_request,
    _DOMAIN_RULES,
    _DOMAIN_TOOL_MAP,
    _TERMINUS_PRESERVED_TOOLS,
    _domain_rules_for_tools,
)

TOOLS = {"mcp__weather__get_weather", "mcp__weather__get_hourly_forecast"}


def _classify(text):
    return _classify_agent_request([{"role": "user", "content": text}], text)


def test_weather_questions_get_the_weather_domain_and_are_not_low_signal():
    prompts = [
        "What's the weather in Pune tomorrow?",
        "weather in Paris",
        "Will it rain this evening in Mumbai?",
        "Is it going to snow tomorrow?",
        "how hot is it in Dubai",
        "Give me the forecast for Berlin this weekend",
        "Do I need an umbrella today?",
        "temperature outside right now?",
        "how windy is it today",
        "Weather for 12.97,77.59",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "weather" in intent["domains"], f"expected weather for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_a_plain_weather_word_keeps_web_search_as_the_fallback():
    assert {"weather", "web"} <= set(_classify("What's the weather in Pune tomorrow?")["domains"])


def test_unrelated_requests_do_not_get_the_domain():
    prompts = [
        "hi",
        "Write a python script that sorts a list",
        "Set the sampling temperature to 0.2",
        "What is the CPU temperature limit of an RP2040?",
        "Design a wind turbine blade in Blender",
        "Draft an email to my landlord",
        "Remind me to buy milk",
        "Search the web for the best pizza dough recipe",
    ]
    for p in prompts:
        assert "weather" not in _classify(p)["domains"], f"false positive: {p!r}"


def test_domain_seeds_both_weather_tools_under_server_id_weather():
    assert _DOMAIN_TOOL_MAP["weather"] == TOOLS


def test_the_rule_pack_says_metric_and_prefers_the_tools_to_web_search():
    assert "weather" in _DOMAIN_RULES
    rules = _domain_rules_for_tools({"mcp__weather__get_weather"})
    assert _DOMAIN_RULES["weather"] in rules
    rule = _DOMAIN_RULES["weather"]
    assert "get_weather" in rule and "get_hourly_forecast" in rule
    assert "Prefer them to a web search" in rule
    assert "Never convert to °F, mph or inches" in rule


def test_workspace_terminus_toolset_keeps_the_weather_tools():
    assert _DOMAIN_TOOL_MAP["weather"] <= _TERMINUS_PRESERVED_TOOLS


def test_the_server_is_registered_as_a_builtin_under_the_id_the_tool_names_use():
    from src.builtin_mcp import _BUILTIN_SERVERS

    script, name = _BUILTIN_SERVERS["weather"]
    assert script == "mcp_servers/weather_server.py" and "Weather" in name
    assert all(t.startswith("mcp__weather__") for t in TOOLS)
