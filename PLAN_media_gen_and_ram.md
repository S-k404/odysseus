# Plan: media generation fixes, menu bar icon, "free up RAM"

Written 2026-11-04 (session start, before any code change). Nothing below has been
implemented yet. Read `MAC_APP_HANDOFF.md` first for the rules (no Docker, no real
model loads in tests, don't quit the app while another session builds or runs pytest).

The request: fix image gen, video gen, music gen, image decensor and "other features"
in the Mac app; fix the menu bar icon; add a "free up RAM" step before models load and
a menu bar shortcut / Optimise button.

## What I checked (2026-11-04 00:00-00:10 IST)

| Area | Finding | Checked how |
|---|---|---|
| Image gen (chat) | Works per the 2026-11-03 live check: picker -> stable-diffusion -> 512x512 in 20 s. Size is fixed at 512x512 in the chat route. | Notes only; not re-run today |
| Image gen (MCP `image_gen`) | Server starts and lists `generate_image` (defaults to gpt-image-1, 1024x1024, a cloud model). Not called. | tools/list handshake |
| Video gen | **Does not exist.** Only a capability constant (`CAP_VIDEO_GENERATION`, `src/model_capabilities.py`); the Cookbook actively removes the "Video" use-case (`static/js/cookbook-hwfit.js` ~2032). No route, tool or UI. | grep |
| Music gen | `mcp_servers/music_gen_server.py` is a **procedural synth** (chords/melody to WAV) plus Kokoro TTS and Whisper through Speaches on :8000. No neural music model. Speaches runs only in Docker, which is off, so speech/transcribe fail right now. | read the file |
| Decensor | `uncensor` MCP (`odysseus-image-tools/uncensor_server.py`, SDXL inpainting, ~6.6 GB weights, ~8 GB RAM loaded) is registered and enabled in `data/app.db`; starts and lists its tools. Whether the model actually calls it correctly from a chat is **not tested**. | handshake + DB row |
| Menu bar icon | Installed build (21:51) draws a ring (memory 72%), hollow core (idle) and an orbiting dot, at the right of the bar. It renders; what the user finds wrong is **unknown**. It reads as a disc or spinner rather than an Odysseus mark. | screenshot crop |
| RAM today | 34 of 48 GB used with **no** model loaded, swap 1.9 GB, pressure normal. Biggest process is the Docker VM (5.7 GB). Existing protection: unload other DMR models before a load, release on pick/new chat, RAM guard refusal, memory watchdog, launchd watchdog. There is no user-triggered "free RAM" and nothing that frees non-model memory (uncensor, SD, Ollama together). | ps, `MAC_APP_STATUS.md` |

## Part A: Free up RAM (no open questions; do first)

Goal: one function that frees what Odysseus can safely free, used automatically before a
load and on demand from the app and the menu bar.

1. `src/ram_optimizer.py`: `free_ram(keep=None)` returns the steps taken and
   before/after numbers from `memory_guard.snapshot()` (not hand-rolled `vm_stat`).
   Steps, in order: unload DMR models except `keep` (never one that is `in_use`);
   Ollama `keep_alive: 0`; Stable Diffusion in DMR when idle; ask the `uncensor` server
   to run `unload_uncensor_model`; drop Odysseus's own caches. It must **not** kill other
   apps and must **not** run `purge` (needs sudo). It may list the biggest other apps as
   a suggestion only.
2. Before a load: in `_local_model_slot` / the RAM guard path (`src/llm_core.py`,
   `src/memory_guard.py`), when the guard would refuse, run `free_ram(keep=model)` and
   re-check before refusing. Show "Freeing memory..." in the chat while it runs.
3. API: `POST /api/local-models/optimize` (next to `/release` in
   `routes/local_model_routes.py`) returning freed GB and the steps.
4. UI: an "Optimise memory" button (model picker footer and Settings), result as a toast
   ("Freed 9.4 GB, 31 GB free").
5. Menu bar (`swift/MenuBarStats.swift`, `swift/MenuBarView.swift`): "Optimise memory"
   item and a button on the card. It calls the endpoint when the server is up and falls
   back to the existing direct DMR unload (`--menubar-unload-all`) when it is not. Add a
   `--menubar-optimise` flag so it can be checked without a screen.
6. Tests: unit tests with stubbed runners (per `tests/TESTING_STANDARD.md`), then the
   scratch server + `scripts/dev/fake_dmr.py` for the end-to-end check. No real model
   loads or unloads.

## Part B: Fix what exists (image gen, decensor, music, "other features")

Start by reproducing, not guessing. Each item gets a failing check first.

1. Image gen: run the picker flow on the scratch server; then try larger sizes (the chat
   route is fixed at 512x512), and decide whether the `image_gen` MCP should default to a
   local model instead of gpt-image-1 (the user wants local models only).
2. Decensor: drive `find_censored_regions` and `uncensor_image` on a synthetic mosaic
   through the MCP handshake, then through an agent turn on the scratch server. Check it
   frees its ~8 GB (it self-unloads after 5 idle minutes) and that Part A can trigger the
   unload.
3. Music: make the failure of Kokoro/Whisper clear when Speaches (Docker) is down instead
   of a stack trace; keep the procedural synth working. Neural music is Part C.
4. "Other features": sweep Settings -> System -> Services and the Connectors window for
   red items once the above is done, and list them for the user rather than fixing blind.

## Part C: New capability, needs a decision (don't start without it)

- **Video generation** and **neural music generation** are new features, not fixes. Each
  needs a model download of several GB and a RAM budget that has to coexist with the
  chat model (one big model at a time is the rule). Candidates to discuss: a small
  text-to-video model for video; MusicGen-small or ACE-Step for music, run on MPS from
  `odysseus-image-tools`' venv pattern, loaded on demand and unloaded through Part A.

## Part D: Menu bar icon (needs the user's answer)

Possibilities: it looks like a disc/spinner rather than the Odysseus mark; it animates
when the user wants it still; the size or position is off; the click does the wrong
thing. Once told which, change `MenuBarIcon.image` in `swift/MenuBarView.swift`
(candidate: draw the app's own mark from `odysseus.icns` as a template image, keep the
memory ring as a thin overlay). Verify by screenshot crop as above. Installing needs
`./build-macos-app.sh` with the app quit, so check `pgrep -fl "build-macos-app|pytest"`
and ask before quitting; another session was running a large pytest at 00:00.

## Open questions for the user

1. What is wrong with the menu bar icon (look, animation, size, click)?
2. Which failures did you actually see in image / music / decensor (an error message or
   what happened)? Without it Part B is a reproduction pass.
3. Do you want video and neural music generation added (Part C), and are multi-GB
   downloads fine?

## Order

A (RAM) -> B (reproduce and fix) -> D (icon, one rebuild together with A's Swift change)
-> C if approved.

## Status 2026-11-04 (later the same night)

The owner answered: make the menu bar less crowded (animate the icon, not the card);
texting any model errors out and sits on "generating images"; make models specific,
load only on request, plan with the frontier model then hand off.

Done (tests: full suite 6079 passed, 3 skipped):
- Part A backend: `src/ram_optimizer.py`, `POST /api/local-models/optimize`, and the load guard
  now frees RAM before it refuses (`llm_core._load_block_reason_after_freeing`).
- "Optimise memory": picker footer button (modelPicker.js), menu bar button and menu row,
  `--menubar-optimise` flag.
- Menu bar card redesigned: no animation on open, no boxed tiles (swift/MenuBarView.swift).
  NOT installed: the app is not running; `./build-macos-app.sh` still has to be run.
- "Stuck generating images": a hard time limit and a guaranteed terminal event on the
  image path (`ODYSSEUS_IMAGE_GEN_TIMEOUT`, default 600 s); a model runner's pinned list now
  decides what is an image model even if the chat endpoint is disabled. Not reproduced with
  the saved config; the Mac server had been quit at 00:05.
- Plan handoff: "Run with" selector on the plan card.

Still open: Part B (decensor end-to-end, music error messages), Part C (video, neural music),
a browser check of the picker button and plan card (Chrome extension was not connected).

Decensor: paused and handed to Antigravity at the owner's request; see PLAN_decensor.md.

Correction (2026-11-04 ~01:45): the table above says speech and transcription fail because Speaches only
runs in Docker, which is off. At 01:45 Docker Desktop was running and a container published Speaches on
127.0.0.1:8000; `generate_speech_track` returned a real MP3. Speech works whenever that container is up;
the new clear error appears only when it is not.

## Status 2026-11-04 ~02:00 (after "do them all")

Installed: new menu bar app in /Applications/Odysseus.app (built 01:09; the previous app is backed up in the Claude scratchpad). Not launched.
Music: clear Speaches errors (verified against a down port), new `generate_music_neural` (MusicGen, ~2.4 GB, asks before the first download).
Video: new built-in server `video_gen` / tool `generate_video` (default Lightricks/LTX-Video via diffusers; override with ODYSSEUS_VIDEO_MODEL).
Both neural tools run in a short-lived worker process (mcp_servers/media_runner.py, media_workers/), so the model is in memory only while a clip is made, and `ensure_ram_for_tool` unloads other models first when it would not fit.
NOT verified with real weights: Hugging Face is unreachable from the Claude sandbox, so MusicGen and the video model were never loaded; the worker scripts are untested against a real model. Everything around them (consent, memory check, worker protocol, MP4 encoding with ffmpeg, MCP handshake) is tested.
Decensor: paused for Antigravity, see PLAN_decensor.md.
Full suite: 6098 passed, 3 skipped.

## Status 2026-11-04 ~03:00: auto-switch and smart models

Owner screenshots showed: a chat left on stable-diffusion after a picture, "Can't find variable: _isBg" after an image,
and a hand-picked 1.5B coder answering a plan with "Reference context received.".
- `_isBg` fixed (static/js/chat.js, old bug: a loop-scoped variable used after the loop).
- `src/model_router.py` + `POST /api/local-models/route`: picks the model that fits the message and fits in RAM
  (asks the real load guard). Picture request -> image model; next text message -> back to a text model; attached picture ->
  vision model (or the image model for an edit); plan mode -> biggest non-vision model that fits; agent/tools/code ->
  at least 7B; everything else keeps the current model. Unknown current models are never touched.
- Browser: `static/js/autoRoute.js` runs just before a message is sent (hook in chat.js), switches through the picker's
  tested `_pick` (which unloads the model being left), toasts "Auto: <reason>". It never blocks a send (4 s limit, any
  failure keeps the model). Toggle: "Auto-switch models" in the model picker footer (on by default, remembered in
  localStorage `odysseus-auto-route`). Plan card "Run with" defaults to "automatic".
- Tests: tests/test_model_router.py (13), tests/test_auto_route_js.py (6, real autoRoute.js under Node). Full suite 6117 passed, 3 skipped.
- NOT checked in a browser (Chrome extension not connected). The Python endpoint needs the app restarted (Cmd-Q, reopen);
  until then the browser gets a 404 from /route and simply doesn't switch.

## Status 2026-11-04 ~04:00: image context, Plan mode, and bugs found by running it in Chrome

- Owner: "once I generated an image, the agent uses it as context and doesn't switch if I ask about it in the same chat."
  Router (`src/model_router.py`): a chat with a generated picture on screen (`last_image`) classifies a question about it as
  `about_image` (never a model switch, never a vision-model switch; the picture is attached as context) and a change request
  ("make it darker") as `image_edit_last` (image model, picture attached). Browser (`static/js/autoRoute.js`): attaches the newest
  `img.generated-image` through the normal attachment path, so the server gives it to the model as pixels (vision model) or as the
  cached description (text model, existing `analyze_image_with_vl_result`). After a picture finishes, the chat switches back to the
  text model it came from (`autoRouteAfterTurn`).
- Plan mode: the composer's Plan pill had been dropped from the page (only Tab toggled it). `ensurePlanPill()` in static/app.js
  adds it back next to Thinking/Context; a plan reply is now a card ("Proposed plan", Execute / Run with / Keep planning / Clear).
- Bugs that only a real browser showed (fixed): (1) `modelPicker.js` is loaded twice, so `listChatModels/switchToModel` read the
  uninitialised copy and auto-switch silently never fired: hooks now live on `window.__odysseusPicker`; (2) a brand-new chat is
  not in the session list, and the list lags a switch: the current model for routing prefers this chat's latest pick;
  (3) `selectedRouteForSend` in chat.js is captured before routing and the server honours it over the session's model, so the
  message still went to the old model: it is refreshed after a switch; (4) `_isBg` ReferenceError after an image (old bug).
- Tests: 19 router tests, 10 autoRoute Node tests; full suite 6135 passed, 3 skipped. Real-Chrome scripts (puppeteer-core in the
  Claude scratchpad, scratch server on 7871 with a fake runner that also serves images) covered: Plan pill, picker footer buttons,
  plan card, draw -> auto image model -> back to text, ask about the picture -> attached, no switch.
- Not verified: with a real vision setup (`vision_model` setting) the description quality; the Mac app itself (needs Cmd-Q and reopen).

## Status 2026-11-04 ~05:00: loops, faster follow-ups, local-first image tool, repo review

- Thinking loops, three layers: (1) `_apply_local_anti_loop` (src/llm_core.py): presence_penalty 0.5 default for every local thinking
  model (was MiniMax-only); a preset's own value wins; the retry after a loop is still stronger (1.0). The 0.5 is a judgement call,
  not tuned on these models. (2) `_sentence_loop` also catches one sentence repeated 5 times in the last 12. (3) `is_simple_chat`
  (src/model_router.py) + chat_stream: short plain messages ("say hi in five words") are sent with thinking off; opt out with
  ODYSSEUS_SMART_THINKING=0. Verified in Chrome: "say hi" got enable_thinking:false, "why is the sky blue?" kept thinking.
- Faster picture follow-ups: attach a picture once per chat (autoRoute.js); a picture this app generated is described by its own
  prompt/caption instantly (`_generated_image_context`, src/chat_handler.py) instead of loading a vision model; descriptions are cached by
  image content (`_image_hash_cache_path`). Verified in Chrome: two questions about one picture = one upload.
- Agent `generate_image` tool (mcp_servers/image_gen_server.py): local image model first, 512x512 default for local models, frees RAM
  before loading (`ensure_ram_for_tool`, also on the legacy `_call_mcp_tool` path). Unit-tested only; not run against a real SD model.
- Repos reviewed from README summaries only (nothing installed): Rapid-MLX (Apple Silicon MLX server, OpenAI-compatible) is the one
  worth trying; local-deep-research (MCP/REST research agent) second. Unsloth/bitsandbytes/Soup are training/quantisation tools;
  flash-attention and llm-optimizer are NVIDIA/AMD only.
- Full suite: 6147 passed, 3 skipped.
