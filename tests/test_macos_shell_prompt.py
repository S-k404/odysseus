"""The native Mac app tells the model its shell is macOS; the Docker copy (Linux) does not."""
import sys

import pytest

from src import agent_loop


@pytest.mark.parametrize("compact", [False, True])
def test_mac_prompt_names_macos_commands(monkeypatch, compact):
    monkeypatch.setattr(sys, "platform", "darwin")
    prompt = agent_loop._assemble_prompt({"bash"}, compact=compact)

    assert "## Shell environment" in prompt and "macOS" in prompt
    assert "sed -i ''" in prompt and "There is no `timeout`" in prompt


@pytest.mark.parametrize("compact", [False, True])
def test_linux_prompt_has_no_mac_rules(monkeypatch, compact):
    monkeypatch.setattr(sys, "platform", "linux")
    assert "## Shell environment" not in agent_loop._assemble_prompt({"bash"}, compact=compact)


def test_no_shell_tool_means_no_shell_rules(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "## Shell environment" not in agent_loop._assemble_prompt({"manage_notes"})


def test_rules_are_static_so_the_prompt_stays_a_stable_cache_prefix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert agent_loop._assemble_prompt({"bash"}) == agent_loop._assemble_prompt({"bash"})
