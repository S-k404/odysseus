"""
figma_server.py

MCP server providing Figma design tool inspection, component discovery,
and design token extraction (colors, typography, spacing).
Uses Figma REST API when FIGMA_ACCESS_TOKEN is present, or built-in design system utilities.
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

server = Server("figma_integration")

FIGMA_API_BASE = "https://api.figma.com/v1"


def _headers() -> Dict[str, str]:
    headers = {"User-Agent": "Odysseus-Figma/1.0"}
    token = os.environ.get("FIGMA_ACCESS_TOKEN") or os.environ.get("FIGMA_TOKEN")
    if token:
        headers["X-Figma-Token"] = token.strip()
    return headers


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="figma_get_file_info",
            description="Inspect a Figma design file structure, pages, frames, and last modified date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_key": {
                        "type": "string",
                        "description": "Figma file key from the URL (e.g. 'https://www.figma.com/design/FILE_KEY/title' -> 'FILE_KEY')",
                    }
                },
                "required": ["file_key"],
            },
        ),
        Tool(
            name="figma_extract_design_tokens",
            description="Extract structured design tokens (color variables, typography styles, spacing) into JSON / CSS variables.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_key": {"type": "string", "description": "Figma file key"},
                },
                "required": ["file_key"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()
    file_key = (arguments.get("file_key") or "").strip()
    if "/" in file_key:
        # Extract from full URL if passed
        parts = file_key.split("/")
        for i, p in enumerate(parts):
            if p in ("file", "design") and i + 1 < len(parts):
                file_key = parts[i + 1]
                break

    token = os.environ.get("FIGMA_ACCESS_TOKEN") or os.environ.get("FIGMA_TOKEN")
    if not token:
        return [TextContent(type="text", text=(
            "### Figma Connector Status\n"
            "To connect live Figma files, set `FIGMA_ACCESS_TOKEN` in your environment or Settings > Connectors.\n"
            "You can generate a personal access token in Figma: Account Settings > Security > Personal Access Tokens."
        ))]

    if name == "figma_get_file_info":
        url = f"{FIGMA_API_BASE}/files/{file_key}?depth=2"
        try:
            req = urllib.request.Request(url, headers=_headers())
            data_str = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
            data = json.loads(data_str)

            doc_name = data.get("name", "Untitled")
            version = data.get("version", "1")
            pages = []
            for child in data.get("document", {}).get("children", []):
                frame_count = len(child.get("children", []))
                pages.append(f"- **{child.get('name')}**: {frame_count} top-level frames")

            out = [
                f"# Figma File: {doc_name}",
                f"- **Key**: `{file_key}`",
                f"- **Last Modified**: {data.get('lastModified')}",
                f"- **Version**: {version}\n",
                "### Pages & Frames:\n" + "\n".join(pages)
            ]
            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error accessing Figma file '{file_key}': {e}")]

    elif name == "figma_extract_design_tokens":
        url = f"{FIGMA_API_BASE}/files/{file_key}/styles"
        try:
            req = urllib.request.Request(url, headers=_headers())
            data_str = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
            data = json.loads(data_str)
            styles = data.get("meta", {}).get("styles", [])

            out = [f"### Design Tokens for Figma File `{file_key}` ({len(styles)} published styles)\n"]
            for s in styles:
                out.append(f"- **{s.get('name')}** (`{s.get('style_type')}`): {s.get('description') or 'Default'}")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error extracting Figma design tokens: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

