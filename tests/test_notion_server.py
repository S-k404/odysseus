"""Built-in read-only Notion MCP server (mcp_servers/notion_server.py).

Everything runs against an in-process fake of the Notion API served through
httpx.MockTransport, with a fake clock in place of time.monotonic/time.sleep,
so no sockets are opened and no test ever really sleeps.

Pinned behavior: the server can only read; search ranks by title-keyword
overlap; page trees render with properties, nesting, pagination and a depth
limit; `find` narrows a page to matching lines; database rows and filters work
(filter as object or JSON string); errors are explained without leaking the
token or query strings; reads are cached briefly and errors never are; 429s are
retried honoring Retry-After; the limiter allows a small burst then paces.
"""

import asyncio
import json
import types

import httpx
import pytest

from mcp_servers import notion_server as ns

TOKEN = "ntn_your_notion_integration_token_here"


def _id(n):
    h = f"{n:032x}"
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _short(n):
    return f"{n:032x}"


def _page(n, title, parent=None, props=None, edited="2026-09-01"):
    page = {
        "object": "page", "id": _id(n), "last_edited_time": edited + "T00:00:00Z",
        "url": "https://notion.so/" + title.replace(" ", "-") + "-" + _short(n),
        "parent": parent or {"type": "workspace", "workspace": True},
        "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}},
    }
    page["properties"].update(props or {})
    return page


def _database(n, title, columns):
    return {
        "object": "database", "id": _id(n), "last_edited_time": "2026-09-02T00:00:00Z",
        "url": "https://notion.so/" + title + "-" + _short(n),
        "parent": {"type": "workspace", "workspace": True},
        "title": [{"plain_text": title}],
        "properties": {"Name": {"type": "title"}, **{k: {"type": v} for k, v in columns.items()}},
    }


def _block(n, type_, text="", children=False, **extra):
    body = {"rich_text": [{"plain_text": text}]} if type_ != "child_page" else {}
    body.update(extra)
    return {"id": _id(n), "type": type_, "has_children": children, type_: body}


class _Clock:
    """Stands in for the `time` module: sleeping just advances the clock."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


class FakeNotion:
    def __init__(self):
        self.requests = []          # (method, path, params, body)
        self.headers = []
        self.catalog = []           # pages and databases visible to search
        self.objects = {}           # id -> page/database
        self.children = {}          # block id -> list of blocks, or list of pages (lists) of blocks
        self.rows = {}              # database id -> list of row pages
        self.script = {}            # (method, path) -> list of (status, json, headers) served first
        self.rows_have_more = False

    def add(self, obj, searchable=True):
        self.objects[obj["id"]] = obj
        if searchable:
            self.catalog.append(obj)
        return obj

    def handler(self, request):
        path = request.url.path.removeprefix("/v1")
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, params, body))
        self.headers.append(dict(request.headers))
        queued = self.script.get((request.method, path))
        if queued:
            status, payload, headers = queued.pop(0)
            return httpx.Response(status, json=payload, headers=headers)
        if request.method == "POST" and path == "/search":
            q = (body.get("query") or "").lower()
            hits = [o for o in self.catalog if q in ns._title_of(o).lower()]
            if not q:
                hits = sorted(self.catalog, key=lambda o: o["last_edited_time"], reverse=True)
            wanted = (body.get("filter") or {}).get("value")
            if wanted:
                hits = [o for o in hits if o["object"] == wanted]
            return httpx.Response(200, json={"results": hits[: body.get("page_size", 100)]})
        if request.method == "POST" and path.endswith("/query"):
            db_id = path.split("/")[2]
            return httpx.Response(200, json={"results": self.rows.get(db_id, []), "has_more": self.rows_have_more})
        if request.method == "GET" and path.startswith("/blocks/") and path.endswith("/children"):
            block_id = path.split("/")[2]
            if block_id not in self.children:
                return httpx.Response(404, json={"message": "Could not find block"})
            data = self.children[block_id]
            if data and isinstance(data[0], list):      # paginated: list of pages of blocks
                index = int(params.get("start_cursor", 0))
                more = index + 1 < len(data)
                return httpx.Response(200, json={"results": data[index], "has_more": more,
                                                 "next_cursor": str(index + 1) if more else None})
            return httpx.Response(200, json={"results": data, "has_more": False})
        if request.method == "GET" and path.startswith("/pages/"):
            obj = self.objects.get(path.split("/")[2])
            if obj and obj["object"] == "page":
                return httpx.Response(200, json=obj)
            return httpx.Response(400 if obj else 404, json={"message": "is a database" if obj else "not found"})
        if request.method == "GET" and path.startswith("/databases/"):
            obj = self.objects.get(path.split("/")[2])
            if obj and obj["object"] == "database":
                return httpx.Response(200, json=obj)
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(404, json={"message": "unhandled " + path})


@pytest.fixture
def notion(monkeypatch):
    fake = FakeNotion()
    fake.clock = _Clock()
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)
    monkeypatch.setattr(ns, "time", fake.clock)
    monkeypatch.setattr(ns, "_http", None)
    monkeypatch.setattr(ns, "_cache", {})
    monkeypatch.setattr(ns, "_limiter", ns._Limiter(ns._RATE, ns._BURST))
    real_client = httpx.Client
    monkeypatch.setattr(ns, "httpx", types.SimpleNamespace(
        Client=lambda **kw: real_client(transport=httpx.MockTransport(fake.handler), **kw),
        Timeout=httpx.Timeout, Limits=httpx.Limits, TransportError=httpx.TransportError,
    ))
    return fake


def call(**arguments):
    return asyncio.run(ns.call_tool("manage_notion", arguments))[0].text


# --- safety ---------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("PATCH", "/pages/x"), ("POST", "/pages"), ("DELETE", "/blocks/x"), ("POST", "/comments"),
    ("POST", "/blocks/x/children"), ("PUT", "/search"), ("POST", "/databases/x/query"), ("POST", "/databases/x/y"),
])
def test_only_reads_are_ever_sent(notion, method, path):
    with pytest.raises(ns.NotionError, match="read-only"):
        ns._request(method, path, {})
    assert notion.requests == []


def test_missing_token_explains_setup_and_sends_nothing(notion, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN")
    assert "NOTION_TOKEN is not set" in call(action="search", query="x")
    assert notion.requests == []


def test_requests_carry_bearer_token_and_api_version(notion):
    notion.add(_page(1, "Physics notes"))
    call(action="search", query="physics")
    assert notion.headers[0]["authorization"] == "Bearer " + TOKEN
    assert notion.headers[0]["notion-version"] == "2022-06-28"


def test_tool_schema_exposes_only_read_actions_and_lenient_filter():
    tool = asyncio.run(ns.list_tools())[0]
    props = tool.inputSchema["properties"]
    assert set(props["action"]["enum"]) == {"search", "read", "query"}
    assert set(props["filter"]["type"]) == {"object", "string"}   # small models send filters as strings
    assert "Unknown tool" in asyncio.run(ns.call_tool("other", {}))[0].text


# --- ids ------------------------------------------------------------------

def test_extract_id_accepts_urls_hyphenated_and_bare_ids():
    want = _id(0xABC)
    assert ns._extract_id(f"https://notion.so/ws/Some-Page-{_short(0xABC)}?pvs=4#{'d' * 32}") == want
    assert ns._extract_id(want.upper()) == want
    assert ns._extract_id(_short(0xABC)) == want
    assert ns._extract_id("not an id") is None and ns._extract_id("") is None


# --- search ---------------------------------------------------------------

def test_search_ranks_by_title_keyword_overlap_and_dedupes(notion):
    notion.add(_page(1, "ECE Hub", edited="2026-09-10"))
    notion.add(_page(2, "Physics notes", edited="2026-09-05"))
    notion.add(_page(3, "ECE 201 Physics", edited="2026-09-20"))
    out = call(action="search", query="ece hub notes")
    titles = [line.split(" [")[0][2:] for line in out.splitlines() if line.startswith("- ")]
    assert titles[0] == "ECE Hub"                       # 2 of 3 keywords beats 1 of 3, though newer pages exist
    assert sorted(titles) == ["ECE 201 Physics", "ECE Hub", "Physics notes"]
    assert "also tried: ece, hub, notes" in out
    sent = {body["query"] for method, path, _, body in notion.requests if path == "/search"}
    assert sent == {"ece hub notes", "ece", "hub", "notes"}


def test_single_keyword_search_makes_one_request(notion):
    notion.add(_page(1, "Physics notes"))
    call(action="search", query="physics")
    assert len([r for r in notion.requests if r[1] == "/search"]) == 1


def test_search_labels_rows_with_their_database_and_honors_kind(notion):
    db = notion.add(_database(9, "Tasks", {"Status": "status"}))
    notion.add(_page(4, "HW 1", parent={"type": "database_id", "database_id": db["id"]}))
    out = call(action="search", query="hw")
    assert "HW 1 [row]" in out and f"in={_short(9)}" in out
    assert "Tasks [database]" in call(action="search", kind="database")
    assert notion.requests[-1][3]["filter"] == {"property": "object", "value": "database"}


def test_empty_search_lists_most_recently_edited_first(notion):
    notion.add(_page(1, "Old", edited="2026-01-01"))
    notion.add(_page(2, "New", edited="2026-09-01"))
    out = call(action="search")
    assert out.splitlines()[1].startswith("- New") and "most recently edited" in out
    assert notion.requests[-1][3]["sort"]["timestamp"] == "last_edited_time"


def test_search_with_no_match_says_titles_only_and_sharing(notion):
    out = call(action="search", query="nothing")
    assert "TITLES" in out and "Connections" in out


# --- reading pages --------------------------------------------------------

def test_read_page_renders_properties_nesting_and_hides_signed_urls(notion):
    page = notion.add(_page(1, "Physics notes", props={"Status": {"type": "status", "status": {"name": "Active"}}}))
    notion.children[page["id"]] = [
        _block(10, "heading_1", "Physics"), _block(11, "toggle", "Week 1", children=True),
        _block(12, "to_do", "Read ch1", checked=True), _block(14, "child_page", title="Sub"),
        _block(13, "image", caption=[], file={"url": "https://s3.example/secret?sig=ABC"}),
    ]
    notion.children[_id(11)] = [_block(20, "bulleted_list_item", "Kinematics")]
    out = call(action="read", id=f"https://notion.so/Physics-{_short(1)}?pvs=4")
    assert out.startswith("# Physics notes") and "Properties: Status: Active" in out
    assert "not instructions" in out
    assert "# Physics" in out and "  - Kinematics" in out and "[x] Read ch1" in out
    assert f"[child_page: Sub] id={_short(14)}" in out
    assert "[image: ]" in out and "sig=ABC" not in out


def test_read_page_follows_pagination(notion):
    page = notion.add(_page(1, "Long"))
    notion.children[page["id"]] = [[_block(10, "paragraph", "first page")], [_block(11, "paragraph", "second page")]]
    out = call(action="read", id=_short(1))
    assert "first page" in out and "second page" in out


def test_read_stops_at_depth_limit_and_skips_refused_nested_blocks(notion):
    page = notion.add(_page(1, "Deep"))
    notion.children[page["id"]] = [_block(10, "toggle", "d0", children=True), _block(99, "toggle", "refused", children=True)]
    for level, (parent, child) in enumerate([(10, 11), (11, 12), (12, 13), (13, 14)], start=1):
        notion.children[_id(parent)] = [_block(child, "toggle", f"d{level}", children=True)]
    notion.children[_id(14)] = [_block(15, "paragraph", "too deep")]     # 99 has no entry: Notion answers 404
    out = call(action="read", id=_short(1))
    assert all(f"d{i}" in out for i in range(4)) and "d4" not in out and "too deep" not in out
    assert "refused" in out                                              # the parent line still renders
    requested = {path for _, path, _, _ in notion.requests}
    assert f"/blocks/{_id(14)}/children" not in requested


def test_find_returns_matching_lines_with_context(notion):
    page = notion.add(_page(1, "Notes"))
    notion.children[page["id"]] = [_block(10 + i, "paragraph", f"filler {i}") for i in range(8)] + [
        _block(30, "paragraph", "Dynamics: forces")] + [_block(40 + i, "paragraph", f"tail {i}") for i in range(4)]
    out = call(action="read", id=_short(1), find="dynamics")
    assert "Dynamics: forces" in out and "filler 7" in out and "filler 0" not in out
    assert "showing only lines matching 'dynamics'" in out
    assert "no lines mention" in call(action="read", id=_short(1), find="zebra")


def test_find_falls_back_to_any_word_and_marks_gaps(notion):
    page = notion.add(_page(1, "Notes"))
    notion.children[page["id"]] = [_block(10, "paragraph", "alpha")] + [
        _block(20 + i, "paragraph", f"gap {i}") for i in range(6)] + [_block(30, "paragraph", "omega")]
    out = call(action="read", id=_short(1), find="alpha omega")         # no line has both -> either word
    assert "alpha" in out and "omega" in out and "\n...\n" in out


def test_output_is_clipped_and_max_chars_is_clamped(notion):
    clipped = ns._clip("x" * 5000, 2000)
    assert clipped.startswith("x" * 2000) and "output truncated" in clipped and len(clipped) < 2200
    assert ns._int(100, 24000, 2000, 60000) == 2000
    assert ns._int(10 ** 9, 24000, 2000, 60000) == 60000
    assert ns._int("x", 24000, 2000, 60000) == 24000


# --- databases ------------------------------------------------------------

def _tasks_db(notion):
    db = notion.add(_database(9, "Tasks", {"Status": "status", "Due": "date"}), searchable=False)
    notion.rows[db["id"]] = [_page(4, "HW 1", parent={"type": "database_id", "database_id": db["id"]}, props={
        "Status": {"type": "status", "status": {"name": "Done"}},
        "Due": {"type": "date", "date": {"start": "2026-09-10", "end": None}},
        "Empty": {"type": "select", "select": None},
    })]
    return db


def test_read_database_shows_columns_and_rows_without_empty_cells(notion):
    _tasks_db(notion)
    out = call(action="read", id=_short(9))                 # page lookup answers 400, falls back to database
    assert "(This is a database.)" in out and "Columns: Name (title), Status (status), Due (date)" in out
    assert "HW 1" in out and "Status: Done" in out and "Due: 2026-09-10" in out and "Empty" not in out


def test_query_accepts_filter_as_object_or_json_string_and_notes_more_rows(notion):
    _tasks_db(notion)
    flt = {"property": "Status", "status": {"equals": "Done"}}
    notion.rows_have_more = True
    as_string = call(action="query", id=_short(9), filter=json.dumps(flt), limit=1)
    as_object = call(action="query", id=_short(9), filter=flt, limit=1, fresh=True)   # same request: bypass the cache
    bodies = [r[3] for r in notion.requests if r[1].endswith("/query")]
    assert bodies[0] == bodies[1] == {"page_size": 1, "filter": flt}
    assert "more rows exist" in as_string and "HW 1" in as_object


def test_query_rejects_malformed_filters_and_missing_ids(notion):
    _tasks_db(notion)
    assert "must be a JSON object" in call(action="query", id=_short(9), filter="{not json")
    assert "must be a JSON object" in call(action="query", id=_short(9), filter=["x"])
    assert "needs 'id'" in call(action="query") and "needs 'id'" in call(action="read", id="")
    assert "Unknown action" in call(action="create")


# --- errors ---------------------------------------------------------------

def test_a_400_shows_notions_own_explanation(notion):
    _tasks_db(notion)
    notion.script[("POST", f"/databases/{_id(9)}/query")] = [
        (400, {"message": "Could not find property with name or id: Bad"}, {})]
    out = call(action="query", id=_short(9), filter={"property": "Bad", "status": {"equals": "x"}})
    assert out.startswith("Error: Notion returned 400: bad request: Could not find property")
    assert "newer Notion-Version" not in out and TOKEN not in out


@pytest.mark.parametrize("status,phrase", [(401, "invalid or was revoked"), (403, "Read content"), (404, "not shared")])
def test_auth_and_sharing_errors_are_explained_without_leaking_the_token(notion, status, phrase):
    notion.script[("GET", f"/pages/{_id(7)}")] = [(status, {"message": "nope"}, {})]
    notion.script[("GET", f"/databases/{_id(7)}")] = [(status, {"message": "nope"}, {})]
    out = call(action="read", id=_short(7))
    assert out.startswith("Error:") and phrase in out and TOKEN not in out


def test_errors_never_echo_the_query_string(notion):
    with pytest.raises(ns.NotionError) as err:
        ns._request("GET", f"/blocks/{_id(5)}/children", params={"start_cursor": "zzz-secret-cursor"})
    assert "zzz-secret-cursor" not in str(err.value)


# --- cache ----------------------------------------------------------------

def test_repeat_reads_are_cached_briefly_and_fresh_bypasses(notion):
    page = notion.add(_page(1, "Cached"))
    notion.children[page["id"]] = [_block(10, "paragraph", "hello")]
    call(action="read", id=_short(1))
    first = len(notion.requests)
    call(action="read", id=_short(1))
    assert len(notion.requests) == first                       # served from memory
    call(action="read", id=_short(1), fresh=True)
    assert len(notion.requests) > first                        # fresh=true refetches
    after_fresh = len(notion.requests)
    notion.clock.now += ns._CACHE_TTL + 1
    call(action="read", id=_short(1))
    assert len(notion.requests) > after_fresh                  # entries expire


def test_errors_are_not_cached_so_a_newly_shared_page_works(notion):
    assert "not shared" in call(action="read", id=_short(1))
    page = notion.add(_page(1, "Now shared"))
    notion.children[page["id"]] = [_block(10, "paragraph", "visible")]
    assert "visible" in call(action="read", id=_short(1))


# --- rate limiting --------------------------------------------------------

def test_a_429_is_retried_after_retry_after_and_only_waits_once(notion):
    page = notion.add(_page(1, "Busy"))
    notion.script[("GET", f"/pages/{_id(1)}")] = [(429, {"message": "slow down"}, {"Retry-After": "2"})]
    assert ns._request("GET", f"/pages/{_id(1)}")["id"] == page["id"]
    assert [r[1] for r in notion.requests] == [f"/pages/{_id(1)}"] * 2
    assert notion.clock.sleeps == [2.0]


def test_limiter_allows_a_burst_then_paces(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ns, "time", clock)
    limiter = ns._Limiter(rate=2.0, burst=3)
    for _ in range(3):
        limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()
    limiter.acquire()
    assert clock.sleeps == [0.5, 0.5]                          # one request per 1/rate seconds afterwards


def test_a_penalty_slows_the_next_request(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ns, "time", clock)
    limiter = ns._Limiter(rate=2.0, burst=3)
    limiter.penalize(2.0)
    limiter.acquire()
    assert clock.sleeps == [2.0]


# --- registration ---------------------------------------------------------

async def _registered_servers(monkeypatch, env_token):
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    core = types.ModuleType("core")
    core.__path__ = []
    platform_compat = types.ModuleType("core.platform_compat")
    platform_compat.IS_WINDOWS = False
    platform_compat.which_tool = lambda name: None
    monkeypatch.setitem(sys.modules, "core", core)
    monkeypatch.setitem(sys.modules, "core.platform_compat", platform_compat)
    spec = importlib.util.spec_from_file_location("builtin_mcp_under_test", root / "src" / "builtin_mcp.py")
    builtin_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builtin_mcp)

    if env_token is None:
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
    else:
        monkeypatch.setenv("NOTION_TOKEN", env_token)

    started = []

    def collect(coro):
        started.append(coro)
        return None

    monkeypatch.setattr(builtin_mcp, "_spawn_bg", collect)
    monkeypatch.setattr(builtin_mcp, "MCP_DISABLED", False)
    connected = []

    class FakeManager:
        async def connect_server(self, server_id, **kwargs):
            connected.append(server_id)
            return True

    await builtin_mcp.register_builtin_servers(FakeManager())
    for coro in started:
        if coro.__name__ == "_connect_python_server":
            await coro
        else:
            coro.close()                                       # the npx browser starter is irrelevant here
    return connected


async def test_notion_server_is_skipped_without_a_token(monkeypatch):
    connected = await _registered_servers(monkeypatch, None)
    assert "notion" not in connected and "memory" in connected


async def test_notion_server_is_skipped_for_a_blank_token(monkeypatch):
    assert "notion" not in await _registered_servers(monkeypatch, "   ")


async def test_notion_server_registers_when_a_token_is_set(monkeypatch):
    connected = await _registered_servers(monkeypatch, TOKEN)
    assert "notion" in connected and "memory" in connected
