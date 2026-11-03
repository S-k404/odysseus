#!/usr/bin/env python3
"""
music_gen_server.py - MCP Server for Music & Neural Audio Generation
Provides tools for:
- Parametric procedural music synthesis (WAV/MP3 generation: chords, melodies, ambient tracks)
- Neural speech & voice generation (via Speaches/Kokoro port 8000)
- Speech & audio transcription (via Faster-Whisper port 8000)
"""

import os
import sys
import json
import math
import time
import wave
import struct
import httpx
from pathlib import Path
from typing import Dict, Any, List

def send_response(response: Dict[str, Any]):
    line = json.dumps(response)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

WORKSPACE = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent) / "workspace"
AUDIO_DIR = WORKSPACE / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SPEACHES_BASE = os.environ.get("SPEACHES_BASE_URL", "http://127.0.0.1:8000/v1")

TOOLS = [
    {
        "name": "generate_music_track",
        "description": "Generate a synthesized music track (ambient, synthwave, lofi, or electronic) with custom tempo, scale, and duration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "Music genre (e.g. 'synthwave', 'lofi', 'ambient', 'classical', 'cyberpunk')",
                    "default": "ambient"
                },
                "key": {
                    "type": "string",
                    "description": "Musical key (e.g. 'C_major', 'A_minor', 'D_dorian', 'F_sharp_minor')",
                    "default": "A_minor"
                },
                "bpm": {
                    "type": "integer",
                    "description": "Tempo in beats per minute (60 to 180)",
                    "default": 110
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "Length of the track in seconds (5 to 60)",
                    "default": 15
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (e.g. 'theme_song.wav')"
                }
            }
        }
    },
    {
        "name": "generate_speech_track",
        "description": "Generate high-fidelity neural voice audio using Kokoro TTS on local Apple Silicon.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The script or dialogue to synthesize into speech"
                },
                "voice": {
                    "type": "string",
                    "description": "Voice identifier (e.g. 'af_heart', 'af_bella', 'am_adam', 'bf_emma', 'bm_george')",
                    "default": "af_heart"
                },
                "filename": {
                    "type": "string",
                    "description": "Output audio filename (e.g. 'voiceover.mp3')"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "transcribe_audio_file",
        "description": "Transcribe speech from an audio file (WAV, MP3, M4A) using local Faster-Whisper.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Full path to the audio file to transcribe"
                }
            },
            "required": ["audio_path"]
        }
    }
]

# Frequency table for notes
NOTE_FREQS = {
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.00, "A3": 220.00, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00, "B4": 493.88,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "F5": 698.46, "G5": 783.99, "A5": 880.00, "B5": 987.77,
}

SCALES = {
    "A_minor": ["A3", "C4", "D4", "E4", "G4", "A4", "C5", "E5"],
    "C_major": ["C3", "E3", "G3", "C4", "E4", "G4", "A4", "C5"],
    "synthwave": ["D3", "F3", "A3", "D4", "F4", "A4", "C5", "D5"],
    "ambient": ["E3", "G3", "B3", "E4", "G4", "B4", "D5", "E5"],
}

def synthesize_procedural_track(out_path: Path, genre: str, scale_name: str, bpm: int, duration_sec: int) -> str:
    sample_rate = 44100
    total_samples = sample_rate * duration_sec
    scale = SCALES.get(scale_name, SCALES["A_minor"])
    
    # Generate notes based on beat
    beat_dur = 60.0 / bpm
    samples_per_beat = int(sample_rate * beat_dur)
    
    data = []
    t = 0
    note_idx = 0
    
    for i in range(total_samples):
        # Bass tone
        t_sec = i / sample_rate
        beat_idx = int(i / samples_per_beat)
        current_note = scale[beat_idx % len(scale)]
        freq = NOTE_FREQS.get(current_note, 440.0)
        
        # Fundamental wave (sine + subtle harmonic)
        val = 0.5 * math.sin(2.0 * math.pi * freq * t_sec)
        val += 0.25 * math.sin(4.0 * math.pi * freq * t_sec)
        
        # Sub-bass for synthwave/electronic
        if genre in ("synthwave", "cyberpunk"):
            bass_freq = freq / 2.0
            val += 0.35 * math.sin(2.0 * math.pi * bass_freq * t_sec)
            
        # Percussive envelope per beat
        env = math.exp(-3.0 * ((i % samples_per_beat) / samples_per_beat))
        val = val * (0.6 + 0.4 * env)
        
        # Clamp to 16-bit PCM
        val = max(-1.0, min(1.0, val))
        sample_val = int(val * 32767 * 0.75)
        data.append(struct.pack("<h", sample_val))
        
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(data))
        
    size_kb = round(out_path.stat().st_size / 1024, 1)
    return json.dumps({
        "status": "success",
        "path": str(out_path),
        "genre": genre,
        "key": scale_name,
        "bpm": bpm,
        "duration_seconds": duration_sec,
        "size_kb": size_kb,
        "format": "WAV 44.1kHz 16-bit",
        "message": f"Synthesized track '{genre}' successfully: {out_path}"
    }, indent=2)

def handle_generate_music_track(args: Dict[str, Any]) -> str:
    genre = args.get("genre", "ambient")
    key = args.get("key", "A_minor")
    bpm = max(60, min(args.get("bpm", 110), 180))
    dur = max(5, min(args.get("duration_seconds", 15), 60))
    fn = args.get("filename")
    if not fn:
        fn = f"music_{genre}_{int(time.time())}.wav"
    if not fn.endswith(".wav"):
        fn += ".wav"
        
    out_path = AUDIO_DIR / fn
    try:
        return synthesize_procedural_track(out_path, genre, key, bpm, dur)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def handle_generate_speech_track(args: Dict[str, Any]) -> str:
    text = args.get("text", "")
    voice = args.get("voice", "af_heart")
    fn = args.get("filename")
    if not fn:
        fn = f"speech_{int(time.time())}.mp3"
    if not fn.endswith((".mp3", ".wav")):
        fn += ".mp3"
        
    out_path = AUDIO_DIR / fn
    
    # Try calling Speaches on port 8000
    try:
        url = f"{SPEACHES_BASE}/audio/speech"
        payload = {
            "model": "speaches-ai/Kokoro-82M-v1.0-ONNX",
            "input": text,
            "voice": voice,
            "response_format": "mp3"
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                size_kb = round(out_path.stat().st_size / 1024, 1)
                return json.dumps({
                    "status": "success",
                    "path": str(out_path),
                    "size_kb": size_kb,
                    "voice": voice,
                    "model": "Kokoro-82M-v1.0-ONNX",
                    "message": f"Generated neural speech audio: {out_path}"
                }, indent=2)
            else:
                return json.dumps({
                    "status": "error",
                    "status_code": resp.status_code,
                    "error": resp.text
                })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def handle_transcribe_audio(args: Dict[str, Any]) -> str:
    audio_path = args.get("audio_path", "")
    p = Path(audio_path)
    if not p.exists():
        return json.dumps({"status": "error", "message": f"File not found: {audio_path}"})
        
    try:
        url = f"{SPEACHES_BASE}/audio/transcriptions"
        with open(p, "rb") as f:
            files = {"file": (p.name, f, "audio/mpeg")}
            data = {"model": "Systran/faster-whisper-small"}
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, files=files, data=data)
                if resp.status_code == 200:
                    return json.dumps(resp.json(), indent=2)
                else:
                    return json.dumps({"status": "error", "status_code": resp.status_code, "text": resp.text})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

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
                        "name": "music_gen",
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
            
            if name == "generate_music_track":
                res = handle_generate_music_track(args)
            elif name == "generate_speech_track":
                res = handle_generate_speech_track(args)
            elif name == "transcribe_audio_file":
                res = handle_transcribe_audio(args)
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

