#!/usr/bin/env python3
"""Generate a music clip with MusicGen, write a WAV, print one JSON line and exit.

Runs as its own process (see mcp_servers/media_runner.py) so the model's memory is returned
as soon as the clip is written. Needs torch and transformers.
"""
import argparse
import json
import sys
import time
import wave


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    started = time.time()
    try:
        import numpy as np
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"Missing Python package for music generation: {exc}"}))
        return 1

    try:
        processor = AutoProcessor.from_pretrained(args.model)
        model = MusicgenForConditionalGeneration.from_pretrained(args.model)
        encoder = model.config.audio_encoder
        steps = int(args.seconds * getattr(encoder, "frame_rate", 50))
        inputs = processor(text=[args.prompt], padding=True, return_tensors="pt")
        if args.seed is not None:
            torch.manual_seed(args.seed)

        def generate(device: str):
            m = model.to(device)
            batch = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                return m.generate(**batch, do_sample=True, guidance_scale=3.0, max_new_tokens=steps)

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            audio = generate(device)
        except Exception:
            if device == "cpu":
                raise
            device = "cpu"  # an op the GPU backend lacks: redo on the CPU
            audio = generate(device)

        samples = audio[0, 0].float().cpu().numpy()
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        rate = int(encoder.sampling_rate)
        with wave.open(args.out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm.tobytes())
        print(json.dumps({"status": "success", "path": args.out, "seconds": round(len(pcm) / rate, 1),
                          "sample_rate": rate, "device": device, "elapsed": round(time.time() - started, 1)}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
