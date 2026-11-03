"""One huge tool result must not cost the model its system prompt, memory or history.

An MCP server such as REA can return megabytes (3.7 MB for a 3000-file archive). Odysseus used to
pass that through unbounded; trim_for_context then dropped the memory/RAG messages, cut the system
prompt to 2000 characters and discarded older turns, including the assistant turn that owns the
tool result, so the result itself was removed as an orphan.
"""

import asyncio
from types import SimpleNamespace

from src.constants import MAX_MCP_OUTPUT_CHARS
from src.context_compactor import TOOL_RESULT_BUDGET_SHARE, trim_for_context
from src.mcp_manager import McpManager
from src.model_context import estimate_tokens

SYSTEM = "You are Odysseus. " + "Tool instructions and rules. " * 400
MEMORY = "Memory: the user prefers local models. " * 60
BUDGET = 27_852  # the auto budget of a 32k-token model window


def _conversation(tool_text: str) -> list:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "system", "content": MEMORY},
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer " * 40},
        {"role": "user", "content": "what is inside Assembly-CSharp.dll?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "mcp__rea__inspect_managed_artifact", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": tool_text},
    ]


def test_oversized_tool_result_is_shortened_and_everything_else_survives():
    tool_text = "HEAD-MARK " + "x" * 1_000_000 + " TAIL-MARK"
    messages = _conversation(tool_text)

    out = trim_for_context(messages, BUDGET, reserve_tokens=1024)

    assert [m["role"] for m in out] == [m["role"] for m in messages]
    assert out[0]["content"] == SYSTEM, "main system prompt must not be truncated"
    assert out[1]["content"] == MEMORY, "memory message must not be dropped"
    assert out[2:6] == messages[2:6], "history and the assistant turn owning the call must be kept"
    tool = out[6]
    assert tool["tool_call_id"] == "c1"
    assert tool["content"].startswith("HEAD-MARK") and tool["content"].endswith("TAIL-MARK")
    assert "Odysseus shortened this tool result" in tool["content"]
    assert estimate_tokens(out) <= BUDGET - 1024


def test_shortened_result_is_kept_at_about_its_share_of_the_budget():
    out = trim_for_context(_conversation("y" * 500_000), BUDGET, reserve_tokens=1024)

    tool = [m for m in out if m["role"] == "tool"]
    assert len(tool) == 1, "the result must survive, not be dropped as an orphan"
    share = int((BUDGET - 1024) * TOOL_RESULT_BUDGET_SHARE)
    assert share * 0.8 <= estimate_tokens(tool) <= share + 8


def test_messages_within_budget_are_returned_unchanged():
    messages = _conversation("a modest result " * 100)

    assert trim_for_context(messages, BUDGET, reserve_tokens=1024) is messages


def test_tool_result_under_its_share_is_not_touched_when_something_else_is_too_big():
    small_result = "r" * 4_000
    messages = _conversation(small_result)
    messages[2] = {"role": "user", "content": "pasted log " * 20_000}

    out = trim_for_context(messages, BUDGET, reserve_tokens=1024)

    tool = [m for m in out if m["role"] == "tool"]
    assert not tool or tool[0]["content"] == small_result


def test_only_tool_messages_are_shortened_by_the_new_stage():
    messages = _conversation("t" * 200_000)
    big_user_text = "u" * 40_000
    messages[4] = {"role": "user", "content": big_user_text}

    out = trim_for_context(messages, 400_000, reserve_tokens=1024)

    assert out[4]["content"] == big_user_text


class _Text:
    def __init__(self, text):
        self.text = text


def _call_mcp(text: str, is_error: bool = False) -> dict:
    async def call_tool(name, arguments):
        return SimpleNamespace(content=[_Text(text)], isError=is_error)

    session = SimpleNamespace(call_tool=call_tool)
    return asyncio.run(McpManager()._do_call(session, "inspect_artifact", {}))


def test_mcp_output_over_the_cap_is_truncated_with_a_notice():
    huge = "z" * (MAX_MCP_OUTPUT_CHARS * 3)

    result = _call_mcp(huge)

    assert result["exit_code"] == 0
    assert result["stdout"].startswith("z" * 100)
    assert len(result["stdout"]) < MAX_MCP_OUTPUT_CHARS + 300
    assert f"{len(huge):,} characters in total" in result["stdout"]


def test_mcp_output_at_or_under_the_cap_is_unchanged():
    exact = "k" * MAX_MCP_OUTPUT_CHARS

    assert _call_mcp(exact)["stdout"] == exact


def test_mcp_error_output_is_truncated_and_still_marked_untrusted():
    result = _call_mcp("e" * (MAX_MCP_OUTPUT_CHARS * 2), is_error=True)

    assert result["exit_code"] == 1 and result["untrusted_content"] is True
    assert len(result["stderr"]) < MAX_MCP_OUTPUT_CHARS + 300
