"""
ece_inventory_server.py

MCP server providing direct access to local electronics lab component inventory
(Homebox database and ECE CSV specs).
Allows searching parts, retrieving pinouts/specs/datasheets, and scrubbing BOMs.
"""

import asyncio
import csv
import re
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("ece_inventory")

# Candidates for Homebox directory
HOMEBOX_DIR_CANDIDATES = [
    Path("/app/workspace/Homebox"),
    Path("/Users/shamit/Documents/Docker/Homebox"),
    Path(__file__).resolve().parent.parent.parent / "Homebox",
]


def _find_homebox_dir() -> Optional[Path]:
    for cand in HOMEBOX_DIR_CANDIDATES:
        if cand.is_dir():
            return cand
    return None


# Reference designators (R1, C12, U3, SW2, LED1...) and quantities (2x, x4,
# qty:3) never appear in inventory text, so they'd make every BOM line miss.
_BOM_NOISE_TOKEN = re.compile(
    r"^(?:(?:r|c|l|u|d|q|j|p|sw|led|tp|y|x|f|k|fb|bt|ic|t)\d+[:,]?|\d+x|x\d+|qty:?\d*)$"
)


def _load_all_components() -> List[Dict[str, Any]]:
    """Loads components from Homebox SQLite DB and/or ECE CSV import files."""
    components = []
    seen_refs = set()
    hb_dir = _find_homebox_dir()
    if not hb_dir:
        return components

    # 1. Load from CSV files in Homebox dir (e.g. ece_components_sample_import.csv)
    for csv_file in sorted(hb_dir.glob("*.csv")):
        try:
            with open(csv_file, mode="r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ref = row.get("HB.import_ref", "").strip()
                    name = row.get("HB.name", "").strip()
                    if not name and not ref:
                        continue
                    if ref and ref in seen_refs:
                        continue
                    if ref:
                        seen_refs.add(ref)

                    try:
                        qty = float(row.get("HB.quantity", 0) or 0)
                    except ValueError:
                        qty = 0

                    components.append({
                        "import_ref": ref or name,
                        "name": name,
                        "description": row.get("HB.description", "").strip(),
                        "location": row.get("HB.location", "").strip(),
                        "tags": [t.strip() for t in row.get("HB.tags", "").split(",") if t.strip()],
                        "quantity": qty,
                        "manufacturer": row.get("HB.manufacturer", "").strip(),
                        "model_number": row.get("HB.model_number", "").strip(),
                        "notes": row.get("HB.notes", "").strip(),
                        "value": row.get("HB.field.Value", "").strip(),
                        "package": row.get("HB.field.Package", "").strip(),
                        "voltage_rating": row.get("HB.field.Voltage_Rating", "").strip(),
                        "tolerance": row.get("HB.field.Tolerance", "").strip(),
                        "datasheet_url": row.get("HB.field.Datasheet_URL", "").strip(),
                        "supplier_part_no": row.get("HB.field.Supplier_Part_No", "").strip(),
                        "source": csv_file.name,
                    })
        except Exception:
            pass

    # 2. Load from Homebox SQLite database
    db_path = hb_dir / "data" / "homebox.db"
    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, description, notes, quantity, model_number, manufacturer, import_ref
                FROM entities
                WHERE archived = 0 OR archived IS NULL
            """)
            for row in cur.fetchall():
                ref = row["import_ref"] or row["id"]
                if ref in seen_refs:
                    continue
                seen_refs.add(ref)
                components.append({
                    "import_ref": ref,
                    "name": row["name"] or "",
                    "description": row["description"] or "",
                    "location": "Homebox Storage",
                    "tags": [],
                    "quantity": float(row["quantity"] or 0),
                    "manufacturer": row["manufacturer"] or "",
                    "model_number": row["model_number"] or "",
                    "notes": row["notes"] or "",
                    "value": "",
                    "package": "",
                    "voltage_rating": "",
                    "tolerance": "",
                    "datasheet_url": "",
                    "supplier_part_no": "",
                    "source": "homebox.db",
                })
            conn.close()
        except Exception:
            pass

    return components


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_components",
            description="Search local ECE lab components (passives, ICs, sensors, MCUs, connectors) by name, value, package, or description. Returns stock and drawer locations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Component search term (e.g. '10k', '0805', 'BME280', 'MOSFET', 'LDO 3.3V', 'ESP32')",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g. 'Resistor', 'Capacitor', 'Diode', 'Transistor', 'Sensor', 'Microcontroller')",
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "Only return items with quantity > 0 (default: true)",
                        "default": True,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_component_specs",
            description="Get full technical specifications, pinout notes, datasheet URL, and storage location for a specific component reference or exact part name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Component import ref (e.g. 'ECE-RES-0805-10K') or component name",
                    }
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="scrub_bom",
            description="Scrub a Bill of Materials (BOM) against local lab inventory. Identifies components in stock, drawer locations, and missing parts to order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "bom_text": {
                        "type": "string",
                        "description": "BOM text or list of components (e.g. '10k 0805, 100nF 0805, BME280, ESP32-WROOM-32')",
                    }
                },
                "required": ["bom_text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    components = _load_all_components()

    if name == "search_components":
        query = (arguments.get("query") or "").lower().strip()
        category = (arguments.get("category") or "").lower().strip()
        in_stock = arguments.get("in_stock_only", True)

        matches = []
        for c in components:
            if in_stock and c["quantity"] <= 0:
                continue

            searchable = " ".join([
                c["import_ref"],
                c["name"],
                c["description"],
                c["model_number"],
                c["manufacturer"],
                c["value"],
                c["package"],
                " ".join(c["tags"]),
            ]).lower()

            if query and query not in searchable:
                # Also check sub-tokens
                tokens = query.split()
                if not all(t in searchable for t in tokens):
                    continue

            if category and not any(category in t.lower() for t in c["tags"]) and category not in searchable:
                continue

            matches.append(c)

        if not matches:
            return [TextContent(type="text", text=f"No components found matching '{query}'. Total items in inventory: {len(components)}")]

        out = [f"Found {len(matches)} matching component(s):\n"]
        for m in matches[:25]:
            val_pkg = f" ({m['value'] or 'N/A'}, {m['package'] or 'N/A'})" if (m['value'] or m['package']) else ""
            out.append(
                f"- **{m['name']}**{val_pkg}\n"
                f"  - Ref: `{m['import_ref']}` | Qty: {int(m['quantity'])} in stock\n"
                f"  - Location: `{m['location']}`\n"
                f"  - MPN: {m['model_number'] or 'N/A'} ({m['manufacturer'] or 'Generic'})"
            )
        return [TextContent(type="text", text="\n".join(out))]

    elif name == "get_component_specs":
        target = (arguments.get("identifier") or "").lower().strip()
        found = None
        for c in components:
            if c["import_ref"].lower() == target or c["name"].lower() == target:
                found = c
                break
        if not found:
            for c in components:
                if target in c["import_ref"].lower() or target in c["name"].lower():
                    found = c
                    break

        if not found:
            return [TextContent(type="text", text=f"Component '{target}' not found in inventory.")]

        details = [
            f"# {found['name']}",
            f"- **Import Ref**: `{found['import_ref']}`",
            f"- **Stock Quantity**: {int(found['quantity'])}",
            f"- **Physical Location**: {found['location']}",
            f"- **Value**: {found['value'] or 'N/A'}",
            f"- **Package / Footprint**: {found['package'] or 'N/A'}",
            f"- **Voltage / Current Rating**: {found['voltage_rating'] or 'N/A'}",
            f"- **Tolerance**: {found['tolerance'] or 'N/A'}",
            f"- **Manufacturer**: {found['manufacturer'] or 'N/A'}",
            f"- **Manufacturer Part No (MPN)**: {found['model_number'] or 'N/A'}",
            f"- **Supplier Part No (SKU)**: {found['supplier_part_no'] or 'N/A'}",
            f"- **Datasheet URL**: {found['datasheet_url'] or 'N/A'}",
            f"- **Notes / Pinout**: {found['notes'] or 'None'}",
            f"- **Tags**: {', '.join(found['tags']) if found['tags'] else 'None'}",
        ]
        return [TextContent(type="text", text="\n".join(details))]

    elif name == "scrub_bom":
        bom_text = arguments.get("bom_text", "")
        raw_lines = [l.strip() for l in bom_text.splitlines() if l.strip()]
        lines = []
        for rl in raw_lines:
            if "," in rl and not rl.startswith("HB."):
                lines.extend([p.strip() for p in rl.split(",") if p.strip()])
            else:
                lines.append(rl)

        matched_report = []
        missing_report = []

        for item in lines:
            item_lower = item.lower()
            tokens = [
                t for t in item_lower.replace("-", " ").replace("_", " ").split()
                if not _BOM_NOISE_TOKEN.match(t)
            ]
            best_match = None
            if not tokens:
                missing_report.append(f"❌ **{item}** (No part details to match)")
                continue

            for c in components:
                searchable = " ".join([c["name"], c["value"], c["package"], c["model_number"]]).lower()
                if all(tok in searchable for tok in tokens):
                    best_match = c
                    break

            if best_match:
                matched_report.append(
                    f"✔ **{item}** -> `{best_match['name']}` ({best_match['package']})\n"
                    f"   Location: `{best_match['location']}` | In Stock: {int(best_match['quantity'])}"
                )
            else:
                missing_report.append(f"❌ **{item}** (Not found in lab stock - order needed)")

        result = ["### BOM Scrubbing Report\n"]
        if matched_report:
            result.append("#### Available in Lab Stock:")
            result.extend(matched_report)
            result.append("")
        if missing_report:
            result.append("#### Missing from Lab Stock (Order Required):")
            result.extend(missing_report)

        return [TextContent(type="text", text="\n".join(result))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
