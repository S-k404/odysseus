"""Neural music, video and the speech errors: mcp_servers/{music_gen,video_gen}_server.py + media_runner.py.

No model is loaded and nothing is downloaded: the workers are replaced by tiny fake scripts, so what is
checked is the plumbing (cache check, download consent, memory check, worker protocol, error messages).
"""

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from src import ram_optimizer as ro

SERVERS = Path(__file__).resolve().parent.parent / "mcp_servers"

FAKE_WORKER = '''
import json, sys
argv = sys.argv[1:]
opt = {argv[i]: argv[i + 1] for i in range(0, len(argv) - 1, 2) if argv[i].startswith("--")}
open(opt["--out"], "wb").write(b"fake media")
print("loading model...")
print(json.dumps({"status": "success", "path": opt["--out"], "seconds": 7.0, "frames": 49, "argv": argv}))
'''


def _load(name, monkeypatch, tmp_path):
    monkeypatch.setenv("ODYSSEUS_REPO_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))  # the servers put their own folder first
    spec = importlib.util.spec_from_file_location(name, SERVERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def media(monkeypatch, tmp_path):
    """media_runner pointed at a fake worker folder, with a model that looks downloaded and plenty of memory."""
    workers = tmp_path / "workers"
    workers.mkdir()
    for worker in ("musicgen_worker.py", "video_worker.py"):
        (workers / worker).write_text(FAKE_WORKER)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    sys.path.insert(0, str(SERVERS))
    import media_runner
    monkeypatch.setattr(media_runner, "WORKERS_DIR", workers)
    monkeypatch.setattr(media_runner, "find_python", lambda modules: sys.executable)
    monkeypatch.setattr(media_runner, "memory_snapshot",
                        lambda: {"total_gb": 48.0, "used_gb": 20.0, "available_gb": 28.0})
    yield media_runner
    sys.modules.pop("media_runner", None)


def _cache_model(tmp_path, repo_id):
    snap = tmp_path / "hf" / ("models--" + repo_id.replace("/", "--")) / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")


# ---- speech and transcription errors -------------------------------------------------------

class _Down:
    def __init__(self, exc):
        self.exc = exc

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        raise self.exc


def test_speech_says_plainly_when_speaches_is_not_running(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    monkeypatch.setattr(music.httpx, "Client", _Down(httpx.ConnectError("All connection attempts failed")))

    reply = json.loads(music.handle_generate_speech_track({"text": "hello"}))

    assert reply["status"] == "error" and reply["service"] == "speaches" and reply["retry"] is False
    assert "isn't running" in reply["error"] and "docker compose up -d speaches" in reply["error"]
    assert "generate_music_track" in reply["error"]  # the tools that still work are named
    assert "All connection attempts failed" not in reply["error"]


def test_transcription_gets_the_same_clear_error(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    monkeypatch.setattr(music.httpx, "Client", _Down(httpx.ConnectError("refused")))
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"x")

    reply = json.loads(music.handle_transcribe_audio({"audio_path": str(audio)}))

    assert "isn't running" in reply["error"] and "transcription" in reply["error"]


def test_slow_and_other_speech_failures_are_told_apart(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    monkeypatch.setattr(music.httpx, "Client", _Down(httpx.ReadTimeout("slow")))
    assert "did not answer in time" in json.loads(music.handle_generate_speech_track({"text": "hi"}))["error"]
    monkeypatch.setattr(music.httpx, "Client", _Down(ValueError("odd")))
    assert "speech generation failed: odd" in json.loads(music.handle_generate_speech_track({"text": "hi"}))["error"]
    assert "text is required" in json.loads(music.handle_generate_speech_track({"text": "  "}))["error"]


# ---- neural music --------------------------------------------------------------------------

def test_neural_music_asks_before_the_first_download(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)

    reply = json.loads(music.handle_generate_music_neural({"prompt": "calm piano"}))

    assert reply["status"] == "needs_download" and reply["model"] == "facebook/musicgen-small"
    assert "allow_download=true" in reply["message"] and "2.4 GB" in reply["message"]
    assert not list((tmp_path / "workspace" / "audio").glob("*.wav"))


def test_neural_music_runs_the_worker_once_the_model_is_there(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    _cache_model(tmp_path, "facebook/musicgen-small")

    reply = json.loads(music.handle_generate_music_neural(
        {"prompt": "calm piano", "duration_seconds": 99, "seed": 5, "filename": "../escape"}))

    assert reply["status"] == "success" and "size_kb" in reply
    assert Path(reply["path"]).parent == tmp_path / "workspace" / "audio" and Path(reply["path"]).name == "escape.wav"
    argv = reply["argv"]
    assert argv[argv.index("--seconds") + 1] == "30"  # clamped to what MusicGen handles
    assert argv[argv.index("--seed") + 1] == "5" and argv[argv.index("--prompt") + 1] == "calm piano"


def test_neural_music_downloads_when_the_user_agreed(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    reply = json.loads(music.handle_generate_music_neural({"prompt": "x", "allow_download": True}))
    assert reply["status"] == "success", reply


def test_neural_music_refuses_when_memory_is_short_and_says_how_to_fix_it(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    _cache_model(tmp_path, "facebook/musicgen-small")
    monkeypatch.setattr(media, "memory_snapshot", lambda: {"total_gb": 48.0, "used_gb": 44.0, "available_gb": 4.0})

    reply = json.loads(music.handle_generate_music_neural({"prompt": "calm piano"}))

    assert reply["status"] == "error" and "Optimise memory" in reply["error"] and "6 GB" in reply["error"]


def test_neural_music_reports_missing_packages_and_empty_prompts(media, monkeypatch, tmp_path):
    music = _load("music_gen_server", monkeypatch, tmp_path)
    assert "prompt is required" in json.loads(music.handle_generate_music_neural({"prompt": " "}))["error"]
    monkeypatch.setattr(media, "find_python", lambda modules: None)
    assert "torch and transformers" in json.loads(music.handle_generate_music_neural({"prompt": "x"}))["error"]


# ---- video ---------------------------------------------------------------------------------

def test_video_frame_counts_follow_the_8k_plus_1_rule(media, monkeypatch, tmp_path):
    video = _load("video_gen_server", monkeypatch, tmp_path)
    assert [video.plan_frames(s) for s in (0, 1, 2, 3, 4, 10)] == [25, 25, 49, 73, 97, 97]
    assert [video._snap32(v) for v in (100, 500, 512, 1000)] == [256, 512, 512, 768]


def test_video_needs_consent_then_runs_with_clamped_settings(media, monkeypatch, tmp_path):
    video = _load("video_gen_server", monkeypatch, tmp_path)
    first = json.loads(video.handle_generate_video({"prompt": "a wave"}))
    assert first["status"] == "needs_download" and first["model"] == "Lightricks/LTX-Video"

    reply = json.loads(video.handle_generate_video(
        {"prompt": "a wave", "allow_download": True, "duration_seconds": 3, "width": 1000, "steps": 500, "filename": "w"}))

    assert reply["status"] == "success" and Path(reply["path"]) == tmp_path / "workspace" / "video" / "w.mp4"
    argv = reply["argv"]
    assert argv[argv.index("--frames") + 1] == "73" and argv[argv.index("--width") + 1] == "768"
    assert argv[argv.index("--steps") + 1] == "50"


def test_video_refuses_without_20_gb_to_spare(media, monkeypatch, tmp_path):
    video = _load("video_gen_server", monkeypatch, tmp_path)
    _cache_model(tmp_path, "Lightricks/LTX-Video")
    monkeypatch.setattr(media, "memory_snapshot", lambda: {"total_gb": 48.0, "used_gb": 35.0, "available_gb": 13.0})

    reply = json.loads(video.handle_generate_video({"prompt": "a wave"}))

    assert reply["status"] == "error" and "20 GB" in reply["error"] and "Optimise memory" in reply["error"]


# ---- media_runner --------------------------------------------------------------------------

def test_model_cache_check_is_offline_and_needs_a_snapshot(media, tmp_path):
    assert not media.model_downloaded("org/name")
    (tmp_path / "hf" / "models--org--name" / "snapshots").mkdir(parents=True)
    assert not media.model_downloaded("org/name")  # an empty folder is a failed download
    _cache_model(tmp_path, "org/name")
    assert media.model_downloaded("org/name")


def test_a_killed_worker_is_reported_as_out_of_memory(media, tmp_path):
    (media.WORKERS_DIR / "crash.py").write_text("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
    result = media.run_worker(sys.executable, "crash.py", [], timeout=30)
    assert result["status"] == "error" and "out of memory" in result["error"]


def test_a_failing_worker_shows_the_last_lines_of_its_output(media):
    (media.WORKERS_DIR / "fail.py").write_text("import sys\nprint('a')\nprint('Traceback boom', file=sys.stderr)\nsys.exit(2)\n")
    result = media.run_worker(sys.executable, "fail.py", [], timeout=30)
    assert result["status"] == "error" and "Traceback boom" in result["error"]


def test_a_worker_that_hangs_is_stopped(media):
    (media.WORKERS_DIR / "hang.py").write_text("import time\ntime.sleep(60)\n")
    result = media.run_worker(sys.executable, "hang.py", [], timeout=1)
    assert result["status"] == "error" and "did not finish" in result["error"]


def test_server_speaks_mcp_over_stdio():
    """Start the real video server and talk to it the way Odysseus does."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "generate_video", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(SERVERS / "video_gen_server.py")], capture_output=True, text=True,
                          input="".join(json.dumps(r) + "\n" for r in requests), timeout=60)
    replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
    assert replies[1]["result"]["serverInfo"]["name"] == "video_gen"
    assert [t["name"] for t in replies[2]["result"]["tools"]] == ["generate_video"]
    assert "prompt is required" in replies[3]["result"]["content"][0]["text"]
    assert "Unknown tool" in replies[4]["result"]["content"][0]["text"]


@pytest.mark.skipif(not shutil.which("ffmpeg") and not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="needs ffmpeg")
def test_video_worker_encodes_frames_into_a_real_mp4(tmp_path):
    from PIL import Image
    spec = importlib.util.spec_from_file_location("video_worker", SERVERS / "media_workers" / "video_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    frames = [Image.new("RGB", (64, 64), (i * 20, 40, 90)) for i in range(9)]

    out = tmp_path / "clip.mp4"
    worker.encode(frames, 8, str(out))

    assert out.stat().st_size > 0 and out.read_bytes()[4:8] == b"ftyp"  # an MP4 container


# ---- freeing memory before a heavy tool ----------------------------------------------------

def _snap(available, total=48.0):
    return {"total_gb": total, "used_gb": total - available, "available_gb": available}


def test_heavy_tools_free_memory_first_only_when_they_would_not_fit(monkeypatch):
    monkeypatch.setattr(ro, "runner_urls", lambda: [])  # never look at the real endpoints
    freed = []

    async def free(urls, keep=""):
        freed.append(keep)
        return {"steps": ["unloaded qwen3.6"]}

    def run(tool, available):
        return asyncio.run(ro.ensure_ram_for_tool(tool, snapshot=lambda: _snap(available), free=free))

    assert run("mcp__video_gen__generate_video", 40.0) is None and freed == []  # fits
    assert run("mcp__video_gen__generate_video", 15.0) == ["unloaded qwen3.6"] and freed == [""]
    assert run("mcp__email__list_emails", 1.0) is None and freed == [""]  # not a heavy tool
    assert run("mcp__uncensor__uncensor_image", 1.0) == ["unloaded qwen3.6"]  # decensor tool frees memory when RAM is tight


def test_freeing_memory_never_blocks_the_tool(monkeypatch):
    monkeypatch.setattr(ro, "runner_urls", lambda: [])

    async def broken(urls, keep=""):
        raise RuntimeError("runner exploded")

    assert asyncio.run(ro.ensure_ram_for_tool("mcp__video_gen__generate_video", snapshot=lambda: _snap(1.0), free=broken)) is None
    assert asyncio.run(ro.ensure_ram_for_tool("mcp__video_gen__generate_video", snapshot=lambda: None)) is None


# ---- the agent's generate_image tool: local first, local sizes -----------------------------

def _image_server():
    spec = importlib.util.spec_from_file_location("image_gen_server", SERVERS / "image_gen_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_image_tool_picks_the_local_model_and_keeps_local_sizes_small():
    tool = _image_server()
    pinned = json.dumps(["docker.io/ai/stable-diffusion:latest"])
    everything = json.dumps(["huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M", "docker.io/ai/stable-diffusion:latest", "gpt-image-1"])
    assert tool.first_image_model([(pinned, everything)]) == "docker.io/ai/stable-diffusion:latest"
    assert tool.first_image_model([(None, everything)]) == "docker.io/ai/stable-diffusion:latest"  # no pinned list: the cache
    assert tool.first_image_model([(None, json.dumps(["qwen3-8b"])), ("not json", None)]) == ""
    assert tool.pick_size("docker.io/ai/stable-diffusion:latest", "") == "512x512"
    assert tool.pick_size("docker.io/ai/stable-diffusion:latest", "700x300") == "704x320"
    assert tool.pick_size("docker.io/ai/stable-diffusion:latest", "9000x9000") == "1024x1024"
    assert tool.pick_size("docker.io/ai/stable-diffusion:latest", "banana") == "512x512"
    assert tool.pick_size("gpt-image-1", "512x512") == "1024x1024" and tool.pick_size("gpt-image-1", "1536x1024") == "1536x1024"
    assert tool.pick_size("dall-e-3", "1024x1792") == "1024x1792"


def test_the_image_tool_makes_room_before_a_local_image_model_loads(monkeypatch):
    monkeypatch.setattr(ro, "runner_urls", lambda: [])  # never look at the real endpoints
    freed = []

    async def free(urls, keep=""):
        freed.append(keep)
        return {"steps": ["unloaded qwen3.6"]}

    steps = asyncio.run(ro.ensure_ram_for_tool("mcp__image_gen__generate_image", snapshot=lambda: _snap(6.0), free=free))
    assert steps == ["unloaded qwen3.6"] and freed == [""]
