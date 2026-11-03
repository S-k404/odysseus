"""Fake Docker Model Runner for safe end-to-end checks (never loads a real model).

    python3 scripts/dev/fake_dmr.py PORT LOGFILE

Behaves like DMR where Odysseus cares: a chat request "loads" its model,
/engines/unload removes models, /engines/ps lists what is loaded, and
/engines/status reports vLLM-Metal so the RAM guard has something to refuse.
Starts with two models resident. Every request is appended to LOGFILE as JSON.

Real DMR quirks it reproduces:
  - replies name the model by its file path (…/model.gguf), not its tag;
  - a <think>…</think> block ahead of the answer.
Its model list also holds a speech, an image and an embedding model, so the
chat picker's non-chat filter can be checked.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
LOG = sys.argv[2]
MODELS = {
    "ai/small-chat:1": "gguf",
    "ai/big-chat:2": "gguf",
    "mlx/vllm-coder:latest": "safetensors",
    "speaches-ai/Kokoro-82M-v1.0-ONNX": "onnx",
    "docker.io/ai/stable-diffusion:latest": "diffusers",
    "huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M": "gguf",
}
loaded = {"ai/big-chat:2", "ai/small-chat:1"}  # two models resident at start


def log(entry):
    entry["t"] = round(time.time(), 3)
    entry["loaded_after"] = sorted(loaded)
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("?")[0]
        log({"method": "GET", "path": p})
        if p in ("/engines/v1/models", "/v1/models"):
            return self._json({"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]})
        if p == "/models":
            return self._json([{"id": f"sha256:{i}", "tags": [m], "config": {"format": f, "context_size": 32768}}
                               for i, (m, f) in enumerate(MODELS.items())])
        if p == "/engines/ps":
            return self._json([{"backend_name": "llama.cpp", "model_name": m, "mode": "completion"} for m in sorted(loaded)])
        if p == "/engines/status":
            return self._json({"llama.cpp": "Running: llama.cpp metal", "vllm": "Running: vllm-metal v0.2", "mlx": "Not Installed"})
        if p == "/engines/_configure":
            return self._json([])
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        body = self._body()
        if p == "/engines/unload":
            for m in body.get("models") or []:
                loaded.discard(m)
            log({"method": "POST", "path": p, "models": body.get("models")})
            return self._json({"unloaded_runners": len(body.get("models") or [])})
        if p.endswith("/chat/completions"):
            model = body.get("model")
            loaded.add(model)
            log({"method": "POST", "path": p, "model": model, "stream": body.get("stream")})
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in ["<think>Let me think.</think>", "Hello", " from ", model]:
                    chunk = {"id": "x", "object": "chat.completion.chunk", "model": "/Users/x/.docker/models/bundles/sha256/abc123/model/model.gguf",
                             "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                done = {"id": "x", "object": "chat.completion.chunk", "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
                return
            return self._json({"id": "x", "object": "chat.completion", "model": model,
                               "choices": [{"index": 0, "message": {"role": "assistant", "content": "Short title"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}})
        log({"method": "POST", "path": p})
        return self._json({"error": "not found"}, 404)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
