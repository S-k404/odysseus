"""Lexical MCP tool selection, used when the ChromaDB tool index is down."""

from src.tool_index import keyword_mcp_tools


def _tool(server, name, description="", disabled=False):
    return {
        "server_id": server,
        "server_name": f"Built-in: {server}",
        "name": name,
        "qualified_name": f"mcp__{server}__{name}",
        "description": description,
        "is_disabled": disabled,
    }


class _Mgr:
    def __init__(self, tools):
        self.tools = tools

    def get_all_tools(self, disabled_map=None):
        return self.tools


TOOLS = [
    _tool("arxiv_research", "search_arxiv_papers", "Search arXiv for academic papers"),
    _tool("arxiv_research", "get_arxiv_paper", "Fetch one arXiv paper by id"),
    _tool("pubmed", "search_pubmed", "Search biomedical literature papers"),
    _tool("sqlite_explorer", "list_sqlite_tables", "List tables in a SQLite database"),
    _tool("sqlite_explorer", "query_sqlite", "Run a read-only SQL query"),
    _tool("kicad_eda", "run_drc", "Run design rule checks on a KiCad board"),
    _tool("github", "list_repos", "List GitHub repositories"),
]
MGR = _Mgr(TOOLS)


def test_server_and_tool_words_select_that_servers_tools():
    got = keyword_mcp_tools("find recent arxiv papers about transformers", MGR)
    assert got == {"mcp__arxiv_research__search_arxiv_papers", "mcp__arxiv_research__get_arxiv_paper"}


def test_plural_query_word_matches_singular_tool_name():
    assert "mcp__arxiv_research__get_arxiv_paper" in keyword_mcp_tools("papers", MGR)


def test_generic_chat_selects_nothing():
    assert keyword_mcp_tools("hello", MGR) == set()
    assert keyword_mcp_tools("what can you do for me", MGR) == set()
    assert keyword_mcp_tools("", MGR) == set()


def test_one_shared_description_word_is_not_enough():
    # "biomedical" appears only in pubmed's description.
    assert keyword_mcp_tools("biomedical", MGR) == set()
    assert keyword_mcp_tools("biomedical literature", MGR) == {"mcp__pubmed__search_pubmed"}


def test_sqlite_request_gets_the_sqlite_tools():
    got = keyword_mcp_tools("list the sqlite tables", MGR)
    assert got == {"mcp__sqlite_explorer__list_sqlite_tables", "mcp__sqlite_explorer__query_sqlite"}


def test_generic_verbs_do_not_pull_in_unrelated_servers():
    # "list" is in several tool names but says nothing about which server.
    assert keyword_mcp_tools("list my things", MGR) == set()


def test_generic_verbs_alone_do_not_select_a_tool():
    tools = [*TOOLS, _tool("onshape_cad", "check_onshape_connection", "Check the Onshape API connection")]
    got = keyword_mcp_tools("check my kicad board", _Mgr(tools))
    assert got == {"mcp__kicad_eda__run_drc"}


def test_disabled_tools_are_skipped():
    tools = [_tool("arxiv_research", "search_arxiv_papers", disabled=True), *TOOLS[1:2]]
    assert keyword_mcp_tools("arxiv", _Mgr(tools)) == {"mcp__arxiv_research__get_arxiv_paper"}


def test_result_is_capped_and_best_match_first():
    many = [_tool("pcb_maker", f"pcb_step_{c}", "pcb") for c in "abcdefghijkl"]
    # Equal scores break ties by name, so the cap keeps a..e.
    assert keyword_mcp_tools("pcb", _Mgr(many), limit=5) == {f"mcp__pcb_maker__pcb_step_{c}" for c in "abcde"}


def test_missing_or_broken_manager_selects_nothing():
    class _Broken:
        def get_all_tools(self, disabled_map=None):
            raise RuntimeError("boom")

    assert keyword_mcp_tools("arxiv", None) == set()
    assert keyword_mcp_tools("arxiv", _Broken()) == set()
