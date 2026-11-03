"""
arxiv_server.py

MCP server providing academic paper search and summary retrieval from arXiv.
Zero external dependencies (uses Python standard library xml.etree and urllib).
"""

import asyncio
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("arxiv_research")

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _fetch_arxiv_atom(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Odysseus-Academic-Research/1.0 (mailto:research@local.agent)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def _parse_entry(entry: ET.Element) -> Dict[str, Any]:
    title = (entry.findtext("atom:title", namespaces=ATOM_NS) or "").strip().replace("\n", " ")
    summary = (entry.findtext("atom:summary", namespaces=ATOM_NS) or "").strip().replace("\n", " ")
    published = (entry.findtext("atom:published", namespaces=ATOM_NS) or "")[:10]
    entry_id = (entry.findtext("atom:id", namespaces=ATOM_NS) or "").strip()

    # Extract clean arXiv ID
    arxiv_id_m = re.search(r"arxiv\.org/abs/([^/]+)$", entry_id)
    arxiv_id = arxiv_id_m.group(1) if arxiv_id_m else entry_id

    authors = []
    for author in entry.findall("atom:author", namespaces=ATOM_NS):
        name = author.findtext("atom:name", namespaces=ATOM_NS)
        if name:
            authors.append(name.strip())

    pdf_url = ""
    for link in entry.findall("atom:link", namespaces=ATOM_NS):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    primary_cat = ""
    prim = entry.find("arxiv:primary_category", namespaces=ATOM_NS)
    if prim is not None:
        primary_cat = prim.attrib.get("term", "")

    return {
        "id": arxiv_id,
        "title": title,
        "authors": authors,
        "published": published,
        "summary": summary,
        "pdf_url": pdf_url,
        "category": primary_cat,
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_arxiv_papers",
            description="Search arXiv for academic papers, preprints, and research literature in Computer Science, AI, Physics, Math, and Engineering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, title words, or topics (e.g. 'local LLM agent reasoning', 'PCB routing reinforcement learning')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of papers to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_arxiv_paper",
            description="Get the full title, abstract, authors, category, and direct PDF link for a specific arXiv ID (e.g. '2310.06825').",
            inputSchema={
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "The exact arXiv identifier (e.g. '2310.06825')",
                    }
                },
                "required": ["arxiv_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_arxiv_papers":
        query = (arguments.get("query") or "").strip()
        max_res = min(int(arguments.get("max_results", 5)), 15)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty")]

        clean_query = re.sub(r"[^\w\s]", " ", query).strip()
        encoded = urllib.parse.quote_plus(f"all:{clean_query}")
        url = f"http://export.arxiv.org/api/query?search_query={encoded}&start=0&max_results={max_res}&sortBy=relevance&sortOrder=descending"

        try:
            loop = asyncio.get_running_loop()
            xml_text = await loop.run_in_executor(None, _fetch_arxiv_atom, url)
            root = ET.fromstring(xml_text)
            entries = root.findall("atom:entry", namespaces=ATOM_NS)

            if not entries:
                return [TextContent(type="text", text=f"No papers found on arXiv matching '{query}'.")]

            out = [f"### arXiv Research Results for: \"{query}\" ({len(entries)} papers found)\n"]
            for e in entries:
                p = _parse_entry(e)
                auth_str = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
                snippet = p["summary"][:250] + "..." if len(p["summary"]) > 250 else p["summary"]
                out.append(
                    f"#### [{p['title']}](https://arxiv.org/abs/{p['id']})\n"
                    f"- **arXiv ID**: `{p['id']}` | **Published**: {p['published']} | **Category**: `{p['category']}`\n"
                    f"- **Authors**: {auth_str}\n"
                    f"- **PDF Link**: {p['pdf_url']}\n"
                    f"- **Abstract**: {snippet}\n"
                )

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error querying arXiv: {e}")]

    elif name == "get_arxiv_paper":
        raw_id = (arguments.get("arxiv_id") or "").strip()
        clean_id = re.sub(r"^arxiv:", "", raw_id, flags=re.IGNORECASE).strip()

        if not clean_id:
            return [TextContent(type="text", text="Error: arxiv_id is required")]

        url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote_plus(clean_id)}"
        try:
            loop = asyncio.get_running_loop()
            xml_text = await loop.run_in_executor(None, _fetch_arxiv_atom, url)
            root = ET.fromstring(xml_text)
            entries = root.findall("atom:entry", namespaces=ATOM_NS)

            if not entries:
                return [TextContent(type="text", text=f"Paper with arXiv ID '{clean_id}' not found.")]

            p = _parse_entry(entries[0])
            details = [
                f"# {p['title']}",
                f"- **arXiv ID**: `{p['id']}`",
                f"- **Published Date**: {p['published']}",
                f"- **Primary Category**: `{p['category']}`",
                f"- **Authors**: {', '.join(p['authors'])}",
                f"- **Paper URL**: https://arxiv.org/abs/{p['id']}",
                f"- **Direct PDF**: {p['pdf_url']}\n",
                f"### Abstract\n{p['summary']}",
            ]
            return [TextContent(type="text", text="\n".join(details))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching paper details: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
