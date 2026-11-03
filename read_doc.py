#!/usr/bin/env python3
"""
read_doc.py — Versatile Document-to-Speech CLI.

Extracts text from .txt, .md, and .pdf documents, cleans visual noise
(URLs, code fences, citations), chunks at natural sentence boundaries,
and synthesizes speech via Kokoro TTS (Speaches) into an MP3 or plays directly.
"""

import sys
import os
import re
import argparse
import subprocess
import requests
from pathlib import Path

# PDF parsing with graceful fallbacks
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

SPEACHES_ENDPOINT = os.getenv("TTS_API_URL", "http://localhost:8000/v1/audio/speech")
DEFAULT_MODEL = os.getenv("TTS_MODEL", "speaches-ai/Kokoro-82M-v1.0-ONNX")


def extract_text(file_path: Path) -> str:
    """Extracts raw text from .txt, .md, and .pdf files."""
    suffix = file_path.suffix.lower()

    if suffix in [".txt", ".md", ".markdown"]:
        return file_path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        if pypdf is not None:
            reader = pypdf.PdfReader(str(file_path))
            return "\n\n".join([page.extract_text() or "" for page in reader.pages])
        elif fitz is not None:
            doc = fitz.open(str(file_path))
            text = "\n\n".join([page.get_text() for page in doc])
            doc.close()
            return text
        else:
            raise ImportError("Run 'pip install pypdf' or 'pip install pymupdf' to enable PDF document reading.")
    elif suffix == ".epub":
        import zipfile
        from bs4 import BeautifulSoup
        chapters = []
        with zipfile.ZipFile(str(file_path), "r") as z:
            for name in sorted(z.namelist()):
                if name.lower().endswith((".xhtml", ".html")):
                    soup = BeautifulSoup(z.read(name), "html.parser")
                    for tag in soup(["script", "style", "nav"]):
                        tag.extract()
                    chapters.append(soup.get_text(separator=" "))
        return "\n\n".join(chapters)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def clean_text_for_speech(text: str) -> str:
    """Removes code blocks, markdown links, citation brackets, and URLs."""
    text = re.sub(r"```[\s\S]*?```", " [Code Block Omitted] ", text) # Remove code blocks
    text = re.sub(r"`[^`]*`", "", text)                              # Remove inline code
    text = re.sub(r"https?://\S+|www\.\S+", "", text)               # Remove URLs
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)           # Convert [Link](url) -> Link
    text = re.sub(r"\[\d+\]", "", text)                             # Remove citation brackets like [1], [2]
    # Clean redundant whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def chunk_by_sentences(text: str, max_chars: int = 700):
    """Chunks text into natural sentence boundaries."""
    sentences = re.split(r'(?<=[.?!])\s+', text)
    chunks, current = [], ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(current) + len(s) < max_chars:
            current += (" " if current else "") + s
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks


def synthesize(chunks, voice="af_sky", model="hexgrad/Kokoro-82M", output="narration.mp3"):
    print(f"Synthesizing {len(chunks)} sections with voice '{voice}'...")

    # Map model name alias if needed
    effective_model = model
    if effective_model in ("hexgrad/Kokoro-82M", "kokoro", "Kokoro-82M"):
        effective_model = "speaches-ai/Kokoro-82M-v1.0-ONNX"

    with open(output, "wb") as f_out:
        for idx, chunk in enumerate(chunks, 1):
            print(f"  -> Processing section {idx}/{len(chunks)}...")
            try:
                res = requests.post(
                    SPEACHES_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": effective_model,
                        "input": chunk,
                        "voice": voice,
                        "response_format": "mp3"
                    },
                    timeout=60
                )
                if res.status_code == 200:
                    f_out.write(res.content)
                else:
                    print(f"Error on section {idx}: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"Connection error on section {idx}: {e}")

    print(f"Finished! Narration saved to: {output}")


def play_audio(audio_path: str):
    """Plays generated audio aloud on macOS."""
    if sys.platform == "darwin":
        print(f"Playing narration aloud: {audio_path}")
        try:
            subprocess.run(["afplay", audio_path], check=True)
        except KeyboardInterrupt:
            print("\nPlayback stopped.")
        except Exception as e:
            print(f"Playback error: {e}")
    else:
        print(f"Native playback only on macOS (platform={sys.platform}). Audio saved to {audio_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read any document aloud using Kokoro TTS.")
    parser.add_argument("file", help="Path to .txt, .md, or .pdf file")
    parser.add_argument("--voice", default="af_sky", help="Kokoro voice (af_sky, af_bella, am_adam, bf_emma, bm_george)")
    parser.add_argument("--model", default="hexgrad/Kokoro-82M", help="Model name (default: hexgrad/Kokoro-82M)")
    parser.add_argument("--output", default="document_narration.mp3", help="Output MP3 path")
    parser.add_argument("--play", action="store_true", help="Play narration aloud after synthesis")
    args = parser.parse_args()

    raw_text = extract_text(Path(args.file))
    cleaned = clean_text_for_speech(raw_text)
    chunks = chunk_by_sentences(cleaned)
    synthesize(chunks, voice=args.voice, model=args.model, output=args.output)

    if args.play:
        play_audio(args.output)
