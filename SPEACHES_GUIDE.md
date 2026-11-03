# Odysseus & Speaches Audio Engine — Fixes & Access Guide

This guide documents what was fixed, configured, and how to access all audio and document narration features.

---

## 🛠️ What Was Fixed & Configured

### 1. Unified TTS + STT Audio Engine
- **Previous state**: You had an older `kokoro-tts` container running on port 8880 that only supported Text-to-Speech, while Speech-to-Text (transcription) was disabled (`"stt_enabled": false`).
- **Fixed**: Deployed **Speaches** (`ghcr.io/speaches-ai/speaches:latest-cpu`) on port **8000**, unifying **Kokoro-82M** (TTS) and **Faster-Whisper** (STT) into a single OpenAI-compatible service.
- **Resource Cleanup**: Stopped the obsolete single-purpose `kokoro-tts` container to reclaim system memory and CPU.

### 2. Docker Network Connectivity
- **Fixed**: Connected the `speaches` container to the existing `odysseus_default` bridge network. Odysseus communicates internally via `http://speaches:8000/v1` (Docker DNS), while your Mac host communicates via `http://localhost:8000/v1`.

### 3. Added Native `provider=openai` in Odysseus Backend
- **Previous state**: Odysseus's `TTSService` and `STTService` only supported `local` or `endpoint:<id>`. Setting `TTS_PROVIDER=openai` in `.env` resulted in Odysseus treating the provider as disabled or throwing errors.
- **Fixed**: Updated `services/tts/tts_service.py` and `services/stt/stt_service.py` to directly read environment variables (`TTS_PROVIDER=openai`, `TTS_OPENAI_API_BASE`, `TTS_VOICE=af_sky`, `STT_PROVIDER=openai`, `STT_OPENAI_API_BASE`, etc.) and dispatch OpenAI-compatible requests.

### 4. Model Name Aliasing
- **Fixed**: Speaches loads weights under the repo `speaches-ai/Kokoro-82M-v1.0-ONNX`. When Odysseus or scripts request `hexgrad/Kokoro-82M` or `kokoro`, Odysseus and `read_doc.py` automatically alias the request to the active ONNX model so it never fails with `404 Not Found`.

### 5. Client-Side Voice Recorder
- **Fixed**: Updated `static/js/voiceRecorder.js` so clicking the microphone in the Odysseus chat UI triggers server-side transcription when `STT_PROVIDER=openai`.

### 6. Agent Persona & Chat Preset Deployment
- **Fixed**: Saved the **"Document Narrator"** agent persona to both the Odysseus SQLite database (`crew_members` table) and the chat preset store (`presets.json`).

---

## 🚀 How to Access Everything

### 1. In Odysseus Web App (UI)
Open your browser to: **[http://localhost:7000](http://localhost:7000)**

* **Voice Output (TTS)**:
  - When the agent responds, it synthesizes spoken audio using Kokoro voice `af_sky`.
* **Voice Input (STT)**:
  - Click the **microphone icon** next to the chat prompt bar, speak into your mic, and click stop. Faster-Whisper will transcribe your speech directly into the prompt box.
* **Document Narrator Agent**:
  - **Via Preset Dropdown**: Click the preset selector above the chat bar and choose **"Document Narrator"**.
  - **Via Assistants / Crew**: Switch to the **Document Narrator 🎙️** assistant.
  - Upload a PDF, markdown note, or research paper and type:
    - `"Read Chapter 1"` or
    - `"Executive Briefing"`

---

### 2. Speaches Web Dashboard & Test UI
Open your browser to: **[http://localhost:8000/](http://localhost:8000/)**

* Provides an interactive Gradio web UI where you can test different Kokoro voices (`af_sky`, `af_bella`, `am_adam`, `bf_emma`, `bm_george`), adjust speech speed, and test audio transcriptions directly.

---

### 3. Document-to-Speech CLI (`read_doc.py`)
Run from your terminal to read any `.pdf`, `.md`, or `.txt` document:

```bash
cd /Users/shamit/Documents/Docker/Speaches

# 1. Narrate a PDF to an MP3 file
./read_doc.py /path/to/document.pdf --output my_narration.mp3 --voice af_sky

# 2. Narrate a Markdown file and play it aloud immediately (macOS afplay)
./read_doc.py test_docs/sample.md --play

# 3. Use another voice (e.g., British female voice 'bf_emma')
./read_doc.py test_docs/sample.pdf --voice bf_emma --play
```
*(Note: `read_doc.py` is also available directly inside `/Users/shamit/Documents/Docker/Odysseus/read_doc.py`)*

---

### 4. Universal Document Narrator (`narrator.py`)
For advanced multi-format narration (including **EPUB** books and page range selection):

```bash
cd /Users/shamit/Documents/Docker/Speaches

# Read specific pages of a PDF
./narrator.py document.pdf --start-page 1 --end-page 10 -o chapter1.mp3

# Narrate an entire EPUB book
./narrator.py book.epub -v af_sky -o audiobook.mp3 --play
```

---

### 5. Managing the Docker Container
To check logs, stop, or restart Speaches:

```bash
cd /Users/shamit/Documents/Docker/Speaches

# View real-time logs
docker logs -f speaches

# Restart Speaches
docker compose restart

# Stop / Start
docker compose down
docker compose up -d
```

---

### 6. Automated Verification Suite
Run the 10-point verification test at any time to confirm all systems are operating:

```bash
cd /Users/shamit/Documents/Docker/Speaches
python3 verify_all.py
```
