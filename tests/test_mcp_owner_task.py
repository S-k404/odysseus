"""stdio/SSE MCP connections must be opened, served and closed by one dedicated task.

The transports run an anyio task group, and anyio cancel scopes have to be entered and
exited by the same task. McpManager used to open the connection in whichever task called
connect_server, so a connector added or reconnected from a request handler (UI, manage_mcp
tool, builtin reconnect during an agent run) was torn down when that request ended:
the request raised "Attempted to exit a cancel scope that isn't the current tasks's
current cancel scope", and every later call failed with an empty error until restart.
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import pytest

from src.mcp_manager import McpManager


class _Trace:
    def __init__(self):
        self.enter_tasks = []
        self.exit_tasks = []


def _install_fakes(monkeypatch, trace, *, fail_open=None, fail_initialize=None, hang_initialize=False):
    """Patch the mcp client pieces with fakes that behave like the real ones where it matters:
    the transport runs an anyio task group (so its scope is bound to the task that opened it)."""
    import mcp
    import mcp.client.sse
    import mcp.client.stdio

    async def _forever():
        await anyio.sleep_forever()

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        if fail_open is not None:
            raise fail_open
        trace.enter_tasks.append(asyncio.current_task())
        async with anyio.create_task_group() as tg:
            tg.start_soon(_forever)
            try:
                yield ("read", "write")
            finally:
                trace.exit_tasks.append(asyncio.current_task())
                tg.cancel_scope.cancel()

    class FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            if hang_initialize:
                await asyncio.sleep(3600)
            if fail_initialize is not None:
                raise fail_initialize

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name="echo", description="echo text", inputSchema={"type": "object", "properties": {}},
                annotations=None)])

        async def call_tool(self, name, arguments):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")], isError=False)

    monkeypatch.setattr(mcp.client.stdio, "stdio_client", fake_client)
    monkeypatch.setattr(mcp.client.sse, "sse_client", fake_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)


async def _connect(mgr, transport="stdio", server_id="s"):
    if transport == "sse":
        return await mgr.connect_server(server_id, "name", "sse", url="http://127.0.0.1:1/sse")
    return await mgr.connect_server(server_id, "name", "stdio", command="x", args=[])


async def test_connection_outlives_the_connecting_task_and_closes_in_its_own_task(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()

    async def request_handler():
        # Like a request: its own task, inside a task group that is cancelled when the response is done.
        async with anyio.create_task_group() as tg:
            assert await _connect(mgr) is True
            tg.cancel_scope.cancel()

    await asyncio.create_task(request_handler())  # used to raise the cancel-scope RuntimeError

    result = await mgr.call_tool("mcp__s__echo", {})
    assert result["exit_code"] == 0 and result["stdout"] == "hi"

    await asyncio.create_task(mgr.disconnect_server("s"))  # a different task than the one that connected
    assert len(trace.enter_tasks) == 1
    assert trace.exit_tasks == trace.enter_tasks  # opened and closed by the same (owner) task
    assert trace.enter_tasks[0] is not asyncio.current_task()
    assert "s" not in mgr._runners and "s" not in mgr._sessions and "s" not in mgr._connections


async def test_stdio_connection_state_is_unchanged(monkeypatch):
    _install_fakes(monkeypatch, _Trace())
    mgr = McpManager()
    gen = mgr._generation
    assert await _connect(mgr) is True
    assert mgr._connections["s"] == {
        "status": "connected", "name": "name", "transport": "stdio", "tool_count": 1, "identity": "",
    }
    assert [t["name"] for t in mgr._tools["s"]] == ["echo"]
    assert mgr._generation == gen + 1
    await mgr.disconnect_server("s")


async def test_sse_connection_uses_the_same_owner_task(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()
    assert await _connect(mgr, "sse") is True
    assert mgr._connections["s"] == {"status": "connected", "name": "name", "transport": "sse", "tool_count": 1}
    await mgr.disconnect_server("s")
    assert trace.exit_tasks == trace.enter_tasks


async def test_failure_to_open_reports_the_original_error(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace, fail_open=FileNotFoundError("no such command: x"))
    mgr = McpManager()
    assert await _connect(mgr) is False
    assert mgr._connections["s"]["status"] == "error"
    assert "no such command: x" in mgr._connections["s"]["error"]
    assert mgr._runners == {} and "s" not in mgr._sessions


async def test_failure_after_opening_closes_the_transport_and_keeps_the_error_type(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace, fail_initialize=RuntimeError("init boom"))
    mgr = McpManager()
    assert await _connect(mgr) is False
    assert mgr._connections["s"]["error"] == "init boom"  # not wrapped in an ExceptionGroup message
    assert trace.exit_tasks == trace.enter_tasks and len(trace.exit_tasks) == 1
    assert mgr._runners == {}


async def test_cancelled_connect_cleans_up(monkeypatch):
    # connect_all_enabled wraps each connect in wait_for(timeout=20); a hung server must not leak.
    trace = _Trace()
    _install_fakes(monkeypatch, trace, hang_initialize=True)
    mgr = McpManager()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(_connect(mgr), 0.2)
    assert mgr._runners == {}
    assert trace.exit_tasks == trace.enter_tasks and len(trace.exit_tasks) == 1
    assert "s" not in mgr._sessions


async def test_reconnecting_the_same_id_closes_the_previous_connection(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()
    assert await _connect(mgr) is True
    assert await _connect(mgr) is True
    assert len(trace.enter_tasks) == 2 and len(trace.exit_tasks) == 1  # first one closed, second live
    await mgr.disconnect_all()
    assert len(trace.exit_tasks) == 2 and mgr._runners == {}


_ECHO_SERVER = (
    "from mcp.server.fastmcp import FastMCP\n"
    "m = FastMCP('echo')\n"
    "@m.tool()\n"
    "def echo(text: str) -> str:\n"
    "    return text\n"
    "m.run()\n"
)


async def test_real_stdio_server_added_from_a_request_stays_usable():
    mgr = McpManager()

    async def request_handler():
        async with anyio.create_task_group() as tg:
            ok = await mgr.connect_server("real", "echo", "stdio", command=sys.executable, args=["-c", _ECHO_SERVER])
            assert ok is True, mgr._connections.get("real")
            tg.cancel_scope.cancel()

    try:
        await asyncio.wait_for(asyncio.create_task(request_handler()), 60)
        result = await asyncio.wait_for(mgr.call_tool("mcp__real__echo", {"text": "hello"}), 30)
        assert result["exit_code"] == 0, result
        assert result["stdout"] == "hello"
    finally:
        await asyncio.wait_for(asyncio.create_task(mgr.disconnect_server("real")), 30)
    assert mgr._runners == {}
