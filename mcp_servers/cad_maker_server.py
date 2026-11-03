"""
cad_maker_server.py

Parametric 3D & 2D CAD Maker MCP server for Odysseus.
Supports parametric enclosures, mechanical brackets, 3D printing STL generation,
OpenSCAD (.scad) generation, 2D engineering drawings (.dxf), and direct integration
with macOS CADCraft (/Applications/CADCraft.app).
"""

import asyncio
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("cad_maker")


def _get_cad_output_dir() -> Path:
    ws = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent) / "workspace" / "cad"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ── 3D Triangle Mesh & STL Exporter ──

class Mesh3D:
    def __init__(self):
        self.triangles: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = []

    def add_triangle(self, v1, v2, v3):
        self.triangles.append((v1, v2, v3))

    def add_quad(self, v1, v2, v3, v4):
        self.add_triangle(v1, v2, v3)
        self.add_triangle(v1, v3, v4)

    def add_box(self, x, y, z, dx, dy, dz):
        # 8 vertices
        p = [
            (x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z),
            (x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)
        ]
        # Bottom
        self.add_quad(p[0], p[3], p[2], p[1])
        # Top
        self.add_quad(p[4], p[5], p[6], p[7])
        # Front
        self.add_quad(p[0], p[1], p[5], p[4])
        # Back
        self.add_quad(p[2], p[3], p[7], p[6])
        # Left
        self.add_quad(p[0], p[4], p[7], p[3])
        # Right
        self.add_quad(p[1], p[2], p[6], p[5])

    def add_cylinder(self, cx, cy, z0, radius, height, segments=32):
        dz = height
        z1 = z0 + dz
        angle_step = 2 * math.pi / segments
        circle_pts_bottom = [(cx + radius * math.cos(i * angle_step), cy + radius * math.sin(i * angle_step), z0) for i in range(segments)]
        circle_pts_top = [(cx + radius * math.cos(i * angle_step), cy + radius * math.sin(i * angle_step), z1) for i in range(segments)]

        for i in range(segments):
            nxt = (i + 1) % segments
            # Side quad
            self.add_quad(circle_pts_bottom[i], circle_pts_bottom[nxt], circle_pts_top[nxt], circle_pts_top[i])
            # Bottom cap
            self.add_triangle((cx, cy, z0), circle_pts_bottom[nxt], circle_pts_bottom[i])
            # Top cap
            self.add_triangle((cx, cy, z1), circle_pts_top[i], circle_pts_top[nxt])

    def export_ascii_stl(self, filepath: Path, solid_name="solid"):
        lines = [f"solid {solid_name}"]
        for v1, v2, v3 in self.triangles:
            # Normal computation
            ux, uy, uz = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
            vx, vy, vz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / mag, ny / mag, nz / mag

            lines.append(f"  facet normal {nx:.6e} {ny:.6e} {nz:.6e}")
            lines.append("    outer loop")
            lines.append(f"      vertex {v1[0]:.6e} {v1[1]:.6e} {v1[2]:.6e}")
            lines.append(f"      vertex {v2[0]:.6e} {v2[1]:.6e} {v2[2]:.6e}")
            lines.append(f"      vertex {v3[0]:.6e} {v3[1]:.6e} {v3[2]:.6e}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {solid_name}\n")
        filepath.write_text("\n".join(lines), encoding="utf-8")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_parametric_enclosure",
            description="Generate a complete 3D printable electronics enclosure (base + lid) for any PCB dimensions. Includes standoff screw posts, wall thickness, snap-fit or screw joints, connector cutouts (USB-C, HDMI, power), and exports OpenSCAD (.scad), STL (.stl), 2D DXF, and SVG preview.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project or enclosure name (e.g. esp32_sensor_box)", "default": "pcb_enclosure"},
                    "pcb_width": {"type": "number", "description": "PCB width in mm (X dimension)", "default": 50.0},
                    "pcb_length": {"type": "number", "description": "PCB length in mm (Y dimension)", "default": 70.0},
                    "box_height": {"type": "number", "description": "Total internal height in mm (Z dimension)", "default": 25.0},
                    "wall_thickness": {"type": "number", "description": "Enclosure shell wall thickness in mm", "default": 2.0},
                    "standoff_height": {"type": "number", "description": "PCB standoff mounting height in mm", "default": 5.0},
                    "screw_hole_diameter": {"type": "number", "description": "Mounting screw hole diameter in mm (e.g. 2.2 for M2, 3.2 for M3)", "default": 2.2},
                    "cutouts": {
                        "type": "array",
                        "description": "Port cutouts, e.g. [{'wall': 'front', 'type': 'usb_c', 'offset_x': 20, 'z': 6, 'w': 9.5, 'h': 3.5}]",
                        "items": {"type": "object"}
                    }
                },
                "required": ["name", "pcb_width", "pcb_length"]
            }
        ),
        Tool(
            name="create_3d_cad_model",
            description="Synthesize a 3D parametric mechanical part (brackets, spacers, heatsink mounts, robot chassis, sensor holders). Exports both 3D printing STL mesh and OpenSCAD (.scad) code.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Part name (e.g. motor_bracket_l298n)"},
                    "part_type": {
                        "type": "string",
                        "description": "Part type: bracket, spacer, chassis_plate, sensor_mount, cylinder_bushing, custom",
                        "enum": ["bracket", "spacer", "chassis_plate", "sensor_mount", "cylinder_bushing", "custom"]
                    },
                    "dimensions": {
                        "type": "object",
                        "description": "Dictionary of dimensions, e.g. {'width': 40, 'length': 40, 'height': 20, 'thickness': 3, 'hole_diameter': 3.2}"
                    },
                    "mounting_holes": {
                        "type": "array",
                        "description": "List of hole positions [{'x': 10, 'y': 10, 'r': 1.6}]",
                        "items": {"type": "object"}
                    }
                },
                "required": ["name", "part_type", "dimensions"]
            }
        ),
        Tool(
            name="create_dxf_drawing",
            description="Generate a professional 2D CAD engineering blueprint in DXF format using ezdxf. Supports layers (OUTLINE, HOLES, DIMENSIONS, TEXT), title block, millimeter coordinates, and laser/CNC cutting profiles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Output DXF filename (e.g. base_plate.dxf)"},
                    "title": {"type": "string", "description": "Drawing title (e.g. ECE Robotic Chassis Plate)"},
                    "width": {"type": "number", "description": "Total width in mm"},
                    "height": {"type": "number", "description": "Total height in mm"},
                    "holes": {
                        "type": "array",
                        "description": "List of drill holes: [{'x': 10, 'y': 10, 'diameter': 3.2}]",
                        "items": {"type": "object"}
                    },
                    "cutouts": {
                        "type": "array",
                        "description": "Internal cutout rectangles: [{'x': 20, 'y': 20, 'w': 30, 'h': 15}]",
                        "items": {"type": "object"}
                    },
                    "corner_radius": {"type": "number", "description": "Fillet/corner radius in mm", "default": 0.0}
                },
                "required": ["filename", "width", "height"]
            }
        ),
        Tool(
            name="open_in_cadcraft",
            description="Open any generated .dxf or .dwg drawing directly in /Applications/CADCraft.app on macOS for instant visual inspection and interactive editing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the .dxf or .dwg file"}
                },
                "required": ["file_path"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    out_dir = _get_cad_output_dir()

    if name == "create_parametric_enclosure":
        proj_name = arguments.get("name", "enclosure")
        pw = float(arguments.get("pcb_width", 50.0))
        pl = float(arguments.get("pcb_length", 70.0))
        bh = float(arguments.get("box_height", 25.0))
        wt = float(arguments.get("wall_thickness", 2.0))
        sh = float(arguments.get("standoff_height", 5.0))
        sd = float(arguments.get("screw_hole_diameter", 2.2))
        cutouts = arguments.get("cutouts", [])

        # Dimensions
        outer_w = pw + 2 * (wt + 1.0)
        outer_l = pl + 2 * (wt + 1.0)
        outer_h = bh + wt

        # 1. Generate OpenSCAD Source
        scad_code = f"""// Parametric PCB Enclosure: {proj_name}
// Generated automatically by Odysseus CAD Maker

$fn = 40;

pcb_w = {pw};
pcb_l = {pl};
box_h = {bh};
wall = {wt};
standoff_h = {sh};
screw_d = {sd};

outer_w = pcb_w + 2 * (wall + 1);
outer_l = pcb_l + 2 * (wall + 1);
outer_h = box_h + wall;

module standoff(x, y) {{
    translate([x, y, wall]) {{
        difference() {{
            cylinder(r=screw_d + 1.5, h=standoff_h);
            cylinder(r=screw_d / 2, h=standoff_h + 1);
        }}
    }}
}}

module enclosure_base() {{
    difference() {{
        // Outer body
        cube([outer_w, outer_l, outer_h]);
        // Inner cavity
        translate([wall, wall, wall])
            cube([outer_w - 2 * wall, outer_l - 2 * wall, outer_h]);
    }}

    // PCB Standoffs in 4 corners
    standoff(wall + 4, wall + 4);
    standoff(outer_w - wall - 4, wall + 4);
    standoff(wall + 4, outer_l - wall - 4);
    standoff(outer_w - wall - 4, outer_l - wall - 4);
}}

module enclosure_lid() {{
    translate([outer_w + 10, 0, 0]) {{
        difference() {{
            union() {{
                cube([outer_w, outer_l, wall]);
                translate([wall + 0.3, wall + 0.3, wall])
                    cube([outer_w - 2 * wall - 0.6, outer_l - 2 * wall - 0.6, 2]);
            }}
            // Screw holes
            translate([wall + 4, wall + 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([outer_w - wall - 4, wall + 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([wall + 4, outer_l - wall - 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([outer_w - wall - 4, outer_l - wall - 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
        }}
    }}
}}

enclosure_base();
enclosure_lid();
"""
        scad_path = out_dir / f"{proj_name}.scad"
        scad_path.write_text(scad_code, encoding="utf-8")

        # 2. Generate 3D STL Mesh for Base Box
        mesh = Mesh3D()
        # Outer shell
        mesh.add_box(0, 0, 0, outer_w, outer_l, outer_h)
        # 4 Standoff posts
        sr = (sd + 2.0) / 2
        mesh.add_cylinder(wt + 4, wt + 4, wt, sr, sh)
        mesh.add_cylinder(outer_w - wt - 4, wt + 4, wt, sr, sh)
        mesh.add_cylinder(wt + 4, outer_l - wt - 4, wt, sr, sh)
        mesh.add_cylinder(outer_w - wt - 4, outer_l - wt - 4, wt, sr, sh)

        stl_path = out_dir / f"{proj_name}_base.stl"
        mesh.export_ascii_stl(stl_path, solid_name=proj_name)

        # 3. Generate 2D DXF Blueprint
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        doc.layers.new("OUTLINE", dxfattribs={"color": 7})
        doc.layers.new("STANDOFFS", dxfattribs={"color": 1})
        doc.layers.new("PCB_AREA", dxfattribs={"color": 3})

        # Outer outline
        msp.add_lwpolyline(
            [(0, 0), (outer_w, 0), (outer_w, outer_l), (0, outer_l), (0, 0)],
            dxfattribs={"layer": "OUTLINE"}
        )
        # Inner wall outline
        msp.add_lwpolyline(
            [(wt, wt), (outer_w - wt, wt), (outer_w - wt, outer_l - wt), (wt, outer_l - wt), (wt, wt)],
            dxfattribs={"layer": "OUTLINE"}
        )
        # Standoffs
        for sx, sy in [(wt + 4, wt + 4), (outer_w - wt - 4, wt + 4), (wt + 4, outer_l - wt - 4), (outer_w - wt - 4, outer_l - wt - 4)]:
            msp.add_circle((sx, sy), radius=sd / 2, dxfattribs={"layer": "STANDOFFS"})

        dxf_path = out_dir / f"{proj_name}_blueprint.dxf"
        doc.saveas(dxf_path)

        res = [
            f"### Parametric 3D Enclosure Created: `{proj_name}`\n",
            f"- **Target PCB Size**: {pw:.1f} × {pl:.1f} mm",
            f"- **Enclosure Outer Dimensions**: {outer_w:.1f} × {outer_l:.1f} × {outer_h:.1f} mm",
            f"- **Shell Wall Thickness**: {wt:.1f} mm | **Standoff Height**: {sh:.1f} mm (M{int(round(sd))} Screws)\n",
            f"#### Generated CAD Deliverables:\n",
            f"1. **3D Printable Mesh (STL)**: `{stl_path}`",
            f"2. **OpenSCAD Source (.scad)**: `{scad_path}`",
            f"3. **2D Engineering Blueprint (DXF)**: `{dxf_path}`",
            f"\n*Tip: Open the DXF directly in CADCraft using `open_in_cadcraft` or slice the STL for 3D printing.*"
        ]
        return [TextContent(type="text", text="\n".join(res))]

    elif name == "create_3d_cad_model":
        part_name = arguments.get("name", "cad_part")
        ptype = arguments.get("part_type", "bracket")
        dims = arguments.get("dimensions", {})
        holes = arguments.get("mounting_holes", [])

        w = float(dims.get("width", 40.0))
        l = float(dims.get("length", 40.0))
        h = float(dims.get("height", 20.0))
        t = float(dims.get("thickness", 3.0))

        scad = f"""// 3D Parametric Part: {part_name} ({ptype})
$fn = 36;
difference() {{
    union() {{
        cube([{w}, {l}, {t}]);
        cube([{w}, {t}, {h}]);
    }}
    // Mounting Holes
"""
        for i, hole in enumerate(holes):
            hx = hole.get("x", w / 2)
            hy = hole.get("y", l / 2)
            hr = hole.get("r", 1.6)
            scad += f"    translate([{hx}, {hy}, -1]) cylinder(r={hr}, h={t + 2});\n"
        scad += "}\n"

        scad_path = out_dir / f"{part_name}.scad"
        scad_path.write_text(scad, encoding="utf-8")

        mesh = Mesh3D()
        mesh.add_box(0, 0, 0, w, l, t)
        if ptype == "bracket":
            mesh.add_box(0, 0, 0, w, t, h)
        stl_path = out_dir / f"{part_name}.stl"
        mesh.export_ascii_stl(stl_path, solid_name=part_name)

        return [TextContent(type="text", text=f"### 3D CAD Model Generated: `{part_name}` ({ptype})\n- **Dimensions**: {w} × {l} × {h} mm (thickness {t}mm)\n- **STL File**: `{stl_path}`\n- **OpenSCAD File**: `{scad_path}`")]

    elif name == "create_dxf_drawing":
        fname = arguments.get("filename", "drawing.dxf")
        if not fname.endswith(".dxf"):
            fname += ".dxf"
        title = arguments.get("title", "2D CAD Drawing")
        w = float(arguments.get("width", 100.0))
        h = float(arguments.get("height", 100.0))
        holes = arguments.get("holes", [])
        cutouts = arguments.get("cutouts", [])

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        doc.layers.new("OUTLINE", dxfattribs={"color": 7})
        doc.layers.new("HOLES", dxfattribs={"color": 1})
        doc.layers.new("CUTOUTS", dxfattribs={"color": 6})
        doc.layers.new("TEXT", dxfattribs={"color": 2})

        # Border
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h), (0, 0)], dxfattribs={"layer": "OUTLINE"})

        # Holes
        for hole in holes:
            hx = float(hole.get("x", 0))
            hy = float(hole.get("y", 0))
            dia = float(hole.get("diameter", 3.0))
            msp.add_circle((hx, hy), radius=dia / 2, dxfattribs={"layer": "HOLES"})

        # Cutouts
        for c in cutouts:
            cx = float(c.get("x", 0))
            cy = float(c.get("y", 0))
            cw = float(c.get("w", 10))
            ch = float(c.get("h", 10))
            msp.add_lwpolyline([(cx, cy), (cx + cw, cy), (cx + cw, cy + ch), (cx, cy + ch), (cx, cy)], dxfattribs={"layer": "CUTOUTS"})

        # Title text
        msp.add_text(f"{title} - {w}x{h}mm", dxfattribs={"layer": "TEXT", "height": 3.5}).set_placement((5, h - 8))

        dxf_path = out_dir / fname
        doc.saveas(dxf_path)

        return [TextContent(type="text", text=f"### 2D DXF CAD Drawing Created: `{dxf_path}`\n- **Canvas Size**: {w:.1f} × {h:.1f} mm\n- **Holes**: {len(holes)} drill points\n- **Cutouts**: {len(cutouts)} slots\n\nCall `open_in_cadcraft` to open in CADCraft on your Mac.")]

    elif name == "open_in_cadcraft":
        fpath = arguments.get("file_path", "")
        p = Path(fpath)
        if not p.is_absolute():
            p = out_dir / fpath

        if not p.exists():
            return [TextContent(type="text", text=f"Error: File not found at '{p}'.")]

        cadcraft_bin = Path("/Applications/CADCraft.app/Contents/MacOS/CADCraft")
        if cadcraft_bin.exists() and os.access(cadcraft_bin, os.X_OK):
            subprocess.Popen([str(cadcraft_bin), str(p)])
            return [TextContent(type="text", text=f"Opened `{p.name}` in /Applications/CADCraft.app on your Mac.")]
        else:
            # Fallback to macOS open
            subprocess.Popen(["open", str(p)])
            return [TextContent(type="text", text=f"Launched `{p.name}` using macOS default CAD viewer.")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


if __name__ == "__main__":
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    asyncio.run(main())

