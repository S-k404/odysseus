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
- The chat model picker hides speech, embedding and image models (Kokoro,
  Whisper, nomic-embed, stable-diffusion). They stay available in the voice,
  memory and image settings.
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

**Local model safety** (Docker Model Runner on 127.0.0.1:12434)
- Odysseus generates with one local model at a time. Before a model loads,
  the others are unloaded (`src/docker_model_runner.py`, `_local_model_slot`
  in `src/llm_core.py`).
- Picking a model, or starting a new chat, unloads the other models right away
  (`POST /api/local-models/release`). It is skipped while a reply is
  generating. Verified end to end against a fake model runner.
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
- `.env` is shared with Docker. When running natively, Docker service URLs
  such as `http://speaches:8000` are pointed at the ports Docker publishes on
  127.0.0.1 (`src/native_hosts.py`).

**MCP servers**
- Fixes:
  - Obsidian vault paths.
  - ECE inventory BOM parsing.
  - Onshape user line.
  - The repo-root lookup in the CAD, PCB, project, music and computer-use
    servers.
- PCB maker runs real `kicad-cli` DRC/ERC.

**Tests:** the full suite passes. New tests cover the instance lock, native
hosts, and the model runner guard and unload.

### Needs a step from you
1. **Quit and reopen Odysseus** (⌘Q). The server that is running now is the old
   code; the new app build is already in `/Applications`.
2. **Before the next Docker run:** `docker compose up -d --build`. The Docker
   image doesn't have the unload, guard or single-server changes until it is
   rebuilt.
3. **Optional theme:** your saved theme is a custom blue/red palette with the
   rain effect. Settings → Appearance → **claude** (dark) or **claude-light**
   gives the Claude Desktop colours and no background effect.

### Known gaps
- ChromaDB, SearXNG and Speaches only run inside the Docker stack. While Docker
  is off, the Mac app has no vector memory or document search, no SearXNG web
  search, and no TTS/STT.
- "Projects" opens a new-project prompt rather than a projects page.
- Ollama models are not unloaded on switch. They unload themselves after 5
  minutes idle, and the 1.5B model is about 1 GB.
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
3. **Claude parity polish.** A Projects page. (Light theme is done.)
4. **Merge upstream.** Bring in the 509 upstream commits on a separate branch,
   resolve conflicts, and rerun the full suite.
5. **RAM headroom.** If the Mac still feels tight, package qwen3.6-35b at 64k
   context (`docker model package --from … --context-size 65536`), which
   costs less RAM than 128k. Optionally add Ollama unload (`keep_alive: 0`).
6. **Review the other agents' MCP servers** and remove the stubs or duplicates.
