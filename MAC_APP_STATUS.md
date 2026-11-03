# Odysseus Mac app: status and plans

Last updated 2026-11-03. How to work on it safely, and where things live:
`MAC_APP_HANDOFF.md`. Goal: Odysseus on the Mac should look and feel like
Claude Desktop, run local models only, and never take the Mac down by loading
too many models at once.

## Status

### Done and verified

**Claude Desktop look**
- Composer: one model picker (Specialists / All models), with a single Thinking
  control and a single Context control (16k / 32k / 64k / Max). The context
  setting is a cap; it never raises a model past the size it is served with.
- Chat transcript (`static/claude-skin.css` sections 10–12):
  - Replies have no card, and the model name is a muted caption.
  - Your messages are a soft bubble with hover actions.
  - The thinking toggle is grey.
- Welcome screen shows a "Good afternoon"-style greeting.
- Sidebar:
  - "Recents" list with titles only (the model is in the tooltip).
  - The nav labels now match what they open: Cookbook, Connectors.
- Connectors window (`static/js/connectors.js`):
  - Shows live MCP server status.
  - Installed / Discover / Add tabs, with sign-in by pasting back the callback URL.
  - Discover lists a catalog of open-source servers (Notion, Google Workspace,
    GitHub, Figma, Blender, Docker, n8n, Exa, Context7, DeepWiki, Hugging Face,
    filesystem, git, …).
- Account menu: no placeholder plans or Learn items. Logout works.
- Reply captions show just the model name. Docker reports the answering model as
  a file path (`…/model.gguf`), which used to print as "model → model"; the
  arrow now appears only when a different model really answered.
- The thinking toggle reads "Thought process" and stays fixed; the caret shows
  open or closed.
- The chat model picker hides speech and embedding models (Kokoro, Whisper,
  nomic-embed). They stay available in the voice and memory settings.
- Image generation is in the picker again, under its own "Image generation"
  heading (stable-diffusion, gpt-image, flux...). A chat on one of those models
  generates an image (or edits an attached one; the server routes by model id)
  and the composer drops the Agent|Chat toggle and the Thinking/Context pills.
  The hiding had removed the only UI way in. `isImageModelId` (modelSort.js)
  mirrors `src/image_model_ids.py`; a test keeps them in step. Checked in
  headless Chrome against the scratch server with the fake runner; a live
  Stable Diffusion run through the UI has not been tried (it needs ~20 GB free).
  The chat route generates at a fixed 512x512.
- Light mode: a built-in **claude-light** theme (Settings → Appearance) with
  Claude Desktop's cream page, darker sidebar, white composer and terracotta
  accent. Checked in headless Chrome against the scratch server: welcome, chat
  and picker. The older `light` and `paper` themes also work with the skin.
  Known: the welcome tip and "Nobody" label are very faint in every theme
  (opacity .2 / .25, from upstream).
- The picker no longer lists the untagged `sha256:…` copies that
  `docker model package` leaves behind. One is hidden only when a tagged model in
  the list has the same weights (`hide_untagged_duplicates` in
  `src/docker_model_runner.py`); an untagged model with no tagged twin, or one
  you pinned, still shows. Settings still lists everything.

**Mac app wrapper** (`swift/OdysseusApp.swift`)
- Handles JS dialogs, file pickers, downloads, external links and reopening
  the window.
- Has the Homebrew PATH, so npx / uvx / docker MCP servers start.
- The server log goes to `logs/odysseus-app.log`.
- If the server stops during startup, the splash screen shows why. This was
  type-checked only; it hasn't been seen on screen yet.

**Switching models and handoff** (checked on the scratch server with the fake
runner; no real model was touched)
- Switching between turns in a chat: the new model gets the whole conversation
  (earlier user messages, the other model's replies with the thinking block
  removed, and the new question), the old model is unloaded before the new one
  loads, each reply keeps the caption of the model that wrote it, and the chat
  remembers its model across a reload.
- Switching while a reply is streaming: the reply finishes on the old model and
  keeps its caption, the unload waits until it is done, and the next message goes
  to the new model.
- Switching to a model the RAM guard refuses: the chat shows why, nothing loads,
  and switching back works. The refused message is not lost; it is sent along with
  the next one.
- Project chats: same results, including after closing and reopening the chat from
  the sidebar. A project is only a folder label; it adds no instructions or files
  to the conversation.
- A turn that used tools (native tool calls on a qwen3-style model) can be handed
  to a model on the other tool path and back. Only the text carries over, as it
  does within one model; the tool call itself is not replayed to the next model.
- Fixed: the picker label could show the old model after a switch while the chat
  really used the new one. A sessions refresh sent at the same moment as the
  model-save request could answer first and overwrite the pick
  (`static/js/modelPickReconcile.js`, applied in `loadSessions`). 4 of 4 repeats
  showed it before the fix, 0 of 6 after.

**Feel and everyday use**
- **Projects page:** sidebar > Projects opens a dialog listing every project with
  its chat count and last activity, a search box, and one click to open the
  project's latest chat or start a new one in it (the small + beside it still
  creates a project). Built from the sidebar's own folder data
  (`static/js/projectsPage.js`). "Updated … ago" reads the server's UTC times
  correctly (they carry no zone and were showing 5 h old in India).
- **Welcome screen:** the tip and the Nobody toggle were drawn at 20-25% opacity,
  nearly invisible; now 55-60%. Tips show Mac shortcuts (⌘K, ⌘N, ⌘, , ⌘B) on a
  Mac and Ctrl elsewhere.
- **Narrow windows:** the Thinking and Context pills no longer wrap onto two
  lines; below 900 px the Context pill shrinks to its icon.
- **Mac window:** remembers where you left it (needs the app rebuilt).

**Reasoning loops and runaway thinking (every model)**
- `_DegenerateStreamGuard` (`src/llm_core.py`) watches every stream for: one token
  repeated, one phrase repeated, a full window of sentences with few different
  ones, text that compresses like a loop (0.14 for thinking, 0.10 for answers;
  ordinary code and docs never went below 0.171 over 4,157 windows), and thinking
  past its ceiling (the Thinking pill's budget x1.5 on self-hosted servers, else
  24,000 tokens; it used to be only a label there).
- A trip during thinking, before an answer starts, closes the request and retries
  once with thinking off (`chat_template_kwargs.enable_thinking=false`, Ollama
  `think:false`, gpt-oss low effort, plus `presence_penalty` 1.0 and a short
  "answer directly" note). Covers OpenAI-compatible servers (Docker runner,
  llama.cpp, LM Studio, vLLM) and Ollama native; Anthropic streams stop with an
  error. A second loop, or a loop after the answer started, ends with a clear error.
- Checked on qwen3-8b through the real runner: thinking-off is honoured, the old
  flags were not, a forced trip retried and answered, and 3,000 tokens of honest
  reasoning was left alone. Not seen: a spontaneous Qwen3.6 loop.

**Keeping the Mac alive** (`src/memory_guard.py`, `src/docker_model_runner.py`)
- Before a model loads, its estimated footprint must fit in what is free plus what
  unloading the other models returns, less a reserve of 10% of RAM (at least
  4 GB). The footprint is the weights, the KV cache at the served context (read
  from the model's own metadata: layers, KV heads, head size, hybrid attention)
  and 1.5 GB of buffers. Against measured loads: qwen3.6-35b @128k estimate 18.3
  GB (measured 19), qwen3-8b @32k 10.7 (10), qwen3-vl-30b @16k 20.3 (20). Memory is
  counted like Activity Monitor (app + wired + compressed). A load that would push
  the Mac into swap is refused with the numbers and a way to override
  (`ODYSSEUS_RAM_GUARD=0`). On the 48 GB Mac with ~27 GB used by other apps,
  Qwen3.6 is refused until about 4 GB more is freed.
- A watchdog unloads every chat model when macOS reports critical memory pressure
  on two checks in a row (10 s), and writes `logs/memory-guard.json`.
  `ODYSSEUS_MEMORY_GUARD=0` turns it off.

**Menu bar item** (`swift/MenuBarStats.swift`)
- A status item next to the clock: icon plus the loaded weights ("14G", or a
  warning sign under memory pressure). Its menu shows server status, each loaded
  model with size and context, memory in use, available, swap, pressure, CPU
  load, any emergency unload, and actions: Unload all models, Open Odysseus,
  Show server log, Quit. It reads the runner and the kernel directly, refreshes
  every 5 s, and needs no login. Needs the app rebuilt (`./build-macos-app.sh`).

**Local model safety** (Docker Model Runner on 127.0.0.1:12434)
- Odysseus generates with one local model at a time. Before a model loads,
  the others are unloaded (`src/docker_model_runner.py`, `_local_model_slot`
  in `src/llm_core.py`).
- Picking a model, or starting a new chat, unloads the other models right away
  (`POST /api/local-models/release`). It is skipped while a reply is
  generating. Verified end to end against a fake model runner.
- Ollama gets the same treatment (`src/ollama_runner.py`, `keep_alive: 0`): the
  old model is unloaded on a switch and by the memory watchdog. Verified on the
  real `qwen2.5:1.5b`: loaded, then unloaded by switching to another model.
- Safetensors models on the vLLM-Metal backend are refused, because that
  backend reserves about 90% of RAM. The chat explains why. Override with
  `ODYSSEUS_ALLOW_VLLM_METAL=1`.
- Local Stable Diffusion image generation waits its turn like chat does.
- Startup loads no model. Checked with the scheduler on and the UI open for
  30 s: zero requests reached the model runner. Startup warmups are off, and
  every active scheduled task is event-triggered.
- Measured RAM per model:

  | Model | Context | RAM |
  |---|---|---|
  | qwen3.6-35b | 128k | 19 GB |
  | qwen3-vl-30b | 16k | 20 GB |
  | qwen3-8b | 32k | 10 GB |
  | coder-1.5b | 32k | 2.4 GB |

- The launchd watchdog (`com.shamit.llm-watchdog`) is a second safety net:
  every 30 s it unloads all models if two big ones are resident or model
  memory passes 28 GB.

**Conflicts between the Docker copy and the Mac app**
- Only one server can use `data/` at a time (`src/instance_lock.py`). A
  second one refuses to start and names the server that holds the folder.
  Verified with two servers. Turn off with `ODYSSEUS_SINGLE_INSTANCE=0`.
- Quitting and reopening the Mac app right away used to fail with "The Odysseus
  server stopped during startup": the old server takes about 5 s to close its MCP
  servers and still held the folder, so the new one refused to start. A server
  that is shutting down now marks its claim "stopping", and a new one waits up to
  30 s for it (`InstanceLock.mark_stopping`). A server that is not stopping, such
  as the Docker copy, is still refused at once. Reproduced on a scratch folder
  before the fix, and checked after it with a 6 s shutdown: the new server waited
  about 8 s, then started.
- The app now writes the server log in append mode. Before, the old and new
  server wrote at their own offsets and overwrote each other, which scrambled the
  log and hid the real error from the startup screen. This part needs the app
  rebuilt (`./build-macos-app.sh`); the waiting needs no rebuild.
- `.env` is shared with Docker. When running natively, Docker service URLs
  such as `http://speaches:8000` are pointed at the ports Docker publishes on
  127.0.0.1 (`src/native_hosts.py`).

**MCP servers**
- All 25 built-in servers (24 Python plus the npx browser one, 107 tools) start
  natively with no Docker. Real calls checked: arXiv search, memory, SQLite.
- Agents find MCP tools without ChromaDB. The tool index needs ChromaDB, and
  without it a tool-calling model (any `qwen3`, `gemini`, `gpt`… name) used to be
  offered no MCP tool at all. `keyword_mcp_tools` (`src/tool_index.py`) now picks
  up to 8 by words in the request: server names, tool names, and at least two
  description words. Checked end to end on a `qwen3`-named fake model: "arxiv
  papers" gets the arXiv tools, "hello" gets none. With ChromaDB up the normal
  retrieval is still used first.
- Fixes:
  - Obsidian vault paths.
  - ECE inventory BOM parsing.
  - Onshape user line.
  - The repo-root lookup in the CAD, PCB, project, music and computer-use
    servers.
- PCB maker runs real `kicad-cli` DRC/ERC.

**Other agents**
- **Antigravity (Gemini)** joins Claude Code and Codex in Settings → Integrations
  → Add → **Antigravity Agent**. It shows install commands that download a skill
  bundle (`integrations/antigravity/`, served at `/api/antigravity/plugin.zip`)
  into `~/.gemini/config/skills/`, where Antigravity discovers skills. At runtime
  it uses the same scope-gated `/api/codex/*` API as the others. Checked: the
  menu entry, token creation, and the generated commands run end to end against
  the scratch server in a throwaway `HOME`. Not installed into your real
  `~/.gemini/config`; run the Settings commands when you want that.
- Gemini and Gemma models used as Odysseus's own agent take the same tool-calling
  path as qwen3, so they get the MCP fix above.

**Optional packages (Cookbook → Dependencies)**
- Installed into `.venv`: `playwright`, `hf_transfer`, `rembg`, and the `sam_mask`
  set (`torch` 2.15 with MPS, `transformers` 5.22, `accelerate`, `torchvision`).
  No existing package changed; `pip check` is clean; `onnxruntime` and
  `fastembed` still work. `playwright` browsers are not downloaded.
- Not installable here: `realesrgan` (its `basicsr` dependency won't build on
  Python 3.14; Docker patches it in `docker/build-realesrgan-wheels.sh`) and
  `APFEL` (not a pip package).

**Tests:** the full suite passes. New tests cover the instance lock, native
hosts, and the model runner guard and unload.

### Needs a step from you
1. ~~Quit and reopen Odysseus.~~ Done 2026-11-03 20:24: the rebuilt app (menu bar
   item, log append fix, relaunch wait) is installed and running. The previous
   build is kept in `dist/Odysseus.app.previous`; delete it when you are happy.
2. **Before the next Docker run:** `docker compose up -d --build`. The Docker
   image doesn't have the unload, guard, loop-protection or single-server
   changes until it is rebuilt.
3. **Try Qwen3.6 for real.** Loop recovery and thinking-off are checked on
   qwen3-8b only. Qwen3.6-35b needs about 18 GB free; the RAM guard refuses it
   until you free memory (27 of 48 GB were in use by other apps).
4. **Look at the menu bar icon** and say if anything is off. It was checked from
   a test copy by its position and menu, not by eye.
5. **Optional theme:** your saved theme is a custom blue/red palette with the
   rain effect. Settings → Appearance → **claude** (dark) or **claude-light**
   gives the Claude Desktop colours and no background effect.

### Known gaps
- ChromaDB, SearXNG and Speaches only run inside the Docker stack. While Docker
  is off, the Mac app has no vector memory or document search, no SearXNG web
  search, and no TTS/STT.
- With ChromaDB down, MCP tool choice is by words only, so a vague request
  ("look into that board") gets no MCP tool until it names one.
- Branch history: this work is 509 commits behind upstream
  `pewdiepie-archdaemon/odysseus`. Some MCP servers in `mcp_servers/` (arxiv,
  coursera, game_save, sqlite_explorer, …) came from other agents and have not
  all been reviewed.

## Future plans (in order)

1. **Companion services without the full stack.** Start only
   `chromadb searxng speaches` from compose, so the Mac app gets memory, search
   and voice without the Docker Odysseus container. Show each one's status in
   Settings.
2. **Restart and check.** After relaunching, confirm memory and RAG connect, and
   see the startup error screen once by starting the app while the Docker copy
   runs.
3. **Claude parity polish.** Projects page and light theme are done; next candidates are
   project instructions and files (a project is still only a folder of chats).
4. **Merge upstream.** Bring in the 509 upstream commits on a separate branch,
   resolve conflicts, and rerun the full suite.
5. **RAM headroom.** If the Mac still feels tight, package qwen3.6-35b at 64k
   context (`docker model package --from … --context-size 65536`), which
   costs less RAM than 128k.
6. **Review the other agents' MCP servers** and remove the stubs or duplicates.
