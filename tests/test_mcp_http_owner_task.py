"""Streamable HTTP MCP connections must be opened, served and closed by one task too.

stdio/SSE already do this (tests/test_mcp_owner_task.py). The HTTP transport used to open its
anyio task group in the background connect task, which ended as soon as it had connected, and
closed it from whichever task ran disconnect_server. anyio then logged "Attempted to exit cancel
scope in a different task" and the connection's reader tasks were never closed by their owner.
"""
import asyncio
import logging
import socket
import subprocess
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


def _install_fakes(monkeypatch, trace, *, fail_open=None, hang_open=False):
    import mcp
    import mcp.client.streamable_http
    import src.mcp_oauth

    async def _forever():
        await anyio.sleep_forever()

    @asynccontextmanager
    async def fake_http_client(*args, **kwargs):
        if hang_open:
            await asyncio.sleep(3600)  # stands in for "waiting for the user to authorize in the browser"
        if fail_open is not None:
            raise fail_open
        trace.enter_tasks.append(asyncio.current_task())
        async with anyio.create_task_group() as tg:
            tg.start_soon(_forever)
            try:
                yield ("read", "write", lambda: "session-id")
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
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name="echo", description="echo text", inputSchema={"type": "object", "properties": {}},
                annotations=None)])

        async def call_tool(self, name, arguments):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")], isError=False)

    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", fake_http_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(src.mcp_oauth, "build_provider", lambda *a, **k: None)


async def _connect(mgr, server_id="h"):
    return await mgr.connect_server(server_id, "name", "http", url="http://127.0.0.1:1/mcp")


async def test_http_connection_is_opened_and_closed_by_the_same_task(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()
    gen = mgr._generation

    assert await _connect(mgr) is True
    assert mgr._connections["h"] == {"status": "connected", "name": "name", "transport": "http", "tool_count": 1}
    assert mgr._generation > gen
    result = await mgr.call_tool("mcp__h__echo", {})
    assert result["exit_code"] == 0 and result["stdout"] == "hi"

    await asyncio.create_task(mgr.disconnect_server("h"))  # not the task that connected
    assert len(trace.enter_tasks) == 1
    assert trace.exit_tasks == trace.enter_tasks
    assert "h" not in mgr._sessions and "h" not in mgr._connections and "h" not in mgr._tools
    assert "h" not in mgr._runners


async def test_http_connection_survives_the_request_that_started_it(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()

    async def request_handler():
        async with anyio.create_task_group() as tg:
            assert await _connect(mgr) is True
            tg.cancel_scope.cancel()

    await asyncio.create_task(request_handler())
    result = await mgr.call_tool("mcp__h__echo", {})
    assert result["exit_code"] == 0
    await mgr.disconnect_server("h")
    assert trace.exit_tasks == trace.enter_tasks


async def test_http_failure_to_connect_reports_an_error_and_leaves_nothing_behind(monkeypatch):
    _install_fakes(monkeypatch, _Trace(), fail_open=ConnectionError("refused"))
    mgr = McpManager()
    assert await _connect(mgr) is False
    assert mgr._connections["h"]["status"] == "error" and "refused" in mgr._connections["h"]["error"]
    assert "h" not in mgr._sessions and "h" not in mgr._runners


async def test_http_connect_waiting_for_authorization_can_be_cancelled_by_disconnect(monkeypatch):
    _install_fakes(monkeypatch, _Trace(), hang_open=True)
    mgr = McpManager()
    assert await mgr._start_http_connect("h", "name", "http://127.0.0.1:1/mcp", wait=0.2) is False
    assert mgr._connections["h"]["status"] == "needs_auth"
    task = mgr._connect_tasks["h"]
    assert not task.done()

    await mgr.disconnect_server("h")
    await asyncio.sleep(0)
    assert task.done()
    assert "h" not in mgr._connections and "h" not in mgr._runners


async def test_http_reconnecting_the_same_id_closes_the_previous_connection(monkeypatch):
    trace = _Trace()
    _install_fakes(monkeypatch, trace)
    mgr = McpManager()
    assert await _connect(mgr) is True
    assert await _connect(mgr) is True
    assert len(trace.enter_tasks) == 2 and len(trace.exit_tasks) == 1
    await mgr.disconnect_all()
    assert len(trace.exit_tasks) == 2 and mgr._runners == {}


_HTTP_SERVER = (
    "import sys\n"
    "from mcp.server.fastmcp import FastMCP\n"
    "m = FastMCP('echo', host='127.0.0.1', port=int(sys.argv[1]))\n"
    "@m.tool()\n"
    "def echo(text: str) -> str:\n"
    "    return text\n"
    "m.run(transport='streamable-http')\n"
)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(port, proc, timeout=30):
    for _ in range(int(timeout * 10)):
        if proc.poll() is not None:
            raise RuntimeError("test MCP server exited early")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError("test MCP server did not start")


async def test_real_http_server_connects_serves_and_disconnects_cleanly(caplog):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-c", _HTTP_SERVER, str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    mgr = McpManager()
    try:
        await _wait_for_port(port, proc)
        with caplog.at_level(logging.WARNING):
            async def request_handler():
                async with anyio.create_task_group() as tg:
                    ok = await mgr.connect_server("real", "echo", "http", url=f"http://127.0.0.1:{port}/mcp")
                    assert ok is True, mgr._connections.get("real")
                    tg.cancel_scope.cancel()

            await asyncio.wait_for(asyncio.create_task(request_handler()), 60)
            result = await asyncio.wait_for(mgr.call_tool("mcp__real__echo", {"text": "hello"}), 30)
            assert result["exit_code"] == 0, result
            assert result["stdout"] == "hello"
            await asyncio.wait_for(asyncio.create_task(mgr.disconnect_server("real")), 30)
        bad = [r.getMessage() for r in caplog.records if "Error closing MCP server" in r.getMessage()]
        assert bad == []
        assert mgr._runners == {} and "real" not in mgr._sessions
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
