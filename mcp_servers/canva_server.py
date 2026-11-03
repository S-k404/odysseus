"""
canva_server.py

MCP server providing Canva design format specs, template archetypes,
color palette harmonic generation, and layout guidelines for visual media.
"""

import asyncio
import colorsys
import json
import urllib.parse
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("canva_design")

FORMAT_SPECS = {
    "instagram_post": {"w": 1080, "h": 1080, "ratio": "1:1", "desc": "Square Feed Post"},
    "instagram_story": {"w": 1080, "h": 1920, "ratio": "9:16", "desc": "Vertical Fullscreen Story/Reel"},
    "youtube_thumbnail": {"w": 1280, "h": 720, "ratio": "16:9", "desc": "Standard HD Video Thumbnail"},
    "presentation_16_9": {"w": 1920, "h": 1080, "ratio": "16:9", "desc": "Slide Deck / Keynote presentation"},
    "linkedin_banner": {"w": 1584, "h": 396, "ratio": "4:1", "desc": "LinkedIn Profile Header"},
    "twitter_header": {"w": 1500, "h": 500, "ratio": "3:1", "desc": "X / Twitter Banner"},
    "a4_document": {"w": 2480, "h": 3508, "ratio": "1:1.414", "desc": "A4 Print at 300 DPI"},
    "us_letter": {"w": 2550, "h": 3300, "ratio": "8.5:11", "desc": "US Letter Print at 300 DPI"},
    "infographic": {"w": 800, "h": 2000, "ratio": "1:2.5", "desc": "Long vertical infographic layout"},
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="canva_get_format_specs",
            description="Retrieve standard pixel dimensions, aspect ratio, safe zones, and print guidelines for graphic designs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "format_type": {
                        "type": "string",
                        "description": "Design format (e.g. 'instagram_post', 'youtube_thumbnail', 'presentation_16_9', 'all')",
                        "default": "all",
                    }
                },
            },
        ),
        Tool(
            name="canva_generate_color_palette",
            description="Generate harmonic color palettes (complementary, triadic, analogous, monochromatic) with HEX codes and usage recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_hex": {
                        "type": "string",
                        "description": "Starting brand color in HEX format (e.g. '#3b82f6', '#d97757')",
                    },
                    "harmony": {
                        "type": "string",
                        "enum": ["complementary", "analogous", "triadic", "split_complementary", "monochromatic"],
                        "default": "complementary",
                    },
                },
                "required": ["base_hex"],
            },
        ),
        Tool(
            name="canva_suggest_layout",
            description="Suggest design layout structure, typography pairings, and element hierarchy for a specific topic or theme.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Subject of the design (e.g. 'AI conference banner', 'Coffee shop menu', 'Tech product launch')"},
                    "format": {"type": "string", "description": "Target format (e.g. 'presentation', 'social', 'poster')"},
                },
                "required": ["topic"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "canva_get_format_specs":
        fmt = (arguments.get("format_type") or "all").lower().strip()
        if fmt in FORMAT_SPECS:
            s = FORMAT_SPECS[fmt]
            return [TextContent(type="text", text=f"### Canva Format Spec: `{fmt}`\n- **Description**: {s['desc']}\n- **Resolution**: {s['w']} x {s['h']} px\n- **Aspect Ratio**: {s['ratio']}\n- **Canva URL**: https://www.canva.com/create/")]

        out = ["### Standard Canva Graphic Design Specifications\n"]
        for k, v in FORMAT_SPECS.items():
            out.append(f"- **`{k}`**: {v['w']}x{v['h']}px ({v['ratio']}) — *{v['desc']}*")
        return [TextContent(type="text", text="\n".join(out))]

    elif name == "canva_generate_color_palette":
        hex_val = arguments.get("base_hex", "#3b82f6").lstrip("#")
        harmony = arguments.get("harmony", "complementary")
        try:
            r = int(hex_val[0:2], 16) / 255.0
            g = int(hex_val[2:4], 16) / 255.0
            b = int(hex_val[4:6], 16) / 255.0
        except Exception:
            r, g, b = 0.23, 0.51, 0.96

        h, s, v = colorsys.rgb_to_hsv(r, g, b)

        def to_hex(h_val, s_val, v_val):
            cr, cg, cb = colorsys.hsv_to_rgb(h_val % 1.0, max(0.0, min(1.0, s_val)), max(0.0, min(1.0, v_val)))
            return f"#{int(cr*255):02x}{int(cg*255):02x}{int(cb*255):02x}".upper()

        palette = [f"#{hex_val.upper()} (Base Primary)"]
        if harmony == "complementary":
            palette.append(f"{to_hex(h + 0.5, s, v)} (Accent / High Contrast)")
            palette.append(f"{to_hex(h, s * 0.4, min(1.0, v * 1.2))} (Tint Background)")
            palette.append(f"{to_hex(h + 0.5, s * 0.3, 0.2)} (Deep Text/Border)")
        elif harmony == "triadic":
            palette.append(f"{to_hex(h + 1/3, s, v)} (Secondary Triad)")
            palette.append(f"{to_hex(h + 2/3, s, v)} (Tertiary Triad)")
            palette.append(f"{to_hex(h, s * 0.15, 0.95)} (Neutral Surface)")
        else: # analogous
            palette.append(f"{to_hex(h - 0.08, s, v)} (Warm Analogous)")
            palette.append(f"{to_hex(h + 0.08, s, v)} (Cool Analogous)")
            palette.append(f"{to_hex(h, s * 0.2, 0.98)} (Background Canvas)")

        out = [f"### Canva Harmonic Palette ({harmony.capitalize()})\n"]
        for p in palette:
            out.append(f"- **{p}**")
        return [TextContent(type="text", text="\n".join(out))]

    elif name == "canva_suggest_layout":
        topic = arguments.get("topic", "")
        fmt = arguments.get("format", "presentation")
        out = [
            f"### Design Blueprint: {topic} ({fmt.capitalize()})\n",
            "#### 1. Visual Hierarchy & Composition",
            "- **Focal Point**: Bold high-contrast hero element occupying top-left to center-right.",
            "- **Rule of Thirds**: Position the primary headline along the upper third baseline.",
            "- **White Space**: Maintain at least 15% clear margin on all edges.",
            "\n#### 2. Typography Strategy",
            "- **Header Font**: Montserrat Bold / Syne / Space Grotesk (700-800 weight, 48-64pt)",
            "- **Body Font**: Inter / Plus Jakarta Sans (400-500 weight, 16-18pt, 1.5 line height)",
            "- **Accent / Kicker**: Monospace badge or uppercase pill label (12pt, tracking +2px)",
            "\n#### 3. Canva Implementation Steps",
            "1. Open Canva and select the template canvas matching target dimensions.",
            "2. Establish background grid (3 columns or 12-column fluid).",
            "3. Place headline, subheader, and call-to-action button with consistent corner radius (8px/12px).",
            "4. Export as PNG (digital) or PDF Print with CMYK & bleed (print).",
        ]
        return [TextContent(type="text", text="\n".join(out))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

