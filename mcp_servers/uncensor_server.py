#!/usr/bin/env python3
"""
mcp_servers/uncensor_server.py

Odysseus built-in MCP server shim for manga panel & image decensoring.
Delegates to the dedicated odysseus-image-tools environment where diffusers,
PyTorch MPS, and SDXL inpainting weights reside.
"""
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "odysseus-image-tools"
VENV_PYTHON = TOOLS_DIR / ".venv" / "bin" / "python"
SERVER_SCRIPT = TOOLS_DIR / "uncensor_server.py"

if VENV_PYTHON.is_file() and SERVER_SCRIPT.is_file():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(SERVER_SCRIPT)] + sys.argv[1:])
else:
    sys.stderr.write(f"Error: Could not find uncensor tools at {TOOLS_DIR}\n")
    sys.exit(1)
