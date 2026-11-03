"""
kicad_eda_server.py

MCP server providing KiCad schematic/PCB inspection and JLCPCB/LCSC part lookup
for electronics and PCB design workflows.
"""

import asyncio
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("kicad_eda")

# Common JLCPCB Basic Parts & Standard SMD Reference Catalog
# Basic parts have $0 reel loading fee at JLCPCB SMT assembly!
JLCPCB_POPULAR_PARTS = [
    {"lcsc": "C17513", "type": "Basic", "mpn": "RC0805FR-0710KL", "val": "10k", "pkg": "0805", "desc": "10kΩ 1% 1/8W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C17514", "type": "Basic", "mpn": "RC0805FR-071KL", "val": "1k", "pkg": "0805", "desc": "1kΩ 1% 1/8W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C17673", "type": "Basic", "mpn": "RC0805FR-074K7L", "val": "4.7k", "pkg": "0805", "desc": "4.7kΩ 1% 1/8W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C17710", "type": "Basic", "mpn": "RC0805FR-07100RL", "val": "100R", "pkg": "0805", "desc": "100Ω 1% 1/8W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C25804", "type": "Basic", "mpn": "RC0603FR-0710KL", "val": "10k", "pkg": "0603", "desc": "10kΩ 1% 1/10W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C22775", "type": "Basic", "mpn": "RC0603FR-071KL", "val": "1k", "pkg": "0603", "desc": "1kΩ 1% 1/10W Chip Resistor", "mfr": "Yageo"},
    {"lcsc": "C49678", "type": "Basic", "mpn": "CL21B104KBCNNNC", "val": "100nF", "pkg": "0805", "desc": "100nF (0.1µF) 50V X7R Ceramic Cap", "mfr": "Samsung"},
    {"lcsc": "C15850", "type": "Basic", "mpn": "CL21A106KOQNNNE", "val": "10uF", "pkg": "0805", "desc": "10µF 16V X5R Ceramic Cap", "mfr": "Samsung"},
    {"lcsc": "C14663", "type": "Basic", "mpn": "CL10B104KB8NNNC", "val": "100nF", "pkg": "0603", "desc": "100nF 50V X7R Ceramic Cap", "mfr": "Samsung"},
    {"lcsc": "C15849", "type": "Basic", "mpn": "CL10A106MQ8NNNC", "val": "10uF", "pkg": "0603", "desc": "10µF 6.3V X5R Ceramic Cap", "mfr": "Samsung"},
    {"lcsc": "C8678",  "type": "Basic", "mpn": "1N4148WS", "val": "100V 300mA", "pkg": "SOD-323", "desc": "Fast Switching Diode 4ns", "mfr": "JCET"},
    {"lcsc": "C8648",  "type": "Basic", "mpn": "SS34", "val": "3A 40V", "pkg": "SMA", "desc": "Schottky Barrier Diode VF=0.5V", "mfr": "MDD"},
    {"lcsc": "C8405",  "type": "Basic", "mpn": "BSS138", "val": "50V 220mA", "pkg": "SOT-23", "desc": "N-Channel 50V Logic-level MOSFET", "mfr": "ON Semi"},
    {"lcsc": "C20917", "type": "Basic", "mpn": "AO3400A", "val": "30V 5.7A", "pkg": "SOT-23", "desc": "N-Channel Power MOSFET RDS=28mΩ", "mfr": "AOS"},
    {"lcsc": "C20918", "type": "Basic", "mpn": "AO3401A", "val": "-30V -4.0A", "pkg": "SOT-23", "desc": "P-Channel Power MOSFET RDS=44mΩ", "mfr": "AOS"},
    {"lcsc": "C6186",  "type": "Basic", "mpn": "AMS1117-3.3", "val": "3.3V 1A", "pkg": "SOT-223", "desc": "LDO Linear Voltage Regulator 3.3V", "mfr": "Advanced Monolithic"},
    {"lcsc": "C8481",  "type": "Basic", "mpn": "AMS1117-5.0", "val": "5.0V 1A", "pkg": "SOT-223", "desc": "LDO Linear Voltage Regulator 5.0V", "mfr": "Advanced Monolithic"},
    {"lcsc": "C6187",  "type": "Basic", "mpn": "AMS1117-ADJ", "val": "Adjustable", "pkg": "SOT-223", "desc": "LDO Linear Voltage Regulator ADJ", "mfr": "Advanced Monolithic"},
    {"lcsc": "C84683", "type": "Preferred", "mpn": "CH340C", "val": "USB-UART", "pkg": "SOIC-16", "desc": "USB to Serial UART with built-in crystal", "mfr": "WCH"},
    {"lcsc": "C14256", "type": "Preferred", "mpn": "ESP32-WROOM-32E", "val": "ESP32 4MB", "pkg": "SMD Module", "desc": "Wi-Fi & BLE Dual-core 240MHz MCU", "mfr": "Espressif"},
    {"lcsc": "C2040",  "type": "Preferred", "mpn": "RP2040", "val": "Dual M0+ 133MHz", "pkg": "QFN-56", "desc": "Raspberry Pi RP2040 Microcontroller", "mfr": "Raspberry Pi"},
    {"lcsc": "C92490", "type": "Preferred", "mpn": "BME280", "val": "I2C/SPI", "pkg": "LGA-8", "desc": "Digital Humidity, Pressure and Temp Sensor", "mfr": "Bosch"},
    {"lcsc": "C24112", "type": "Preferred", "mpn": "MPU-6050", "val": "6-DOF IMU", "pkg": "QFN-24", "desc": "3-Axis Gyroscope and 3-Axis Accelerometer", "mfr": "TDK InvenSense"},
]


def _resolve_workspace_path(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute() and p.exists():
        return p
    # Search under workspace
    workspaces = [Path("/app/workspace"), Path("/Users/shamit/Documents/Docker"), Path.cwd()]
    for ws in workspaces:
        cand = ws / file_path.lstrip("/")
        if cand.exists():
            return cand
    return p


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="inspect_kicad_schematic",
            description="Parse a KiCad schematic (.kicad_sch) file, extract symbols, references, values, footprints, and generate an organized Bill of Materials (BOM).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .kicad_sch file (absolute or relative to workspace)",
                    }
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="inspect_kicad_pcb",
            description="Inspect a KiCad PCB layout (.kicad_pcb) file, extract layer setup, placed footprints count, trace count, via count, and board dimensions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .kicad_pcb file (absolute or relative to workspace)",
                    }
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="search_lcsc_part",
            description="Search JLCPCB and LCSC component catalog for SMD components, Basic/Preferred parts status (for $0 SMT setup fees), and matching footprints.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Component or value to search (e.g. '10k', '0805', 'SS34', 'AMS1117', 'CH340', 'MOSFET', '100nF')",
                    },
                    "package": {
                        "type": "string",
                        "description": "Optional package filter (e.g. '0805', '0603', 'SOT-23', 'SOIC-16')",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "inspect_kicad_schematic":
        raw_path = arguments.get("file_path", "")
        path = _resolve_workspace_path(raw_path)
        if not path.is_file():
            return [TextContent(type="text", text=f"Error: Schematic file not found: {raw_path}")]

        content = path.read_text(encoding="utf-8", errors="ignore")
        # Extract symbols: (symbol (lib_id "...") ... (property "Reference" "R1") ... (property "Value" "10k") ... (property "Footprint" "..."))
        symbol_blocks = re.findall(r"\(symbol\s+[\"']?([^\s\"\')]+)[\"']?\s+([\s\S]*?\n\s*\))", content)

        components = []
        for lib_id, block in symbol_blocks:
            ref_m = re.search(r'\(property\s+["\']Reference["\']\s+["\']([^"\']+)["\']', block)
            val_m = re.search(r'\(property\s+["\']Value["\']\s+["\']([^"\']+)["\']', block)
            fp_m = re.search(r'\(property\s+["\']Footprint["\']\s+["\']([^"\']*)["\']', block)

            ref = ref_m.group(1) if ref_m else "Unknown"
            val = val_m.group(1) if val_m else "Unknown"
            fp = fp_m.group(1) if fp_m else "Unassigned"

            # Skip power symbols like #PWR, GND, VCC
            if ref.startswith("#") or "power:" in lib_id.lower():
                continue

            components.append({
                "ref": ref,
                "value": val,
                "footprint": fp,
                "lib": lib_id,
            })

        if not components:
            return [TextContent(type="text", text=f"Schematic read successfully, but no discrete component symbols found in {path.name}.")]

        # Group components for BOM
        bom_groups: Dict[tuple, List[str]] = {}
        for c in components:
            key = (c["value"], c["footprint"])
            bom_groups.setdefault(key, []).append(c["ref"])

        out = [
            f"# KiCad Schematic Inspection: {path.name}",
            f"- Total Components: {len(components)}",
            f"- Unique Part Types: {len(bom_groups)}\n",
            "### Bill of Materials (BOM):\n",
            "| Item | Value | Footprint | Qty | Designators |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        idx = 1
        for (val, fp), refs in sorted(bom_groups.items(), key=lambda x: len(x[1]), reverse=True):
            fp_clean = fp.split(":")[-1] if ":" in fp else fp
            refs_str = ", ".join(sorted(refs))
            out.append(f"| {idx} | {val} | {fp_clean or '⚠️ Unassigned'} | {len(refs)} | {refs_str} |")
            idx += 1

        unassigned = [c["ref"] for c in components if not c["footprint"] or c["footprint"] == "Unassigned"]
        if unassigned:
            out.append(f"\n⚠️ **Warning: {len(unassigned)} components have unassigned footprints:** {', '.join(unassigned)}")

        return [TextContent(type="text", text="\n".join(out))]

    elif name == "inspect_kicad_pcb":
        raw_path = arguments.get("file_path", "")
        path = _resolve_workspace_path(raw_path)
        if not path.is_file():
            return [TextContent(type="text", text=f"Error: PCB layout file not found: {raw_path}")]

        content = path.read_text(encoding="utf-8", errors="ignore")

        # Counts
        footprints = re.findall(r"\(footprint\s+[\"']?([^\s\"\')]+)[\"']?", content)
        vias = re.findall(r"\(via\b", content)
        segments = re.findall(r"\(segment\b", content)
        nets = set(re.findall(r'\(net\s+\d+\s+["\']([^"\']+)["\']', content))

        # Check layers
        layers_block = re.search(r"\(layers\s+([\s\S]*?\n\s*\))", content)
        layers = []
        if layers_block:
            layers = re.findall(r'\(\d+\s+["\']?([^"\']+)["\']?\s+signal', layers_block.group(1))

        out = [
            f"# KiCad PCB Layout Inspection: {path.name}",
            f"- **Placed Footprints / Modules**: {len(footprints)}",
            f"- **Signal Layers**: {len(layers)} ({', '.join(layers) if layers else 'Standard 2-Layer'})",
            f"- **Traces / Segments**: {len(segments)}",
            f"- **Vias**: {len(vias)}",
            f"- **Nets**: {len(nets)}",
        ]
        return [TextContent(type="text", text="\n".join(out))]

    elif name == "search_lcsc_part":
        query = (arguments.get("query") or "").lower().strip()
        pkg_filter = (arguments.get("package") or "").lower().strip()

        matches = []
        for part in JLCPCB_POPULAR_PARTS:
            searchable = f"{part['lcsc']} {part['mpn']} {part['val']} {part['pkg']} {part['desc']} {part['mfr']}".lower()
            if query and query not in searchable:
                tokens = query.split()
                if not all(t in searchable for t in tokens):
                    continue
            if pkg_filter and pkg_filter not in part["pkg"].lower():
                continue
            matches.append(part)

        if not matches:
            return [TextContent(type="text", text=f"No matching JLCPCB/LCSC parts found in basic catalog for query '{query}'.")]

        out = [
            f"### JLCPCB / LCSC Parts Found ({len(matches)} match(es)):\n",
            "| LCSC Part # | MPN / Value | Type | Package | Description | Manufacturer |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for m in matches:
            type_tag = f"🟢 **{m['type']}** ($0 SMT Setup)" if m["type"] == "Basic" else f"🔵 {m['type']}"
            out.append(f"| [{m['lcsc']}](https://www.lcsc.com/product-detail/{m['lcsc']}.html) | **{m['mpn']}** ({m['val']}) | {type_tag} | `{m['pkg']}` | {m['desc']} | {m['mfr']} |")

        return [TextContent(type="text", text="\n".join(out))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
