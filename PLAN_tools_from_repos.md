# Plan: what to take from the ten reviewed repos (2026-11-04)

Owner: "first add all that works for me into a plan then execute that plan". "Works for me" = runs on this
Mac (Apple Silicon, 48 GB unified memory, macOS) **and** moves a current goal: faster replies, less RAM,
fewer loops, smarter models, deep research. Repo facts below come from their READMEs (read by a fast
summariser), and performance numbers are the repos' own claims, so each item is verified here before it is
trusted. Rules kept: no Docker start/stop, no real-model load without need, nothing installed outside
its own folder, nothing written to the real `data/` while the app is running, one big model at a time.

## Verdicts

| Repo | Works on this Mac? | Goal it serves | Decision |
|---|---|---|---|
| Rapid-MLX | Yes (MLX, Apple Silicon, OpenAI-compatible) | speed, follow-up latency (prefix cache), RAM (quantized KV cache) | **Step 2-3: trial, then integrate if it wins** |
| local-deep-research | Yes (pip, macOS, REST + MCP, local LLMs) | deep research with citations next to the existing research mode | **Step 4: trial, connector off by default** |
| bitsandbytes | Yes (arm64 CPU, Metal for LLM.int8 / 4-bit) | RAM of the PyTorch workers (video, neural music), not GGUF chat | **Step 5: verify on Metal, then an opt-in flag** |
| (new, from local-llm-workbench) | idea only; its scripts expect `nvidia-smi` | measure tokens/s, first-token time, memory | **Step 1: own small benchmark script** |
| Unsloth (Studio), Soup | Yes (Unsloth: GGUF + MLX; Soup: partial MLX) | fine-tuning | Not now: no fine-tuning goal. The quants in use are already Unsloth's |
| nanobot, open-multi-agent | Yes (Python / Node) | agent loop, memory, approvals | Not now: Odysseus already has these; ideas only |
| flash-attention, llm-optimizer | No (CUDA/ROCm, server GPUs) | - | Excluded |

## Steps and how each is judged

1. **Benchmark script** `scripts/dev/bench_endpoint.py`: any OpenAI-compatible endpoint; measures first-token
   time, decode tokens/s, and a second request sharing a long prefix (prefix-cache effect), plus free-memory
   change from `memory_guard`. Done when: unit tests pass against the fake runner and it prints a comparable table.
2. **Rapid-MLX trial** in its own folder (`~/Documents/Docker/odysseus-mlx/`, Python 3.12 via `uv`),
   serving the 4 GB MLX coder model **already in Docker's model store** (read-only path, no download), on a scratch
   port. Done when: it answers `/v1/chat/completions`, the benchmark runs, and I know whether it can unload a model.
3. **Rapid-MLX integration**, only if step 2 shows a real win: a way for Odysseus to treat it as a managed local
   engine (listed in the picker, unloaded by "Optimise memory" / model switch, counted by the RAM guard).
   Done when: tests with a fake server pass and a scratch run shows the unload freeing memory.
4. **local-deep-research trial** in its own folder (`odysseus-ldr`), pointed at a local OpenAI-compatible endpoint.
   Done when: the service starts, a trivial query reaches the local model, and it registers as a Connector on a
   scratch Odysseus. Not added to the real app's database without the owner's go-ahead (script provided).
5. **bitsandbytes check**: import and quantize a small layer on Metal in a throwaway venv. If it works, add an
   opt-in `ODYSSEUS_MEDIA_QUANT=8bit|4bit` to the music/video workers (default off, falls back with a clear message).
   Cannot be verified on real music/video weights here (Hugging Face is unreachable from this sandbox).
6. **Close out**: tests, full suite, notes in this file, final report with measured numbers and what stays unproven.

## Execution log
Measured 2026-11-04 on this Mac (48 GB, M-series), single runs, so read them as indications:

1. **Benchmark script**: `scripts/dev/bench_endpoint.py` + `tests/test_bench_endpoint.py` (3 tests). Done.
2. **Rapid-MLX trial**: installed in `~/Documents/Docker/odysseus-mlx` (1.4 GB venv, Python 3.12 via uv), serving the 4 GB
   MLX coder 7B straight from Docker's model store (read-only, no download).

   | | Rapid-MLX (MLX 4-bit coder 7B) | Docker Model Runner (GGUF Q4_K_M qwen3-8B) |
   |---|---|---|
   | decode speed | 82 tok/s | 86 tok/s |
   | first token, 1,500-token prompt, cold | **0.80 s** | 2.48 s |
   | first token, same prompt again | 0.07 s (11x) | 0.07 s (36x) |
   | memory while loaded | +4.6 GB | +4.9 GB |

   Different models, one run each. Real gap: prompt processing (about 3x faster), which is what your 6,000-token agent prompts need. Idle unload
   verified: 4.59 GB -> 0.60 GB after 60 s with the endpoint still up. Telemetry is ON by default (PostHog); `rapid-mlx telemetry off` was run
   and the launcher sets RAPID_MLX_TELEMETRY=0 DO_NOT_TRACK=1 (one anonymous startup event may have been sent before it was turned off).
   Odysseus chats with it end to end (endpoint registered on a scratch server, both replies streamed, no errors).
3. **Integration**: no engine code needed (the app already speaks this API). `scripts/rapid_mlx.sh start|stop|status` starts it with
   `--lazy-load --idle-unload-seconds 60 --disable-model-downloads`, telemetry off, port 8081 (tested for real on 8082). Gaps: the RAM guard and
   "Optimise memory" only know Docker Model Runner and Ollama, so a Rapid-MLX model frees itself only through the idle timeout (default 60 s).
   To use it: `scripts/rapid_mlx.sh start <folder|alias>`, then in the model picker "+" add `http://127.0.0.1:8081/v1`.
   `rapid-mlx recipe` for this Mac recommends `qwen3.6-35b-4bit` (about 20 GB) as the fast pick and `qwen3.8-27b-4bit` (about 20 GB) as the
   smart pick. Not downloaded: `rapid-mlx pull qwen3.6-35b-4bit` (about 20 GB from Hugging Face) is the next step if wanted.
4. **local-deep-research**: installed in `~/Documents/Docker/odysseus-ldr` (2.1 GB venv). `ldr-mcp` (stdio) lists 8 tools (quick_research,
   detailed_research, generate_report, analyze_documents, search, list_search_engines, list_strategies, get_configuration). A scratch Odysseus
   connected to it as a Connector (status connected, 8 tools); its raw `search` returned real Wikipedia results; a research query reached the local
   model (Rapid-MLX loaded) but found no sources in this one attempt and said so instead of inventing any. So: plumbing verified, answer quality NOT.
   Settings that worked: LDR_LLM_PROVIDER=openai_endpoint, LDR_LLM_OPENAI_ENDPOINT_URL, LDR_LLM_OPENAI_ENDPOINT_API_KEY, LDR_LLM_MODEL.
   Data folder: `~/Library/Application Support/local-deep-research` (empty). NOT added to the real app: connector command
   `~/Documents/Docker/odysseus-ldr/.venv/bin/ldr-mcp`, env as above (add in Connectors > custom MCP, stdio).
5. **bitsandbytes**: torch 2.15 + bitsandbytes 0.50.2 on Metal: Linear8bitLt (int8 weights, ~1% error) and Linear4bit nf4 (uint8, ~10% max
   error) both run on mps. Toy layer only. NOT added to the music/video workers: no real weights can be fetched from this sandbox, and
   post-quantisation device placement is where this usually breaks. Next step when weights are available: try
   `BitsAndBytesConfig(load_in_8bit=True)` (transformers) / `PipelineQuantizationConfig` (diffusers) by hand first.
6. Not executed: Unsloth Studio, Soup (no fine-tuning goal), nanobot, open-multi-agent (overlap), flash-attention and llm-optimizer (NVIDIA/AMD only).

## Test matrix through a scratch Odysseus (2026-11-04, ~25 cases, memory / time / log errors monitored per case)

Setup: scratch Odysseus on :7871 (own database), Rapid-MLX on :8081 serving the 4 GB MLX coder 7B as `qwen2.5-coder-7b-4bit`, and
local-deep-research registered as a stdio Connector. The real app on :7860 was not touched (it has a login). Every case also recorded system
memory before/after, Rapid-MLX peak RSS (sampled each second) and new ERROR/Traceback lines in the Odysseus log: **+0 errors in every case**,
Rapid-MLX peak 5.5 GB, system pressure "normal" except short "warning" stretches caused by other apps (system used 32-42 GB of 48 GB).

| Case | Result | Notes |
|---|---|---|
| C1 endpoint registered, model listed | PASS | |
| C2 chat streams (incl. lazy load) | PASS | first event 0.07 s |
| C3 multi-turn memory | PASS | "teal" remembered |
| C4/C4b agent mode, native tool calls | PASS (3/5 attempts) | Odysseus sends tools natively (`native_tools=True`, 36 tools); the 7B model called the tool in 3 of 5 tries, answers matched the real output each time; in 2 it answered without running anything |
| C5 agent turns, big prompt prefix | INFO | 0.06 s to first event on the second turn (prefix cache) |
| C6 plan mode | PASS | plan text, no tool ran |
| C7 auto-switch router, one model | PASS | never switches away from the only model |
| C8 request fields accepted | PASS | `enable_thinking`, `presence_penalty`, stream usage all HTTP 200 |
| C9 research connector | PASS | connected, 8 tools |
| C10 agent -> approval -> tool | PASS | full cycle (call, approval, run, result); the model chose Odysseus's own `trigger_research` over the connector's `search` |
| C11 connector search, no model | PASS | 3 real Wikipedia results |
| C12 quick_research backed by Rapid-MLX | PASS | 3 sources found (the earlier 0-source run used 1 question per iteration); the 7B's summary was weak |
| C13 idle unload | PASS | memory freed after ~33 s idle, endpoint still up |
| C14 lazy reload after unload | PASS | 1.3 s total |
| C15 two chats at once | PASS | both completed (local calls are serialised) |
| C16 engine down, then restarted | PASS | clean error in 0.1 s, recovers after restart |
| C17 switch to a real Docker Model Runner model | SKIPPED | only 12 GB free; the guard-style check refused to load a ~10 GB model |

What the run taught (all folded into the launcher notes):
1. A bare local model folder has no tool-call parser, so tool calls arrive as plain text and Odysseus can't run them. Start with
   `RAPID_MLX_ARGS="--enable-auto-tool-choice --tool-call-parser qwen"` (named aliases pick theirs automatically). Fixed C4/C10.
2. Shell and connector tools wait for the user's approval in Odysseus (working as designed); a test or script has to approve.
3. After the engine has been down, Odysseus refuses it for 20 s (dead-host cooldown); wait that long after a restart.
4. A 7B coder is unreliable for agent work (3/5). Use the larger model for Agent mode (`qwen3.6-35b-4bit` is the one Rapid-MLX recommends here).
5. Odysseus has two research tools (its own `trigger_research` and the connector's); a small model picks either. Decide which one you want
   the agent to use, or disable the other.
Not covered: thinking-model behaviour on Rapid-MLX (this model has no thinking mode), vision, the 20 GB model, the real app on :7860.

## Rollout to the real app (started 2026-11-04, owner said "do it")

- `rapid-mlx pull qwen3.6-35b-4bit` (mlx-community/Qwen3.6-35B-A3B-4bit, 20.4 GB) started in the background; ~9.6 MB/s, ~35 min. Cache:
  `~/.cache/huggingface/hub/models--mlx-community--Qwen3.6-35B-A3B-4bit`. Hugging Face became reachable from the shell mid-session.
- `scripts/register_rapid_mlx.py` (6 tests) writes the endpoint (native tool calls on) and, with `--research`, the research connector into
  `data/app.db` after a timestamped backup; dry run by default; refuses while Odysseus answers on :7860. Real app was closed at the last check.
- Remaining, in order: (1) wait for the pull to finish; (2) `scripts/rapid_mlx.sh start qwen3.6-35b-4bit` (lazy, nothing in RAM yet);
  (3) one short request to verify it loads and answers, only if >= ~26 GB is available (the model needs ~20 GB and the RAM guard does not
  cover Rapid-MLX); (4) `.venv/bin/python scripts/register_rapid_mlx.py --model qwen3.6-35b-4bit --research --apply` with the app closed;
  (5) full suite, report.

### Rollout result (2026-11-04 ~20:10)

- Pulled `qwen3.6-35b-4bit` = mlx-community/Qwen3.6-35B-A3B-4bit, 15 files, 20,429 MB, 29m35s. **Provenance:** 11 of the 15 files came from the tool's own
  "R2" mirror and 4 from Hugging Face. All 5 large files (4 safetensors + tokenizer.json) match Hugging Face's published SHA-256, and the snapshot
  revision (38740b847e4c) matches the repo's. The small config files have no published checksum.
- Registered in the real app with `scripts/register_rapid_mlx.py --research --apply` while it was closed. Backup: `data/app.db.bak_rapidmlx_20261104_200658`.
  Integrity ok; endpoints 6 -> 7, connectors 24 -> 25, sessions unchanged. To undo: restore that file, or delete the endpoint "Rapid-MLX (local, Apple
  Silicon)" and the connector "Local Deep Research" in the app.
- Engine started with `scripts/rapid_mlx.sh start qwen3.6-35b-4bit` (idle, 0.4 GB, nothing loaded). It auto-detected `qwen3_coder_xml` tool calls and
  the `qwen3` reasoning parser; the optional 0.5 GB MTP speed-up add-on is NOT downloaded (waiting for the owner's yes).
- NOT done: the real load test of the 20 GB model: only 17 GB was free (needs ~26 with headroom), so it was skipped on purpose.
- Hazard found and fixed on the way: the RAM guard only knows Docker Model Runner, so the auto-switch router would have treated the 20 GB model as
  "fits" and switched to it in Plan mode on a Mac that cannot hold it. `estimate_gb()` (src/model_router.py) now estimates other local engines from the name
  (parameters x bits, +15%, +1.5 GB; checked against measured loads) and `/api/local-models/route` refuses a candidate that does not fit. Explicit picks by
  the user are not blocked.

### Close-out check (2026-11-04, session continuing the plan)

- Step 5 done: full suite `pytest tests` with the repo's default env: **6269 passed, 3 skipped, 0 failed** (3m40s), run against the shared working tree (other sessions' uncommitted edits included). Targeted run first: model_router, register_rapid_mlx, bench_endpoint, auto_route_js = 45 passed. No other pytest process was running.
- State at the check: Odysseus app (:7860) closed; Rapid-MLX engine idle on :8081 (pid 86259, nothing loaded); DMR empty; schema proxy up on :12436; free+inactive memory ~16 GB, swap 5.7 of 7.2 GB.
- Still open: (a) the real 20 GB load test of `qwen3.6-35b-4bit` (needs ~26 GB headroom, so it waits for the owner to free memory); (b) the 0.5 GB MTP add-on, waiting for the owner's yes; (c) the rollout files (`src/model_router.py`, `scripts/rapid_mlx.sh`, `scripts/register_rapid_mlx.py`, their tests) are still untracked, not committed.

### Real load test of qwen3.6-35b-4bit (2026-11-04 ~20:44, owner said "run it then")

- Gates: DMR empty, no pytest or other model, Odysseus app closed, free+inactive 16.4 GB (below the ~26 GB the plan asked for; run anyway on the owner's say-so), swap 5.4 of 7.2 GB. Sampled RSS and swap every 2 s (script and samples in the session scratchpad).
- Result: PASS. Cold request (load + answer) **17.6 s**, answer "ok"; warm request **0.14 s**, answer "Four"; HTTP 200, finish=stop, no reasoning text. Engine log: loaded as MLLM (vision lane), prefix cache capped at 4 GB, `[idle_unload]` after 70.8 s, endpoint stayed online. free+inactive went 15.9 -> 8.0 GB while loaded and back to 29 GB after the unload.
- Cost: **swap grew 5.4 -> 14.2 GB (+8.8 GB; swap file total now 15 GB, 1.2 GB left of it)** and stayed there after the unload (stale pages are only released when touched). Watchdog quiet (log still 5 lines).
- Gotcha: the server process RSS reads only ~1.2 GB while the model is resident (MLX memory is not counted in RSS), so the watchdog's 28 GB RSS rule and `ps` do not see it; use `vm.swapusage` and free+inactive instead. Loading it on a Mac with under ~26 GB available costs swap each time.
- Not tested: tool calling through Odysseus on this model, long prompts, the real app on :7860, the MTP add-on.

### MTP add-on (2026-11-04, owner said "do it")

`mlx-community/Qwen3.6-35B-A3B-MTP-4bit` pulled (495 MB, 6 files, 5 via the tool's mirror, 1 via HF); both checksummed files (model.safetensors, tokenizer.json) match
Hugging Face and the snapshot revision matches (0295b81421bf). The engine was restarted and logs "MTP: enabled automatically ... max_k=2" (speculative decoding).
Trade-off printed by the engine: with MTP on, **image input is off** for this model (restart with `--no-spec-decode` for pictures; `RAPID_MLX_ARGS=--no-spec-decode`).
In Odysseus this costs nothing today: `model_supports_vision` judges by name, treats `qwen3.6-35b-4bit` as text-only, and so never sends it pixels (pictures go through
the described-picture path). Speed gain NOT measured (the 20 GB model was never loaded: not enough free memory).

### Watchdog now counts a loaded Rapid-MLX model (2026-11-04)

`~/.local/bin/llm-watchdog.sh` (source copy `../llm-proxy/llm-watchdog.sh`) reads `:8081/health`; a loaded Rapid-MLX model counts in the "two big models" and "30B+ with any other model" rules. It still only unloads Docker models (Rapid-MLX's API will not unload its primary model: 409), so the Rapid-MLX model leaves by its idle timeout. Details, tests and rollback: `../PLAN-2026-11-04-local-ai-rollout.md` (last three bullets).

### The 35B under real load (2026-11-04 21:07-21:15, owner said "now")

Run with a watchdog that kills the engine the moment memory pressure leaves "normal" or free memory drops under 1 GB (the first attempt at 22 GB free was stopped at
pressure "warning", 8.5 GB free, mid-load; the second at 26 GB free completed).

| | result |
|---|---|
| load | first request 7.6 s including the load; +17.1 GB "used" (Activity Monitor's count) |
| speed (MTP on, thinking off, one run) | **112-126 tok/s** after warm-up (25 tok/s on the very first request), first token 1.26 s on a ~1,500-token prompt, 0.05 s when repeated (24x) |
| through Odysseus: chat, multi-turn, reasoning answer | pass (answer mentions scattering, correct) |
| native tool calling, 5 attempts | **5/5 executed, 5/5 answers matched the real output** (the 7B coder: 3/5) |
| plan mode | plan, mutating tools blocked by design; read-only exploration tools are allowed (my first check was too strict) |
| deep research, quick_research | NOT verified: Wikipedia engine is weak (0 results for "Rayleigh scattering"; odd matches for "MLX"), arXiv search works (25 results); the one full run on arXiv died because the watchdog stopped the engine |
| memory | whole system 41-42 GB used with the model resident; free memory fell to 4.4 GB and pressure to "warning" after a few minutes, so the watchdog stopped it |

Conclusion: the 35B works and is fast and reliable with tools, but on this Mac with the usual apps open it sits at the edge of memory (about 6 GB headroom). Close browsers
before using it, or run a smaller model for everyday work. The watchdog script (scratchpad `watchdog.py`) is a good pattern to keep when loading big models.

### Fixes after the rollout (2026-11-04 ~21:30, owner asked "any fixes")

1. `agent_loop._domain_rules_for_tools` skips a tool group that has no rules text (the unfinished decensor group crashed every turn that picked its tools with
   `KeyError: 'decensor'`; seen in the app log at 20:58). Test: tests/test_domain_rules_missing.py. A real "decensor" rules block is still to be written by whoever finishes that agent.
2. Auto-naming a chat (`routes/chat_helpers.auto_name_session`): when the model cannot be asked (memory guard 409, server down) it now logs one warning line
   instead of an ERROR traceback and titles the chat from the first six words (`fallback_title`); it never renames a chat the user already named.
3. "Optimise memory" now also stops the Rapid-MLX engine started by `scripts/rapid_mlx.sh` (`stop_rapid_mlx`, src/ram_optimizer.py): only the process in
   `logs/rapid-mlx.pid` and only if its command line is really rapid-mlx; never when the current chat model is one it serves. Another session had changed
   this file meanwhile (settle-after-unload logic, uncensor tools in the heavy-tool list); the new step was added alongside, not over, those changes.
4. Reviewed the real app's log since it was opened (21:14): no errors, no tracebacks; "Local Deep Research" connected with 8 tools. (An earlier scare about a "storm of
   MCP closing errors" was my own mistake: the time-only filter pulled in yesterday's evening restarts.)
