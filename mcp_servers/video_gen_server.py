#!/usr/bin/env python3
"""
video_gen_server.py - MCP server for text-to-video generation on the local GPU.

The video model is big, so it is loaded only while a clip is made: each request runs in a
short-lived worker process (mcp_servers/media_workers/video_worker.py) whose memory is returned
when it exits. The first use downloads the model and needs allow_download=true, which the model
may only set after the user agreed. Override the model with ODYSSEUS_VIDEO_MODEL.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_runner

WORKSPACE = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent) / "workspace"
VIDEO_DIR = WORKSPACE / "video"

VIDEO_MODEL = os.environ.get("ODYSSEUS_VIDEO_MODEL", "Lightricks/LTX-Video")
VIDEO_MODEL_SIZE = "several GB, roughly 15 to 30 GB for the default model; the exact size could not be checked offline"
VIDEO_NEEDS_GB = float(os.environ.get("ODYSSEUS_VIDEO_NEEDS_GB", "20"))
FPS = 24

TOOLS = [
    {
        "name": "generate_video",
        "description": "Create a short video clip from a text description with a local text-to-video model. Heavy: it needs about "
                       "20 GB of free memory and takes several minutes, so other models are unloaded first. The model loads only "
                       "while the clip is made. The first use downloads it and needs allow_download=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What happens in the clip: subject, action, setting, light, camera"},
                "duration_seconds": {"type": "integer", "description": "Clip length in seconds (1 to 4)", "default": 2},
                "width": {"type": "integer", "description": "Width in pixels (256 to 768, rounded to a multiple of 32)", "default": 512},
                "height": {"type": "integer", "description": "Height in pixels (256 to 768, rounded to a multiple of 32)", "default": 320},
                "steps": {"type": "integer", "description": "Quality vs speed, 10 to 50", "default": 30},
                "seed": {"type": "integer", "description": "Reuse a seed to repeat a result"},
                "filename": {"type": "string", "description": "Output filename (e.g. 'wave.mp4')"},
                "allow_download": {"type": "boolean", "description": "Set true only after the user agreed to download the model on first use"}
            },
            "required": ["prompt"]
        }
    }
]


def _snap32(value: int) -> int:
    return max(256, min(int(round(value / 32) * 32), 768))


def plan_frames(seconds: int) -> int:
    """Frame count the clip needs: whole seconds at FPS, rounded to 8k+1 (what the video model wants), 9 to 97."""
    return max(9, min((max(1, min(seconds, 4)) * FPS // 8) * 8 + 1, 97))


def handle_generate_video(args: Dict[str, Any]) -> str:
    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        return media_runner.error("prompt is required: describe what happens in the clip.")
    python = media_runner.find_python(("torch", "diffusers", "PIL"))
    if not python:
        return media_runner.error(
            "Video generation needs a Python with torch and diffusers, and none was found. "
            "Install diffusers into an environment of your choice and set ODYSSEUS_MEDIA_PYTHON to its python.")
    if not media_runner.model_downloaded(VIDEO_MODEL) and not args.get("allow_download"):
        return media_runner.needs_download_message(VIDEO_MODEL, VIDEO_MODEL_SIZE)
    short = media_runner.not_enough_memory(VIDEO_NEEDS_GB)
    if short:
        return media_runner.error(short)

    frames = plan_frames(int(args.get("duration_seconds") or 2))
    fn = args.get("filename") or f"video_{int(time.time())}.mp4"
    if not fn.endswith(".mp4"):
        fn += ".mp4"
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VIDEO_DIR / Path(fn).name
    cmd = ["--model", VIDEO_MODEL, "--prompt", prompt, "--frames", str(frames), "--fps", str(FPS),
           "--width", str(_snap32(int(args.get("width") or 512))), "--height", str(_snap32(int(args.get("height") or 320))),
           "--steps", str(max(10, min(int(args.get("steps") or 30), 50))), "--out", str(out_path)]
    if args.get("seed") is not None:
        cmd += ["--seed", str(int(args["seed"]))]
    result = media_runner.run_worker(python, "video_worker.py", cmd, timeout=3600)
    if result.get("status") == "success":
        result["size_kb"] = round(out_path.stat().st_size / 1024, 1)
        result["model"] = VIDEO_MODEL
        result["message"] = f"Generated a {result.get('frames')}-frame video: {out_path}"
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    media_runner.serve("video_gen", TOOLS, {"generate_video": handle_generate_video})
