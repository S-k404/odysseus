"""
cloudflare_server.py

MCP server providing Cloudflare Developer Platform integration:
Workers scripts, DNS records, KV namespaces, and deployment monitoring.
Uses official Cloudflare REST API v4 with CLOUDFLARE_API_TOKEN.
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

server = Server("cloudflare_platform")

CF_API_BASE = "https://api.cloudflare.com/client/v4"


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "Odysseus-Cloudflare/1.0"}
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="cloudflare_list_workers",
            description="List Cloudflare Workers serverless functions and their deployment statuses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "Cloudflare Account ID (optional, defaults to CLOUDFLARE_ACCOUNT_ID env)",
                    }
                },
            },
        ),
        Tool(
            name="cloudflare_dns_lookup",
            description="Query DNS records for a domain/zone managed by Cloudflare.",
            inputSchema={
                "type": "object",
                "properties": {
                    "zone_name_or_id": {
                        "type": "string",
                        "description": "Domain name or Zone ID (e.g. 'example.com')",
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["A", "AAAA", "CNAME", "TXT", "MX", "ANY"],
                        "default": "ANY",
                    },
                },
                "required": ["zone_name_or_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN")
    account_id = arguments.get("account_id") or os.environ.get("CLOUDFLARE_ACCOUNT_ID")

    if not token:
        return [TextContent(type="text", text=(
            "### Cloudflare Developer Platform Connector\n"
            "To connect live Cloudflare resources, configure `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.\n"
            "You can create an API token with Workers:Read and DNS:Read permissions at dash.cloudflare.com/profile/api-tokens."
        ))]

    if name == "cloudflare_list_workers":
        if not account_id:
            return [TextContent(type="text", text="Error: CLOUDFLARE_ACCOUNT_ID is required to list Workers.")]

        url = f"{CF_API_BASE}/accounts/{account_id}/workers/scripts"
        try:
            req = urllib.request.Request(url, headers=_headers())
            data_str = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
            data = json.loads(data_str)
            scripts = data.get("result", [])

            if not scripts:
                return [TextContent(type="text", text=f"No Cloudflare Workers found for account {account_id}")]

            out = [f"### Cloudflare Workers Scripts ({len(scripts)} found)\n"]
            for s in scripts:
                sid = s.get("id")
                created = s.get("created_on", "")[:10]
                mod = s.get("modified_on", "")[:10]
                routes = len(s.get("routes", []))
                out.append(f"- **`{sid}`**: Created {created} | Modified {mod} | {routes} active routes")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing Workers: {e}")]

    elif name == "cloudflare_dns_lookup":
        zone = arguments.get("zone_name_or_id", "").strip()
        rec_type = arguments.get("record_type", "ANY")

        # First find zone ID if name given
        try:
            zone_id = zone
            if "." in zone:
                z_url = f"{CF_API_BASE}/zones?name={urllib.parse.quote_plus(zone)}"
                req = urllib.request.Request(z_url, headers=_headers())
                z_res = json.loads(await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode()))
                z_list = z_res.get("result", [])
                if z_list:
                    zone_id = z_list[0].get("id")

            d_url = f"{CF_API_BASE}/zones/{zone_id}/dns_records"
            if rec_type != "ANY":
                d_url += f"?type={rec_type}"
            req = urllib.request.Request(d_url, headers=_headers())
            d_res = json.loads(await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode()))
            records = d_res.get("result", [])

            if not records:
                return [TextContent(type="text", text=f"No DNS records found for zone {zone}")]

            out = [f"### Cloudflare DNS Records for `{zone}` ({len(records)} records)\n"]
            for r in records[:20]:
                proxied = "🟧 Proxied" if r.get("proxied") else "⬜ DNS Only"
                out.append(f"- **{r.get('type')}** `{r.get('name')}` -> `{r.get('content')}` (TTL: {r.get('ttl')}, {proxied})")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error querying DNS: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

