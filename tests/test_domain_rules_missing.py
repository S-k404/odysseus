"""An agent turn must survive a tool group that has no prompt rules yet.

The uncensor tools were added to the tool map before their rules entry existed, and every agent turn that
selected them died with `KeyError: 'decensor'` before the model was ever called.
"""

from src import agent_loop as al


def test_a_tool_group_without_rules_is_skipped_not_fatal(monkeypatch):
    uncensor_tool = "mcp__uncensor__decensor_image"
    monkeypatch.setitem(al._DOMAIN_TOOL_MAP, "decensor", {uncensor_tool})
    monkeypatch.delitem(al._DOMAIN_RULES, "decensor", raising=False)

    assert al._domain_rules_for_tools({uncensor_tool}) == []


def test_rules_for_other_groups_are_still_added_alongside(monkeypatch):
    monkeypatch.setitem(al._DOMAIN_TOOL_MAP, "decensor", {"mcp__uncensor__decensor_image"})
    monkeypatch.delitem(al._DOMAIN_RULES, "decensor", raising=False)
    github_tool = next(iter(al._DOMAIN_TOOL_MAP["github"]))

    rules = al._domain_rules_for_tools({"mcp__uncensor__decensor_image", github_tool})

    assert rules == [al._DOMAIN_RULES["github"]]


def test_a_group_that_has_rules_still_gets_them(monkeypatch):
    tool = next(iter(al._DOMAIN_TOOL_MAP["weather"]))
    assert al._DOMAIN_RULES["weather"] in al._domain_rules_for_tools({tool})
