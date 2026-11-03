"""
pubmed_server.py

MCP server providing biomedical literature search and article abstract retrieval
from NCBI PubMed using NCBI E-utilities REST API.
Zero heavy dependencies (uses standard library urllib and xml.etree).
"""

import asyncio
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("pubmed_research")

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS = {"User-Agent": "Odysseus-PubMed/1.0 (mailto:biomed@local.agent)"}


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="pubmed_search",
            description="Search PubMed for biomedical, clinical, biochemical, genetic, and life-science publications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, disease name, gene symbol, drug name, or clinical topic (e.g. 'CRISPR Cas9 base editing sickle cell', 'EGFR inhibitors resistance')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default: 5, max: 15)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="pubmed_get_abstract",
            description="Get full title, abstract, authors, journal, DOI, and publication year for a specific PubMed PMID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pmid": {
                        "type": "string",
                        "description": "The PubMed ID (e.g. '38148325' or 'PMID:38148325').",
                    }
                },
                "required": ["pmid"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "pubmed_search":
        query = (arguments.get("query") or "").strip()
        max_results = min(int(arguments.get("max_results", 5)), 15)

        if not query:
            return [TextContent(type="text", text="Error: search query cannot be empty")]

        loop = asyncio.get_running_loop()
        try:
            # 1. Search for PMIDs
            encoded = urllib.parse.quote_plus(query)
            search_url = f"{BASE_URL}/esearch.fcgi?db=pubmed&term={encoded}&retmax={max_results}&sort=relevance&retmode=json"
            data = await loop.run_in_executor(None, _http_get, search_url)
            search_json = json.loads(data)
            id_list = search_json.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return [TextContent(type="text", text=f"No PubMed articles found for query: '{query}'")]

            # 2. Fetch summaries for these IDs
            ids_str = ",".join(id_list)
            summary_url = f"{BASE_URL}/esummary.fcgi?db=pubmed&id={ids_str}&retmode=json"
            sum_data = await loop.run_in_executor(None, _http_get, summary_url)
            sum_json = json.loads(sum_data).get("result", {})

            out = [f"### PubMed Search Results for: \"{query}\" ({len(id_list)} articles found)\n"]
            for pmid in id_list:
                item = sum_json.get(pmid, {})
                title = item.get("title", "No Title").rstrip(".")
                pubdate = item.get("pubdate", "")
                source = item.get("source", "")
                authors = [a.get("name", "") for a in item.get("authors", [])][:3]
                auth_str = ", ".join(authors) + (" et al." if len(item.get("authors", [])) > 3 else "")
                doi = ""
                for aid in item.get("articleids", []):
                    if aid.get("idtype") == "doi":
                        doi = aid.get("value")
                        break

                out.append(
                    f"#### [{title}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)\n"
                    f"- **PMID**: `{pmid}` | **Journal**: *{source}* ({pubdate})"
                    + (f" | **DOI**: `{doi}`" if doi else "") + "\n"
                    f"- **Authors**: {auth_str}\n"
                    f"- **Direct Link**: https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n"
                )

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"PubMed search error: {e}")]

    elif name == "pubmed_get_abstract":
        raw_pmid = (arguments.get("pmid") or "").strip()
        pmid = re.sub(r"[^\d]", "", raw_pmid)
        if not pmid:
            return [TextContent(type="text", text="Error: valid numeric PMID required")]

        loop = asyncio.get_running_loop()
        try:
            fetch_url = f"{BASE_URL}/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
            xml_text = await loop.run_in_executor(None, _http_get, fetch_url)
            root = ET.fromstring(xml_text)

            article = root.find(".//Article")
            if article is None:
                return [TextContent(type="text", text=f"Article PMID {pmid} not found")]

            title = (article.findtext("ArticleTitle") or "").strip()
            abstract_nodes = article.findall(".//AbstractText")
            abstract_parts = []
            for node in abstract_nodes:
                label = node.attrib.get("Label")
                text = node.text or ""
                if label:
                    abstract_parts.append(f"**{label}**: {text}")
                else:
                    abstract_parts.append(text)
            abstract = "\n\n".join(abstract_parts) if abstract_parts else "No abstract available."

            journal = article.findtext(".//Journal/Title") or ""
            pub_year = article.findtext(".//JournalIssue/PubDate/Year") or ""

            authors = []
            for a in article.findall(".//Author"):
                last = a.findtext("LastName") or ""
                fore = a.findtext("ForeName") or ""
                if last:
                    authors.append(f"{fore} {last}".strip())

            out = [
                f"# {title}",
                f"- **PMID**: `{pmid}`",
                f"- **Journal**: {journal} ({pub_year})",
                f"- **Authors**: {', '.join(authors) if authors else 'Not listed'}",
                f"- **PubMed Link**: https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n",
                f"### Abstract\n{abstract}",
            ]
            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error fetching abstract for PMID {pmid}: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

