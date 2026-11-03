"""
coursera_server.py

MCP server providing Coursera educational catalog search and course syllabus details.
Queries the Coursera catalog API (api.coursera.org) with zero external dependencies.
"""

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("coursera_catalog")

API_BASE = "https://api.coursera.org/api/courses.v1"


def _http_get(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Odysseus-Coursera/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="coursera_search_courses",
            description="Search Coursera courses, university specializations, and professional certificates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, skill, or subject (e.g. 'machine learning', 'quantum computing', 'full stack web')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="coursera_get_course_details",
            description="Get details, description, work effort, and primary language for a specific course ID or slug.",
            inputSchema={
                "type": "object",
                "properties": {
                    "course_slug_or_id": {
                        "type": "string",
                        "description": "Course identifier or slug (e.g. 'machine-learning')",
                    }
                },
                "required": ["course_slug_or_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()

    if name == "coursera_search_courses":
        query = (arguments.get("query") or "").strip()
        limit = min(int(arguments.get("limit", 5)), 10)
        if not query:
            return [TextContent(type="text", text="Error: search query required")]

        try:
            import re
            slugified = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
            elements = []
            
            # 1. Try slug direct lookup first
            try:
                slug_url = f"{API_BASE}?q=slug&slug={urllib.parse.quote_plus(slugified)}&fields=name,slug,description"
                slug_data = await loop.run_in_executor(None, lambda: _http_get(slug_url))
                elements = slug_data.get("elements", [])
            except Exception:
                pass

            # 2. If no direct slug match, fetch catalog elements and filter
            if not elements:
                cat_url = f"{API_BASE}?fields=name,slug,description&limit=100"
                cat_data = await loop.run_in_executor(None, lambda: _http_get(cat_url))
                raw_elements = cat_data.get("elements", [])
                tokens = [t.lower() for t in query.split() if len(t) > 2]
                for el in raw_elements:
                    text_blob = (el.get("name", "") + " " + el.get("description", "")).lower()
                    if any(tok in text_blob for tok in tokens):
                        elements.append(el)
                        if len(elements) >= limit:
                            break

            if not elements:
                return [TextContent(type="text", text=f"No courses found on Coursera matching '{query}'.")]

            out = [f"### Coursera Catalog Results for: \"{query}\"\n"]
            for c in elements[:limit]:
                name_str = c.get("name") or c.get("slug")
                slug = c.get("slug")
                desc = (c.get("description") or "No description provided.")[:200] + "..."
                course_url = f"https://www.coursera.org/learn/{slug}" if slug else "https://www.coursera.org"
                out.append(
                    f"#### [{name_str}]({course_url})\n"
                    f"- **Slug**: `{slug}` | **Course ID**: `{c.get('id')}`\n"
                    f"- **Overview**: {desc}\n"
                )

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Coursera search error: {e}")]

    elif name == "coursera_get_course_details":
        slug = (arguments.get("course_slug_or_id") or "").strip()
        url = f"{API_BASE}?q=slug&slug={urllib.parse.quote_plus(slug)}&fields=description,primaryLanguages,subtitleLanguages"
        try:
            data = await loop.run_in_executor(None, lambda: _http_get(url))
            elements = data.get("elements", [])
            if not elements:
                return [TextContent(type="text", text=f"Course '{slug}' not found on Coursera.")]

            c = elements[0]
            langs = ", ".join(c.get("primaryLanguages", ["English"]))
            desc = c.get("description", "No description.")
            course_url = f"https://www.coursera.org/learn/{slug}"

            out = [
                f"# {c.get('name')}",
                f"- **Link**: {course_url}",
                f"- **Languages**: {langs}",
                f"- **ID**: `{c.get('id')}`\n",
                f"### Course Description\n{desc}",
            ]
            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error retrieving course details: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

