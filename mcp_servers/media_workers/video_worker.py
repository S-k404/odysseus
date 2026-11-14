#!/usr/bin/env python3
"""Generate a short video clip with a diffusers text-to-video pipeline, write an MP4, print one JSON line and exit.

Runs as its own process (see mcp_servers/media_runner.py) so the model's memory is returned
as soon as the clip is written. Needs torch and diffusers (plus ffmpeg, or OpenCV, to write the file).
"""
import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time


def encode(frames, fps: int, out: str) -> None:
    """H.264 through ffmpeg (plays in browsers and QuickTime); OpenCV's mp4v if there is no ffmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    with tempfile.TemporaryDirectory() as tmp:
        for i, frame in enumerate(frames):
            frame.save(os.path.join(tmp, f"f_{i:05d}.png"))
        if os.path.exists(ffmpeg):
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f_%05d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out], check=True)
            return
        import cv2
        first = cv2.imread(os.path.join(tmp, "f_00000.png"))
        writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (first.shape[1], first.shape[0]))
        for i in range(len(frames)):
            writer.write(cv2.imread(os.path.join(tmp, f"f_{i:05d}.png")))
        writer.release()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="worst quality, inconsistent motion, blurry, jittery, distorted")
    ap.add_argument("--frames", type=int, default=49)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--height", type=int, default=320)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    started = time.time()
    try:
        import numpy as np
        import torch
        from diffusers import DiffusionPipeline
        from PIL import Image
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"Missing Python package for video generation: {exc}"}))
        return 1

    try:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        pipe = DiffusionPipeline.from_pretrained(args.model, torch_dtype=torch.bfloat16)
        if os.environ.get("ODYSSEUS_VIDEO_OFFLOAD") == "1":
            pipe.enable_model_cpu_offload()  # lower peak memory, slower
        else:
            pipe.to(device)
        wanted = {"prompt": args.prompt, "negative_prompt": args.negative, "width": args.width, "height": args.height,
                  "num_frames": args.frames, "num_inference_steps": args.steps}
        if args.seed is not None:
            wanted["generator"] = torch.Generator(device="cpu").manual_seed(args.seed)
        accepted = set(inspect.signature(pipe.__call__).parameters)
        result = pipe(**{k: v for k, v in wanted.items() if k in accepted})
        frames = [f if isinstance(f, Image.Image) else Image.fromarray((np.clip(np.asarray(f), 0, 1) * 255).astype("uint8"))
                  for f in result.frames[0]]
        encode(frames, args.fps, args.out)
        print(json.dumps({"status": "success", "path": args.out, "frames": len(frames), "fps": args.fps,
                          "width": args.width, "height": args.height, "device": device,
                          "elapsed": round(time.time() - started, 1)}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
