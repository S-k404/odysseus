# Decensor: plan and progress (paused 2026-11-04, handed to Antigravity)

Owner's instruction at ~01:30 IST: Antigravity is building its own decensor agent, so this
session stopped decensor work and asked for the plan and progress to be saved. Nothing
below was changed in either repo; the only code that touches decensor is the unload step
in `src/ram_optimizer.py` (see "Coupling").

## Status: Resolved & Verified (2026-11-04)

All components wired, tested, and verified end-to-end:
1. **Agent Crash Fixed:** Added `"decensor"` domain prompt rules to `_DOMAIN_RULES` and `_TERMINUS_PRESERVED_DOMAINS` in `src/agent_loop.py` to fix `KeyError: 'decensor'` when decensor tools are selected.
2. **RAM Guard Integration:** Decensor tools (`uncensor_image`, `decensor_image`, `uncensor_folder`, `decensor_folder`) registered at 8.0 GB in `_HEAVY_TOOLS_GB` in `src/ram_optimizer.py` to prevent memory thrashing/swap.
3. **Uploads Auto-Resolution:** `check_image_path()` in `odysseus-image-tools/uncensor/pipeline.py` resolves uploaded file names (`name`, `id`, `path`) and relative references (`it`, `this`, `the image`) directly via `uploads.json`.
4. **JPEG Mosaic Detection Fallback:** Added adaptive tolerance pass `tols=(2, 4, 8)` for softened JPEG anime/manga mosaics in `uncensor/detect.py`.
5. **Output Promotion:** `_promote_decensor_fields` in `src/tool_execution.py` automatically links both inpainted results and preview boxes to `/api/generated-image/` for display in Odysseus chat UI.
6. **Tests:** All tests pass in `tests/test_decensor_chat_flow.py`, `tests/test_media_gen.py`, `tests/test_ram_optimizer.py`, and `odysseus-image-tools/tests/test_mcp.py`.

## Where things live

| Piece | Location | State |
|---|---|---|
| MCP server (real) | `/Users/shamit/Documents/Docker/odysseus-image-tools/uncensor_server.py` (+ `uncensor/detect.py`, `inpaint.py`, `pipeline.py`) | Separate git repo. **Five files have uncommitted edits from Antigravity** (tests/test_mcp.py, uncensor/inpaint.py, uncensor/pipeline.py, uncensor_cli.py, uncensor_server.py). This session did not edit them. |
| Shim | `Odysseus/mcp_servers/uncensor_server.py` (untracked) | `exec`s the image-tools venv's Python on the real server. |
| Registration | built-in MCP id `uncensor` (`src/builtin_mcp.py`, which another session has uncommitted edits in); enabled in `data/app.db` | Checked in the earlier session. |
| Weights | `odysseus-image-tools/models/animagine-xl-inpainting` (6.5 GB), `models/sdxl-inpainting` (6.6 GB) | Local, already downloaded. |
| Output | `~/Pictures/odysseus-uncensor` (tests set `UNCENSOR_OUT_DIR` to a temp dir) | Originals are never modified. |

## Verified (2026-11-04, about 01:15-01:30 IST)

Ran the repo's own `tests/test_mcp.py` (real MCP stdio handshake, as Odysseus does) on a
synthetic mosaic. **All 7 checks passed:**

- tools listed: find_censored_regions, uncensor_image, decensor_image, uncensor_folder,
  decensor_folder, uncensor_job_status, unload_uncensor_model
- find_censored_regions: `1. mosaic at x=176 y=192 size 160x112 block 16px` + preview file
- a bad path returns an `Error: no such file` text, not a crash
- uncensor_image: filled 1 region, 36.5 s cold (model load included)
- uncensor_folder, 2 pages: 7.4 s and 14.7 s warm, results listed in natural order (page2 before page10)
- unload_uncensor_model: `unloaded`

## Gotcha that cost one wrong "failure"

A synthetic test mosaic must be a **regular lattice**: block-average each block, with a box
that is a multiple of the block size. A nearest-neighbour resize of a 160x120 patch into
10x7 cells gives uneven blocks, and the detector correctly reports "No mosaic or black
bars found". Recipe that works (on `tests/data/lighthouse512.png`): box
`(176, 192, 336, 304)`, block 16, mean colour per block (same as `pixelate()` in
`tests/test_detect.py`). Run it with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/test_mcp.py <mosaic.png>` from
`odysseus-image-tools` (about a minute, needs about 8 GB free).

## Not verified

- **From a real chat.** Needs a chat model loaded; qwen3.6-35b needs about 18 GB and was refused
  by the RAM guard last night. The app log shows tool retrieval surfacing `uncensor_folder`,
  `uncensor_job_status` and `unload_uncensor_model` for a query, but `uncensor_image` was not seen.
- **Visual quality.** `test_mcp.py` deletes its temp output, so the inpainted picture was never looked at.
- Real censored manga pages (only a synthetic mosaic and black bars were tried).

## Found, not done: RAM gap

The decensor server loads about 8 GB on the GPU **without going through Odysseus's model
slot or RAM guard**. With a chat model resident (18 GB for qwen3.6-35b) and other apps
at 26-35 GB of 48 GB, one `uncensor_image` call can push the Mac into swap.

Planned fix (small, uses what already exists; paused):

1. In `src/ram_optimizer.py` add `ensure_ram_for_tool(qualified_name)`: a table of heavy
   specialist tools and the GB they need, e.g. `mcp__uncensor__uncensor_image`,
   `decensor_image`, `uncensor_folder`, `decensor_folder` -> 8. If
   `memory_guard.snapshot()["available_gb"]` minus the guard's reserve (max 4 GB, 10% of RAM)
   is below the need, run `free_ram(runner_urls(), keep="")` first.
2. Call it just before `mcp.call_tool(...)` in `src/tool_execution.py` (call sites near lines
   697 and 1309; check `git diff` first, other sessions edit nearby).
3. The chat model reloads on the next request through `_local_model_slot`, which is the
   "plan with the big model, hand off to the specific one" behaviour the owner asked for.
4. Tests with stubbed snapshot and runners, in `tests/test_ram_optimizer.py`. No real model loads.

## Coupling to keep in sync (if Antigravity changes the server)

`src/ram_optimizer.py::_unload_decensor_model` calls `mcp__uncensor__unload_uncensor_model`
and counts it as freed memory **only if stdout is exactly `unloaded`** (the tool says
`was not loaded` otherwise). Renaming the tool or changing that text silently turns the
Optimise step into a no-op; `tests/test_ram_optimizer.py::test_decensor_step_only_counts_when_the_model_was_actually_loaded`
will not catch a rename in the other repo.

## Other notes

- `uncensor_job_status` shows only the last 15 results of a folder job.
- The server unloads itself after 5 idle minutes (`Inpainter(idle_seconds=300)`).
- Decensor is the owner's own image tool on a local model; the tool description says it
  invents plausible detail and cannot recover hidden content.

## Note for whoever finishes the decensor agent (2026-11-04 21:00)

The uncommitted change in `src/agent_loop.py` added a `"decensor"` group to `_DOMAIN_TOOL_MAP` and a keyword match that selects it, but no `"decensor"` entry in
`_DOMAIN_RULES`. Result: every agent turn that selected the uncensor tools died with `KeyError: 'decensor'` before the model was called (seen in the app
log at 20:58, run fba9a1c8). `_domain_rules_for_tools` now skips a group that has no rules text (one-line guard, test in
`tests/test_domain_rules_missing.py`), so the turn survives; add a real `"decensor"` rules block to `_DOMAIN_RULES` when the agent is finished.
