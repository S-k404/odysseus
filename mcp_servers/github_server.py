"""
github_server.py

MCP server providing GitHub integration: repository search, viewing file contents,
inspecting issues and pull requests, and checking developer profiles.
Uses official GitHub REST API (v3) via standard urllib with optional GITHUB_TOKEN.
"""

import asyncio
import base64
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("github_integration")

API_BASE = "https://api.github.com"


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Odysseus-GitHub-Agent/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _http_get(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="github_search_repos",
            description="Search GitHub repositories by keyword, topic, or language.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords or search qualifiers (e.g. 'agentic mcp language:python', 'odysseus')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of repositories to return (default: 5, max: 10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="github_get_file_contents",
            description="Fetch the text contents of a file from any public or permitted GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repository owner / organization"},
                    "repo": {"type": "string", "description": "Repository name"},
                    "path": {"type": "string", "description": "File path in repo (e.g. 'README.md', 'src/main.py')"},
                    "ref": {"type": "string", "description": "Branch, tag, or commit SHA (default: default branch)"},
                },
                "required": ["owner", "repo", "path"],
            },
        ),
        Tool(
            name="github_list_issues",
            description="List recent issues or pull requests in a GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repository owner"},
                    "repo": {"type": "string", "description": "Repository name"},
                    "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                },
                "required": ["owner", "repo"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()

    if name == "github_search_repos":
        query = (arguments.get("query") or "").strip()
        limit = min(int(arguments.get("limit", 5)), 10)
        if not query:
            return [TextContent(type="text", text="Error: query is required")]

        encoded = urllib.parse.quote_plus(query)
        url = f"{API_BASE}/search/repositories?q={encoded}&per_page={limit}&sort=stars"
        try:
            data = await loop.run_in_executor(None, lambda: _http_get(url))
            items = data.get("items", [])
            if not items:
                return [TextContent(type="text", text=f"No repositories found for '{query}'.")]

            out = [f"### GitHub Repositories matching: \"{query}\"\n"]
            for r in items:
                desc = r.get("description") or "No description."
                stars = r.get("stargazers_count", 0)
                forks = r.get("forks_count", 0)
                lang = r.get("language") or "Unspecified"
                url = r.get("html_url")
                out.append(
                    f"#### [{r['full_name']}]({url})\n"
                    f"- **Stars**: ⭐ {stars:,} | **Forks**: 🍴 {forks:,} | **Language**: `{lang}`\n"
                    f"- **Description**: {desc}\n"
                )
            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"GitHub API error: {e}")]

    elif name == "github_get_file_contents":
        owner = arguments.get("owner", "").strip()
        repo = arguments.get("repo", "").strip()
        path = arguments.get("path", "").strip()
        ref = arguments.get("ref")

        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        if ref:
            url += f"?ref={urllib.parse.quote_plus(ref)}"

        try:
            data = await loop.run_in_executor(None, lambda: _http_get(url))
            if data.get("type") != "file":
                return [TextContent(type="text", text=f"Path '{path}' is not a file (it is a {data.get('type')})")]

            content_b64 = data.get("content", "")
            raw_bytes = base64.b64decode(content_b64)
            text = raw_bytes.decode("utf-8", errors="replace")

            # Limit output to reasonable size
            if len(text) > 30000:
                text = text[:30000] + f"\n\n[... Truncated, {len(text)} total characters ...]"

            return [TextContent(type="text", text=f"### File: `{owner}/{repo}/{path}`\n\n```\n{text}\n```")]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to fetch file: {e}")]

    elif name == "github_list_issues":
        owner = arguments.get("owner", "").strip()
        repo = arguments.get("repo", "").strip()
        state = arguments.get("state", "open")

        url = f"{API_BASE}/repos/{owner}/{repo}/issues?state={state}&per_page=10"
        try:
            items = await loop.run_in_executor(None, lambda: _http_get(url))
            if not items:
                return [TextContent(type="text", text=f"No {state} issues or PRs found in {owner}/{repo}")]

            out = [f"### Recent {state.capitalize()} Issues & PRs in `{owner}/{repo}`:\n"]
            for it in items:
                is_pr = "pull_request" in it
                tag = "PR" if is_pr else "Issue"
                user = it.get("user", {}).get("login", "unknown")
                num = it.get("number")
                title = it.get("title")
                url = it.get("html_url")
                out.append(f"- **[#{num}]({url})** [{tag}] {title} *(by @{user})*")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing issues: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

