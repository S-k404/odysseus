# Odysseus Mac app: handoff notes

For the next person or Claude session picking this up. Current state and the
plan are in `MAC_APP_STATUS.md`; this file is how to work on it safely.

Last updated 2026-11-03. Branch `mac-app-claude-desktop`. Local `main` was
fast-forwarded to `870002db` at the owner's request (nothing has ever been pushed);
the branch is one commit ahead of it (`cb51a746`, Ollama unload).

## Goal and rules from the owner

- Make the Mac app look and feel like Claude Desktop, with **local models
  only**. Do not add Claude/Anthropic cloud models.
- The Mac must not run out of RAM. Never leave two big models loaded.
- **Don't run Docker** (start, restart or rebuild containers) unless the owner
  says so. The Docker copy of Odysseus is stopped on purpose.
- Don't overwrite the saved theme (`data/user_prefs.json`: a custom palette
  with the rain effect) without asking. The built-in `claude` theme is the
  Claude Desktop look.
- Don't unload or load real models while testing unless the owner says so.
  Another Claude Code session (the bridgeplay project's `local_agent.py`) uses
  qwen3.6-35b through Docker Model Runner. Test against the fake runner below.
  The owner has allowed, once each: loading qwen3-8b in Docker Model Runner,
  then unloading it, and loading Ollama's 1 GB `qwen2.5:1.5b`.
- Don't print secrets from `.env` or `data/`.
- Commit or push only when asked. `workspace/` (generated test files) and
  `swift/odysseus-macos` (compiled binary) are intentionally untracked.
  Other agents' files (`mcp_servers/…`) may show as modified; they aren't ours.

## Pick up here (end of the 2026-11-03 session)

**Done and committed on the branch:** loop protection for every local model,
the memory guard, the menu bar item, the Projects page and Claude-style welcome
and composer polish, Antigravity support, MCP discovery without ChromaDB, and
Ollama unload on switch. Details are in `MAC_APP_STATUS.md`.

**Another session's work.** It committed its oversized-MCP-result change to this
branch itself (`c35e9cec`: `MAX_MCP_OUTPUT_CHARS` in `src/constants.py`, a 100k
character cut in `src/mcp_manager.py`, shrinking of oversized tool results in
`src/context_compactor.py`, and `tests/test_oversized_tool_results.py`). Still
uncommitted and not ours, so leave them for the owner: `mcp_servers/game_save_server.py`,
`mcp_servers/GAME_SAVES_STATUS.md`, `mcp_servers/game_save_server.py.pre-es3` and
`mcp_servers/game_saves_dev/`. `workspace/` and `swift/odysseus-macos` are
generated and stay untracked. Check `git log` before editing `llm_core.py` or
`context_compactor.py`: two sessions commit to this branch.

**Open, in the order the owner would feel them:**
1. The installed app predates the window-position memory
   (`setFrameAutosaveName` in `swift/OdysseusApp.swift`). Quit the app, then run
   `./build-macos-app.sh`. It was not reinstalled because the app was open.
2. Qwen3.6-35b has not been tried for real: a spontaneous loop and the retry
   with thinking off are verified on qwen3-8b only. It needs about 18 GB free.
3. The menu bar icon has been checked by position and menu, not by eye.
4. The Docker image needs `docker compose up -d --build` before the next Docker
   run, and Docker stays off until the owner says otherwise.
5. A project is still only a folder of chats. Project instructions and files
   (as in Claude's projects) are the next Claude-parity step.
6. ChromaDB, SearXNG and Speaches only run in the Docker stack; the upstream
   merge is 509 commits behind.

**Gotchas that cost time:**
- Run Python as `.venv/bin/python`. The system `python` is a stub that asks to
  install developer tools, and `python3` has no pytest.
- macOS has no `timeout`: use `perl -e 'alarm N; exec @ARGV' cmd`.
- After adding an import to `static/js/sessions.js`, copy that module in
  `tests/test_startup_session_bootstrap_js.py` or the test fails with
  `ERR_MODULE_NOT_FOUND` (it happened three times).
- The server sends UTC times without a `Z`; use `relativeTime` in
  `static/js/projectsPage.js`, not `new Date(iso)`, to show them.
- `stream_llm` holds the non-reentrant local-model lock, so a retry inside it
  must call `_stream_llm_inner`, not `stream_llm`.

## Safe testing (nothing real is touched)

```bash
scripts/dev/scratch_server.sh start        # Odysseus on :7863 + fake runner on :12499
NODE_PATH=<dir with puppeteer-core>/node_modules \
  node scripts/dev/ui_check.js /tmp/out    # picker rows, reply caption, thinking label, screenshots
scripts/dev/scratch_server.sh stop
```

- `ai/qwen3-test:8B` in the fake runner is there on purpose: "qwen3" makes
  Odysseus treat it as a native tool-calling model. Pick it in Agent mode to see
  which MCP tools a real qwen3 turn would be offered (`[agent-debug]` and
  `[tool-rag]` lines in the scratch server log). The `*-chat` models take the
  other, keyword path.
- To drive Settings headlessly: the gear is `#user-bar-settings` and the
  Integrations Add button is `#unified-intg-add-btn`.
- `scripts/dev/fake_dmr.py` imitates Docker Model Runner: loaded-model state,
  `/engines/unload`, `/engines/status` (vLLM-Metal), a file-path model name in
  replies and a `<think>` block. Its request log (`dmr.jsonl`) shows exactly
  which models were loaded and unloaded.
- `ui_check.js` needs `puppeteer-core` and Google Chrome at
  `/Applications/Google Chrome.app`.
- The scratch server uses its own data dir and no auth, so it doesn't collide
  with the Mac app on 7860.
- Tests: `.venv/bin/python -m pytest -q` (6046 passed, 3 skipped at the
  last full run, about 3 minutes). Quick set for model work:
  `tests/test_docker_model_runner.py tests/test_model_sort_js.py
  tests/test_model_routes.py tests/test_startup_session_bootstrap_js.py`.
- Some tests read the real `data/`. Per `tests/TESTING_STANDARD.md`, stub local
  data in the test; don't weaken the security behaviour.

## Build and run

- Rebuild the app: `./build-macos-app.sh` (installs `/Applications/Odysseus.app`
  and builds `dist/Odysseus.dmg`). Swift is in `swift/OdysseusApp.swift`;
  type-check with `xcrun swiftc -typecheck swift/OdysseusApp.swift swift/MenuBarStats.swift swift/main.swift`
  (three files: the entry point lives in `main.swift`).
- The app starts uvicorn on 7860 and stops it on quit. Log:
  `logs/odysseus-app.log`. Static files are served from the repo, so JS/CSS
  changes need only a reload; Python changes need ⌘Q and reopen.
- Docker copy (port 7000): `docker compose up -d --build`. Its image doesn't
  have the model-unload, RAM-guard or single-server changes until rebuilt.
  Don't hot-mount single files into it.

## Where things live

| Area | Files |
|---|---|
| Claude look | `static/claude-skin.css` (sections 10–12: transcript, sidebar, welcome). Put new reskin CSS here, not in `static/style.css`. Use theme variables, not fixed colours. |
| Sidebar, welcome, labels | `static/index.html`, `static/js/sessions.js`, `static/js/chatRenderer.js` (`renderWelcomeGreeting`, `isRunnerAlias`, `modelRouteLabel`), `static/js/markdown.js` (thinking toggle) |
| Model picker | `static/js/modelPicker.js`, `static/js/modelSort.js` (`isNonChatModelId`) |
| One model at a time | `src/llm_core.py` (`_local_model_slot`, `release_local_models`), `src/docker_model_runner.py` (unload, vLLM-Metal guard), `routes/local_model_routes.py` (`POST /api/local-models/release`), `static/js/localModels.js` |
| One server per `data/` | `src/instance_lock.py` (claim file `data/.server-instance.json`; off with `ODYSSEUS_SINGLE_INSTANCE=0`) |
| Docker hostnames when native | `src/native_hosts.py` (rewrites `speaches`, `searxng`, `chromadb`, `ntfy` URLs to the ports Docker publishes) |
| Connectors window | `static/js/connectors.js`, `routes/mcp_routes.py` |
| Which MCP tools an agent is offered | `src/agent_loop.py` (`[tool-rag]` block), `src/tool_index.py` (`ToolIndex`, and `keyword_mcp_tools` when ChromaDB is down) |
| Other agents (Claude Code, Codex, Antigravity) | `integrations/<agent>/`, `routes/codex_routes.py` (zip routes), `AGENT_CONFIGS` in `static/js/settings.js`. All use the `/api/codex/*` scoped API; add a new agent by copying `integrations/antigravity/` |
| Mac wrapper | `swift/OdysseusApp.swift`, `build-macos-app.sh` |

## Safety rules the code enforces (keep them)

- Startup loads **no** model. Warmups are off unless `ODYSSEUS_STARTUP_WARMUPS`
  is set. Scheduled tasks are event-triggered; the nightly skill audit goes
  through the model slot.
- A local model call takes the slot, then unloads every other loaded model
  (embeddings stay). Foreground chat beats background work.
- Picking a model or starting a new chat calls `/api/local-models/release`,
  except while a reply is generating, or when the picked model would be
  refused.
- Safetensors models on Docker's vLLM-Metal backend are refused (it reserves
  about 90% of RAM). Override: `ODYSSEUS_ALLOW_VLLM_METAL=1`.
- Local image generation waits for the same slot.
- The owner's launchd watchdog (`~/.local/bin/llm-watchdog.sh`, label
  `com.shamit.llm-watchdog`) also unloads models every 30 s when two big ones
  are resident or model memory passes 28 GB. Leave it running.
- Measured RAM: qwen3.6-35b @128k 19 GB, qwen3-vl-30b @16k 20 GB, qwen3-8b @32k
  10 GB, coder-1.5b @32k 2.4 GB. Set a model's context by packaging it
  (`docker model package --from … --context-size N`), not `_configure`.

## Gotchas

- Menu bar item without a screen grab: `Odysseus --dump-menubar` prints its title
  and menu rows from live data, `--menubar-unload-all` does the menu's unload, and
  launching the app with `ODYSSEUS_MENUBAR_DEBUG_FILE=/path` writes whether the
  item is on screen and its menu. To try a build without touching real data, run a
  copy with `ODYSSEUS_PORT=7899 ODYSSEUS_DATA_DIR=/tmp/x AUTH_ENABLED=false`.
- Memory knobs: `ODYSSEUS_RAM_GUARD=0` (allow any load), `ODYSSEUS_MEMORY_GUARD=0`
  (no watchdog), `ODYSSEUS_RAM_RESERVE_GB` (GB the load guard keeps for macOS and
  other apps; default 10% of RAM, at least 4; `0` uses every free byte, a negative
  value such as `-4` also accepts that much swapping). Loop knobs live at the top of
  the guard in `src/llm_core.py`. "Optimise memory" (`src/ram_optimizer.py`) only
  frees what Odysseus owns; its "biggest apps" list ranks by `top` footprint, because
  `ps` resident size hides compressed memory (it showed Docker's VM as 1.9 GB, not 6.6).
  The menu bar's "Free more memory…" (right-click menu, `swift/MemoryFreer.swift`; also offered
  after Optimise while memory is still tight) is the only step that touches other apps: it lists the
  biggest ones (footprint of the app plus its helper processes) with unticked boxes and sends a polite
  quit to the ticked ones. Terminals, Docker, IDEs, Claude and Odysseus are never listed
  (`MemoryFreer.protected`). `Odysseus --menubar-heavy-apps` prints the list without any UI.

- "The Odysseus server stopped during startup" with an unhelpful log: look for
  `DataDirInUse` in `logs/odysseus-app.log` and check `data/.server-instance.json`
  (the claim; `"stopping": true` means a server is mid-shutdown). To reproduce a
  quit-and-reopen race without touching real data, run two servers on a scratch
  `ODYSSEUS_DATA_DIR` and SIGTERM the first while its shutdown is slow.

- Model switching has a repeatable check: start the scratch server, then
  `node scripts/dev/model_switch_check.js OUT_DIR [1-5]` and
  `python3 scripts/dev/model_switch_log.py`. It shows the exact messages each
  model was sent. The fake runner understands `SLOWTEST` (slow stream, to switch
  mid-reply) and `TOOLTEST` (one `update_plan` tool call) or `LOOPTEST` (reasoning loops until the
  request turns thinking off) in a message.
- The model picker is loaded as two module instances (`modelPicker.js` with and
  without a `?v=` suffix), so state shared between them lives on `window`
  (`__odysseusLastPickedRoute`, `__odysseusModelSwitchPromise`). `loadSessions()`
  replaces the whole session list; anything that must survive a refresh needs a
  reconcile step like `modelPickReconcile.js`.
- A message containing words like "project", "app", "file", "system" or "change"
  turns a Chat-mode message into an agent turn (`workspaceAgentIntent` in
  `static/js/chat.js`). A test prompt that happens to include one behaves
  differently from the same chat without it.

- Docker Model Runner names the answering model by file path
  (`…/bundles/sha256/…/model.gguf`). `isRunnerAlias` hides that; don't compare
  raw model names in the UI.
- Docker Model Runner lists some models twice: by tag and as untagged
  `sha256:…` (the original blob, left by `docker model package`, with its old
  context size). The picker hides those via `hide_untagged_duplicates`; Settings
  still shows them. Match is on format, architecture, parameters, quantization
  and size, so a model with too little metadata is never hidden.
- `/api/models` caches for 30 s. A freshly added endpoint shows no models until
  probed; use `?refresh=true`.
- The page's CSP blocks `eval`/`Function()` in injected scripts.
- macOS has no `timeout`; zsh errors on unmatched globs (quote `--include='*.py'`)
  and parses a leading `==` as a command.
- `static/style.css` is 1.2 MB and an earlier agent's edit tool blanked it. Edit
  it only with targeted replacements, and check `git diff --stat` after.
- `.env` is shared with Docker; `load_dotenv` never overrides existing env.
- The owner also runs Antigravity (Gemini) agents. Their transcripts are in
  `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`.

## Memory for Claude sessions

Auto-memory lives in
`~/.claude/projects/-Users-shamit-Documents-Docker/memory/`:
`odysseus-claude-reskin.md` (goal, reskin, lock, theme) and
`docker-model-runner-memory.md` (RAM table, unload, context). Update them when
these notes change.
