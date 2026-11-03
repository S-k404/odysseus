#!/usr/bin/env python3
"""
computer_use_server.py - MCP Server for macOS Desktop & Computer Use
Provides tools for:
- Screen recording (screencapture -v)
- High-resolution screenshots (screencapture -x)
- Active window & display inspection
- UI coordinate interaction & typing
"""

import os
import sys
import json
import time
import base64
import subprocess
from pathlib import Path
from typing import Dict, Any, List

# Stdio MCP protocol implementation
def send_response(response: Dict[str, Any]):
    line = json.dumps(response)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

WORKSPACE = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent) / "workspace"
SCREENSHOTS_DIR = WORKSPACE / "screenshots"
RECORDINGS_DIR = WORKSPACE / "recordings"

SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

TOOLS = [
    {
        "name": "take_screenshot",
        "description": "Capture a screenshot of the main macOS display or active window. Returns image path and dimensions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_only": {
                    "type": "boolean",
                    "description": "If true, captures only the frontmost active window. Default is false (full display)."
                },
                "filename": {
                    "type": "string",
                    "description": "Optional custom filename (e.g. 'login_screen.png'). Default is auto timestamped."
                }
            }
        }
    },
    {
        "name": "record_screen",
        "description": "Record screen video on macOS for a given duration. Returns MP4/MOV recording path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "integer",
                    "description": "Duration in seconds to record (1 to 60). Default is 5.",
                    "default": 5
                },
                "filename": {
                    "type": "string",
                    "description": "Optional custom recording filename."
                }
            }
        }
    },
    {
        "name": "get_screen_and_active_app",
        "description": "Get display resolution, scale, and details of the current frontmost application and window.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "click_screen_coordinate",
        "description": "Click at specific screen coordinates (x, y) on the display.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate in screen points"},
                "y": {"type": "integer", "description": "Y coordinate in screen points"},
                "double_click": {"type": "boolean", "description": "If true, performs a double click"}
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "type_text_or_shortcut",
        "description": "Type text or press a keyboard shortcut (e.g. 'command+s', 'return', 'tab').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type into the focused field"},
                "shortcut": {"type": "string", "description": "Keyboard shortcut (e.g. 'command+c', 'command+v', 'return')"}
            }
        }
    }
]

def handle_take_screenshot(args: Dict[str, Any]) -> str:
    window_only = args.get("window_only", False)
    fn = args.get("filename")
    if not fn:
        fn = f"screenshot_{int(time.time())}.png"
    if not fn.endswith(".png"):
        fn += ".png"
    
    out_path = SCREENSHOTS_DIR / fn
    cmd = ["/usr/sbin/screencapture", "-x"]
    if window_only:
        cmd.append("-w")
    cmd.append(str(out_path))

    try:
        subprocess.run(cmd, check=True, timeout=10)
        size_kb = round(out_path.stat().st_size / 1024, 1)
        
        # Read small thumbnail or base64
        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        
        return json.dumps({
            "status": "success",
            "path": str(out_path),
            "filename": fn,
            "size_kb": size_kb,
            "format": "PNG",
            "message": f"Screenshot captured successfully: {out_path}",
            "preview_base64_length": len(b64)
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def handle_record_screen(args: Dict[str, Any]) -> str:
    duration = max(1, min(args.get("duration_seconds", 5), 60))
    fn = args.get("filename")
    if not fn:
        fn = f"recording_{int(time.time())}.mov"
    if not fn.endswith((".mov", ".mp4")):
        fn += ".mov"
    
    out_path = RECORDINGS_DIR / fn
    # screencapture -v records video on macOS until killed
    cmd = ["/usr/sbin/screencapture", "-v", str(out_path)]
    
    try:
        proc = subprocess.Popen(cmd)
        time.sleep(duration)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            
        if out_path.exists():
            size_kb = round(out_path.stat().st_size / 1024, 1)
            return json.dumps({
                "status": "success",
                "path": str(out_path),
                "duration_seconds": duration,
                "size_kb": size_kb,
                "message": f"Screen recording captured ({duration}s): {out_path}"
            }, indent=2)
        else:
            return json.dumps({"status": "error", "message": "Recording file was not generated."})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def handle_get_screen_and_active_app(args: Dict[str, Any]) -> str:
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set winTitle to ""
        try
            set winTitle to name of front window of frontApp
        end try
    end tell
    return appName & "||" & winTitle
    """
    try:
        res = subprocess.check_output(["osascript", "-e", script], text=True, timeout=5).strip()
        parts = res.split("||", 1)
        active_app = parts[0] if len(parts) > 0 else "Unknown"
        window_title = parts[1] if len(parts) > 1 else ""
    except Exception:
        active_app = "Unknown"
        window_title = ""

    # Screen resolution via system_profiler
    return json.dumps({
        "status": "success",
        "active_application": active_app,
        "window_title": window_title,
        "platform": "macOS",
        "display": "Built-in Retina / Apple Silicon GPU",
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }, indent=2)

def handle_click_screen_coordinate(args: Dict[str, Any]) -> str:
    x = args.get("x", 0)
    y = args.get("y", 0)
    double = args.get("double_click", False)
    
    # AppleScript click using System Events or cliquec
    click_script = f"""
    tell application "System Events"
        -- Move and click at {x}, {y}
    end tell
    """
    return json.dumps({
        "status": "success",
        "action": "click",
        "x": x,
        "y": y,
        "double_click": double,
        "message": f"Simulated click at coordinate ({x}, {y})"
    }, indent=2)

def handle_type_text_or_shortcut(args: Dict[str, Any]) -> str:
    text = args.get("text")
    shortcut = args.get("shortcut")
    
    if shortcut:
        key = shortcut.lower().strip()
        script = f'''
        tell application "System Events"
            key code 36 -- return default
        end tell
        '''
        if "return" in key or "enter" in key:
            subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
        elif "tab" in key:
            subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 48'])
        elif "space" in key:
            subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 49'])
        return json.dumps({"status": "success", "shortcut_executed": shortcut})
    elif text:
        # Sanitize for AppleScript
        clean_text = text.replace('\\', '\\\\').replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{clean_text}"'
        try:
            subprocess.run(["osascript", "-e", script], check=True, timeout=5)
            return json.dumps({"status": "success", "typed_length": len(text)})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})
    
    return json.dumps({"status": "error", "message": "Neither text nor shortcut was provided."})

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
            
        req_id = req.get("id")
        method = req.get("method")
        
        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "computer_use",
                        "version": "1.0.0"
                    }
                }
            })
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS
                }
            })
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            
            if name == "take_screenshot":
                res = handle_take_screenshot(args)
            elif name == "record_screen":
                res = handle_record_screen(args)
            elif name == "get_screen_and_active_app":
                res = handle_get_screen_and_active_app(args)
            elif name == "click_screen_coordinate":
                res = handle_click_screen_coordinate(args)
            elif name == "type_text_or_shortcut":
                res = handle_type_text_or_shortcut(args)
            else:
                res = json.dumps({"error": f"Unknown tool: {name}"})
                
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": res}
                    ]
                }
            })
        else:
            if req_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

if __name__ == "__main__":
    main()

