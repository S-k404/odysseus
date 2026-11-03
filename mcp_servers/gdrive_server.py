"""
gdrive_server.py

MCP server providing Google Drive and Workspace file search, document reading,
and folder inspection. Works with standard Google OAuth or local tokens.
"""

import asyncio
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("google_drive")

API_BASE = "https://www.googleapis.com/drive/v3"


def _headers() -> Dict[str, str]:
    headers = {"User-Agent": "Odysseus-GDrive/1.0"}
    token = os.environ.get("GOOGLE_DRIVE_TOKEN") or os.environ.get("GOOGLE_WORKSPACE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="gdrive_search_files",
            description="Search files, spreadsheets, presentations, and documents across Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "File name keywords or search query (e.g. 'quarterly report', 'syllabus', 'name contains \".pdf\"')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gdrive_read_file_metadata",
            description="Get metadata, sharing permissions, and web links for a Google Drive file ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Google Drive File ID"},
                },
                "required": ["file_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()
    token = os.environ.get("GOOGLE_DRIVE_TOKEN") or os.environ.get("GOOGLE_WORKSPACE_TOKEN")

    if not token:
        return [TextContent(type="text", text=(
            "### Google Drive Connector Status\n"
            "Google Drive connector is active. To connect to your cloud workspace, authenticate via "
            "Google Workspace OAuth or provide `GOOGLE_DRIVE_TOKEN` in Settings > Connectors."
        ))]

    if name == "gdrive_search_files":
        query = (arguments.get("query") or "").strip()
        limit = min(int(arguments.get("limit", 5)), 15)

        q_clause = f"name contains '{query}' and trashed = false"
        encoded = urllib.parse.quote_plus(q_clause)
        url = f"{API_BASE}/files?q={encoded}&pageSize={limit}&fields=files(id,name,mimeType,modifiedTime,webViewLink,size)"

        try:
            req = urllib.request.Request(url, headers=_headers())
            data_str = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
            data = json.loads(data_str)
            files = data.get("files", [])

            if not files:
                return [TextContent(type="text", text=f"No Google Drive files found matching '{query}'.")]

            out = [f"### Google Drive Search Results for: \"{query}\"\n"]
            for f in files:
                link = f.get("webViewLink", "#")
                mime = f.get("mimeType", "").replace("application/vnd.google-apps.", "")
                mod = f.get("modifiedTime", "")[:10]
                out.append(f"- **[{f.get('name')}]({link})** (`{mime}`, modified {mod})\n  ID: `{f.get('id')}`")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error searching Google Drive: {e}")]

    elif name == "gdrive_read_file_metadata":
        file_id = arguments.get("file_id", "").strip()
        url = f"{API_BASE}/files/{file_id}?fields=id,name,mimeType,description,createdTime,modifiedTime,owners,webViewLink"
        try:
            req = urllib.request.Request(url, headers=_headers())
            data_str = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
            f = json.loads(data_str)

            owners = ", ".join([o.get("displayName", "") for o in f.get("owners", [])])
            out = [
                f"# Google Drive File: {f.get('name')}",
                f"- **ID**: `{f.get('id')}`",
                f"- **Type**: `{f.get('mimeType')}`",
                f"- **Owner**: {owners}",
                f"- **Modified**: {f.get('modifiedTime')}",
                f"- **Link**: {f.get('webViewLink')}\n",
                f"### Description\n{f.get('description') or 'No description provided.'}",
            ]
            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching metadata: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

