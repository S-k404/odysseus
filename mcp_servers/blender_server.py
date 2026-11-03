"""
blender_server.py

MCP server for Blender 3D integration in Odysseus.
Connects with local Blender (installed in /Applications/Blender.app) or the
official Blender MCP package, allowing inspection of scene hierarchy, running
Python automation, creating objects, and rendering thumbnails/viewports.
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("blender_3d")

BLENDER_APP_PATHS = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
]

BLMCP_VENV = os.path.expanduser(
    "~/Library/Application Support/Claude/Claude Extensions/ant.dir.gh.blender.blender-mcp/.venv/bin/python"
)


def _find_blender_binary() -> Optional[str]:
    for path in BLENDER_APP_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    import shutil
    return shutil.which("blender")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="blender_get_info",
            description="Get installed Blender version, status, and system capabilities.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="blender_execute_code",
            description="Execute Python code inside Blender to inspect scenes, create meshes, manipulate materials, or automate operations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute inside Blender environment (has full access to `bpy`).",
                    },
                    "blend_file": {
                        "type": "string",
                        "description": "Optional path to a .blend file to load before running code.",
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="blender_get_scene_summary",
            description="List all collections, objects, meshes, cameras, lights, and materials in the active or specified .blend file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blend_file": {
                        "type": "string",
                        "description": "Optional path to a .blend file. If omitted, checks default scene.",
                    }
                },
            },
        ),
        Tool(
            name="blender_render_thumbnail",
            description="Render a viewport thumbnail or camera view of a .blend file to an image file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blend_file": {
                        "type": "string",
                        "description": "Path to the .blend file.",
                    },
                    "output_image": {
                        "type": "string",
                        "description": "Destination file path for PNG or JPEG render.",
                    },
                    "resolution_x": {
                        "type": "integer",
                        "description": "Render width in pixels (default: 800)",
                        "default": 800,
                    },
                    "resolution_y": {
                        "type": "integer",
                        "description": "Render height in pixels (default: 600)",
                        "default": 600,
                    },
                },
                "required": ["blend_file", "output_image"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    blender_bin = _find_blender_binary()
    if not blender_bin:
        return [TextContent(type="text", text="Error: Blender is not installed or not found at /Applications/Blender.app")]

    if name == "blender_get_info":
        try:
            res = subprocess.run([blender_bin, "--version"], capture_output=True, text=True, timeout=10)
            ver_text = res.stdout.strip() or res.stderr.strip()
            return [TextContent(type="text", text=f"Blender is installed and ready:\n\n{ver_text}\n\nBinary: {blender_bin}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error checking Blender: {e}")]

    elif name == "blender_execute_code":
        code = arguments.get("code", "")
        blend_file = arguments.get("blend_file")

        # Wrapper script to run safely headless and capture output
        runner_script = f"""
import sys, json
try:
    import bpy
    {code}
except Exception as exc:
    import traceback
    print("BLENDER_EXEC_ERROR: " + str(exc), file=sys.stderr)
    traceback.print_exc()
"""
        cmd = [blender_bin, "--background"]
        if blend_file and os.path.isfile(blend_file):
            cmd.append(blend_file)
        cmd.extend(["--python-expr", runner_script])

        try:
            loop = asyncio.get_running_loop()
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            )
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            
            # Clean Blender banner from stdout
            lines = [l for l in out.splitlines() if not l.startswith("Blender ") and not "saved" in l.lower()]
            clean_out = "\n".join(lines).strip()
            
            result = f"Output:\n{clean_out}" if clean_out else "Executed successfully with no printed output."
            if err:
                result += f"\n\nStderr / Warnings:\n{err}"
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Execution error: {e}")]

    elif name == "blender_get_scene_summary":
        blend_file = arguments.get("blend_file")
        script = """
import bpy, json
data = {
    "objects": [{"name": o.name, "type": o.type, "location": list(o.location)} for o in bpy.data.objects],
    "materials": [m.name for m in bpy.data.materials],
    "meshes": [m.name for m in bpy.data.meshes],
    "cameras": [c.name for c in bpy.data.cameras],
    "lights": [l.name for l in bpy.data.lights],
}
print("===BLENDER_DATA_JSON===")
print(json.dumps(data, indent=2))
"""
        cmd = [blender_bin, "--background"]
        if blend_file and os.path.isfile(blend_file):
            cmd.append(blend_file)
        cmd.extend(["--python-expr", script])

        try:
            loop = asyncio.get_running_loop()
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            out = proc.stdout
            if "===BLENDER_DATA_JSON===" in out:
                json_part = out.split("===BLENDER_DATA_JSON===")[1].strip()
                return [TextContent(type="text", text=f"Blender Scene Summary:\n\n{json_part}")]
            return [TextContent(type="text", text=out or "No scene summary output.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error inspecting scene: {e}")]

    elif name == "blender_render_thumbnail":
        blend_file = arguments.get("blend_file")
        output_image = arguments.get("output_image")
        res_x = int(arguments.get("resolution_x", 800))
        res_y = int(arguments.get("resolution_y", 600))

        if not blend_file or not os.path.isfile(blend_file):
            return [TextContent(type="text", text=f"Error: blend file not found at {blend_file}")]

        render_script = f"""
import bpy
bpy.context.scene.render.resolution_x = {res_x}
bpy.context.scene.render.resolution_y = {res_y}
bpy.context.scene.render.filepath = '{output_image}'
bpy.ops.render.render(write_still=True)
"""
        cmd = [blender_bin, "--background", blend_file, "--python-expr", render_script]
        try:
            loop = asyncio.get_running_loop()
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            )
            if os.path.exists(output_image) or os.path.exists(output_image + ".png"):
                return [TextContent(type="text", text=f"Render complete! Saved image to {output_image}")]
            return [TextContent(type="text", text=f"Render output:\n{proc.stdout}\n{proc.stderr}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Render failed: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())

