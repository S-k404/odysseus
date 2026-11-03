"""Regression: the agent tool-RAG domain classifier had no reverse-engineering
domain, so a first message such as "Which DLLs does Game.exe import?" matched no
domain, was flagged low_signal and took the direct low-signal reply path: the
model got no tools at all, not even the REA MCP server's. When a domain did
match (e.g. because the text said "file"), embedding retrieval picked the top 8
tools across every server and often left out `open_binary`, which
`inspect_artifact` and `extract_artifact` need first.

The classifier is deterministic string matching (no embeddings / no DB), so it
can be exercised directly. The tool names are the REA tools kept enabled by
rea/allowed-tools.txt, under the MCP server id `rea`.
"""

from src.agent_loop import (
    _classify_agent_request,
    _DOMAIN_RULES,
    _DOMAIN_TOOL_MAP,
    _TERMINUS_PRESERVED_TOOLS,
    _domain_rules_for_tools,
)

REA_TOOLS = {
    "open_binary", "inspect_artifact", "extract_artifact", "inspect_managed_artifact",
    "inspect_managed_native_boundaries", "inspect_pe_resources", "inspect_pe_imports",
    "inspect_native_exports", "inspect_il2cpp_metadata", "analyze_javascript_application",
}


def _classify(text):
    return _classify_agent_request([{"role": "user", "content": text}], text)


def test_reverse_engineering_requests_get_the_domain():
    """One natural request per REA tool, with no 'file'/'folder' keyword."""
    prompts = [
        "Open /games/Dungeon with Girl/Game.exe in the reverse-engineering tools.",
        "What is inside /games/Mousetrap_0.1.6p2/data.zip? Use the REA tools.",
        "List the .NET namespaces and types in Assembly-CSharp.dll.",
        "Which P/Invoke native calls does this .NET assembly make?",
        "Show the version info, icons and resources of Game.exe.",
        "Which functions does UnityPlayer.dll export?",
        "Which DLLs and API functions does Game.exe import?",
        "Read the IL2CPP global-metadata.dat of this Unity game.",
        "This is an RPG Maker MV game built on NW.js. What does its code do?",
        "Decompile this and tell me how the save system works.",
        "What do the PE imports of this look like?",
        "What files are inside the archive /games/Mousetrap_0.1.6p2/data.zip? Give me an overview.",
        "Summarise /saves/1234/pfx/drive_c/users/steamuser/AppData/slot1.dat",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "reverse_engineering" in intent["domains"], f"expected reverse_engineering for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_unrelated_requests_do_not_get_the_domain():
    prompts = [
        "hi",
        "What's the weather in Pune tomorrow?",
        "Write a python script that sorts a list",
        "Implement binary search in rust",
        "Draft an email to my landlord",
        "Execute the unit tests in this folder",
        "Explain how a dynamic link library differs from a static one",
        "Remind me to buy milk",
        "Compare ./games/ and ./saves/ in my repo",
        "Is https://example.com/games/list.html up?",
    ]
    for p in prompts:
        assert "reverse_engineering" not in _classify(p)["domains"], f"false positive: {p!r}"


def test_domain_seeds_the_ten_rea_tools_under_server_id_rea():
    assert _DOMAIN_TOOL_MAP["reverse_engineering"] == {f"mcp__rea__{t}" for t in REA_TOOLS}


def test_domain_has_a_rule_pack_and_it_is_applied():
    assert "reverse_engineering" in _DOMAIN_RULES
    rules = _domain_rules_for_tools({"mcp__rea__open_binary"})
    assert _DOMAIN_RULES["reverse_engineering"] in rules
    rule = _DOMAIN_RULES["reverse_engineering"]
    assert "open_binary" in rule
    # A real 35B model fell back to `bash ls /games` on the host (the mount only
    # exists in the container) and picked inspect_artifact, which takes no path.
    assert "never look for these paths on the host" in rule
    assert "analyze_javascript_application" in rule


def test_workspace_terminus_toolset_keeps_the_rea_tools():
    """With a workspace set, a coding-style request swaps the tool set for the
    Terminus one and keeps only preserved domains' tools."""
    assert _DOMAIN_TOOL_MAP["reverse_engineering"] <= _TERMINUS_PRESERVED_TOOLS
