"""Tests for Codex MCP scoped routes.

Covers:
- GET /api/codex/mcp/tools
- POST /api/codex/mcp/{server_id}/{tool_name}
- Scope enforcement: mcp:read vs mcp:call
- Admin requirement for cookie-session callers
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from fastapi import HTTPException
from routes.codex_routes import setup_codex_routes


def _api_token_request(*, scopes=None, owner="alice"):
    """Simulate an API-token request."""
    return SimpleNamespace(
        state=SimpleNamespace(
            current_user="api",
            api_token=True,
            api_token_scopes=scopes or [],
            api_token_owner=owner,
        ),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)),
        headers={},
    )


def _cookie_request(*, current_user="bob", is_admin=False):
    """Simulate a cookie-session request."""
    auth_mgr = SimpleNamespace(
        is_configured=True,
        is_admin=lambda user: is_admin and user == "bob",
    )
    return SimpleNamespace(
        state=SimpleNamespace(
            current_user=current_user,
            api_token=False,
        ),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=auth_mgr)),
        headers={},
    )


@pytest.fixture
def mock_mcp_manager():
    mgr = MagicMock()
    mgr.get_all_tools.return_value = [
        {"name": "uncensor_folder", "server_id": "uncensor", "description": "Decensor folder"}
    ]
    mgr.call_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "job started"}]})
    return mgr


@pytest.fixture
def codex_routes(mock_mcp_manager):
    router = setup_codex_routes(mcp_manager=mock_mcp_manager)
    # Extract route endpoints by path and method
    endpoints = {}
    for route in router.routes:
        for method in route.methods:
            endpoints[(method, route.path)] = route.endpoint
    return endpoints, mock_mcp_manager


def test_mcp_tools_requires_mcp_read_scope(codex_routes):
    endpoints, _ = codex_routes
    endpoint = endpoints[("GET", "/api/codex/mcp/tools")]

    # Without mcp scope -> 403
    req = _api_token_request(scopes=["todos:read"])
    with pytest.raises(HTTPException) as exc:
        endpoint(req)
    assert exc.value.status_code == 403

    # With mcp:read scope -> success
    req_ok = _api_token_request(scopes=["mcp:read"])
    res = endpoint(req_ok)
    assert "tools" in res
    assert len(res["tools"]) == 1
    assert res["tools"][0]["name"] == "uncensor_folder"


def test_mcp_tools_accepts_mcp_call_scope(codex_routes):
    endpoints, _ = codex_routes
    endpoint = endpoints[("GET", "/api/codex/mcp/tools")]
    req = _api_token_request(scopes=["mcp:call"])
    res = endpoint(req)
    assert "tools" in res


def test_mcp_tools_cookie_admin_gate(codex_routes, monkeypatch):
    endpoints, _ = codex_routes
    endpoint = endpoints[("GET", "/api/codex/mcp/tools")]
    monkeypatch.setenv("AUTH_ENABLED", "true")

    # Non-admin cookie session -> 403
    req_non_admin = _cookie_request(is_admin=False)
    with pytest.raises(HTTPException) as exc:
        endpoint(req_non_admin)
    assert exc.value.status_code == 403

    # Admin cookie session -> success
    req_admin = _cookie_request(is_admin=True)
    res = endpoint(req_admin)
    assert "tools" in res


@pytest.mark.asyncio
async def test_mcp_call_tool_requires_mcp_call_scope(codex_routes):
    endpoints, mgr = codex_routes
    endpoint = endpoints[("POST", "/api/codex/mcp/{server_id}/{tool_name}")]

    # With only mcp:read -> 403
    req_read = _api_token_request(scopes=["mcp:read"])
    with pytest.raises(HTTPException) as exc:
        await endpoint("uncensor", "uncensor_folder", req_read, {"folder": "/tmp"})
    assert exc.value.status_code == 403

    # With mcp:call -> success
    req_call = _api_token_request(scopes=["mcp:call"])
    res = await endpoint("uncensor", "uncensor_folder", req_call, {"folder": "/tmp"})
    mgr.call_tool.assert_awaited_once_with("mcp__uncensor__uncensor_folder", {"folder": "/tmp"})
    assert "content" in res


def test_mcp_tools_503_when_no_manager():
    router = setup_codex_routes(mcp_manager=None)
    endpoints = {((list(r.methods)[0]), r.path): r.endpoint for r in router.routes}
    endpoint = endpoints[("GET", "/api/codex/mcp/tools")]
    req = _api_token_request(scopes=["mcp:read"])
    with pytest.raises(HTTPException) as exc:
        endpoint(req)
    assert exc.value.status_code == 503
