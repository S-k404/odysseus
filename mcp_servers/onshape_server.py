"""
onshape_server.py

MCP server providing Onshape CAD integration:
- Verifying authentication and user session
- Listing documents and searching CAD models
- Inspecting document workspaces, Part Studios, and Assemblies
- Exporting 3D geometry (STEP for KiCad 3D clearance, STL for 3D printing, DXF for board Edge.Cuts)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("onshape_cad")

BASE_URL = "https://cad.onshape.com"


def _get_credentials() -> tuple[str, str]:
    access_key = os.environ.get("ONSHAPE_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("ONSHAPE_SECRET_KEY", "").strip()
    return access_key, secret_key


def _create_headers(method: str, url: str, content_type: str = "application/json") -> Dict[str, str]:
    access_key, secret_key = _get_credentials()
    if not access_key or not secret_key:
        raise ValueError("ONSHAPE_ACCESS_KEY or ONSHAPE_SECRET_KEY environment variable is not set.")

    alphabet = string.ascii_letters + string.digits
    nonce = "".join(random.choices(alphabet, k=25))
    auth_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    parsed_url = urllib.parse.urlparse(url)
    url_path = parsed_url.path
    url_query = parsed_url.query if parsed_url.query else ""

    message = f"{method.upper()}\n{nonce}\n{auth_date}\n{content_type}\n{url_path}\n{url_query}\n".lower()

    hmac_obj = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    signature = base64.b64encode(hmac_obj.digest()).decode("utf-8")
    auth_header = f"On {access_key}:HmacSHA256:{signature}"

    return {
        "Content-Type": content_type,
        "On-Nonce": nonce,
        "Date": auth_date,
        "Authorization": auth_header,
        "Accept": "application/vnd.onshape.v1+json",
        "User-Agent": "Odysseus-Onshape-MCP/1.0",
    }


def _onshape_api_request(method: str, path: str, query_params: Optional[Dict[str, Any]] = None, body: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)

    headers = _create_headers(method, url, content_type="application/json")
    data = json.dumps(body).encode("utf-8") if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        return {"error": f"HTTP {e.code}: {e.reason}", "details": err_msg}
    except Exception as e:
        return {"error": str(e)}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_onshape_connection",
            description="Verify Onshape API key credentials and retrieve authenticated user account and organization details.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="list_onshape_documents",
            description="List recent Onshape CAD documents or search for projects by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search term to filter document names",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of documents to return (default: 10)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="get_onshape_document_elements",
            description="List all elements (Part Studios, Assemblies, Drawings, and Blobs) inside an Onshape document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "The Onshape Document ID (from URL e.g. /documents/<document_id>/w/...)",
                    },
                    "workspace_id": {
                        "type": "string",
                        "description": "Optional Workspace ID (default: document default workspace)",
                    },
                },
                "required": ["document_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()

    if name == "check_onshape_connection":
        res = await loop.run_in_executor(None, _onshape_api_request, "GET", "/api/users/sessioninfo", None, None)
        if "error" in res:
            return [TextContent(type="text", text=f"❌ Onshape Authentication Failed: {res.get('error')}\nDetails: {res.get('details', '')}")]

        # API-key sessions return null name/email; only show them when present.
        user_name = res.get("name") or ""
        email = res.get("email") or ""
        roles = res.get("roles", [])
        state = res.get("state", 1)
        status_str = "Active" if state == 1 else f"State {state}"

        out = ["# ✔ Onshape API Connected Successfully"]
        if user_name or email:
            out.append(f"- **User**: {user_name or email}" + (f" ({email})" if user_name and email else ""))
        out += [
            f"- **Account Status**: {status_str}",
            f"- **User ID**: `{res.get('id', 'N/A')}`",
        ]
        return [TextContent(type="text", text="\n".join(out))]

    elif name == "list_onshape_documents":
        query = arguments.get("query", "").strip()
        limit = min(int(arguments.get("limit", 10)), 30)

        params: Dict[str, Any] = {"limit": limit}
        if query:
            params["q"] = query

        res = await loop.run_in_executor(None, _onshape_api_request, "GET", "/api/documents", params, None)
        if "error" in res:
            return [TextContent(type="text", text=f"Error listing documents: {res.get('error')}")]

        items = res.get("items", [])
        if not items:
            return [TextContent(type="text", text=f"No Onshape documents found{' matching ' + query if query else ''}.")]

        out = [
            f"### Onshape Documents ({len(items)} found):\n",
            "| Document Name | Document ID | Modified Date | Owner |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for it in items:
            name_val = it.get("name", "Untitled")
            doc_id = it.get("id", "")
            mod_date = (it.get("modifiedAt", "") or "")[:10]
            owner_info = it.get("owner", {})
            owner_name = owner_info.get("name", "Me") if isinstance(owner_info, dict) else str(owner_info)
            out.append(f"| **{name_val}** | `{doc_id}` | {mod_date} | {owner_name} |")

        return [TextContent(type="text", text="\n".join(out))]

    elif name == "get_onshape_document_elements":
        doc_id = arguments.get("document_id", "").strip()
        ws_id = arguments.get("workspace_id", "").strip()

        if not doc_id:
            return [TextContent(type="text", text="Error: document_id is required")]

        # If workspace_id is not given, fetch document to find default workspace
        if not ws_id:
            doc_info = await loop.run_in_executor(None, _onshape_api_request, "GET", f"/api/documents/{doc_id}", None, None)
            if "defaultWorkspace" in doc_info:
                ws_id = doc_info["defaultWorkspace"].get("id", "")

        path = f"/api/documents/d/{doc_id}/w/{ws_id}/elements" if ws_id else f"/api/documents/{doc_id}/elements"
        res = await loop.run_in_executor(None, _onshape_api_request, "GET", path, None, None)
        if "error" in res:
            return [TextContent(type="text", text=f"Error fetching document elements: {res.get('error')}")]

        elements = res if isinstance(res, list) else res.get("elements", [])
        if not elements:
            return [TextContent(type="text", text=f"No elements found in document `{doc_id}`.")]

        out = [
            f"# Elements in Onshape Document (`{doc_id}`)\n",
            "| Element Name | Type | Element ID |",
            "| :--- | :--- | :--- |",
        ]
        for el in elements:
            el_name = el.get("name", "Unnamed")
            el_type = el.get("type", "Unknown")
            el_id = el.get("id", "")
            out.append(f"| **{el_name}** | `{el_type}` | `{el_id}` |")

        return [TextContent(type="text", text="\n".join(out))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
