"""
obsidian_server.py

MCP server exposing read/write access to an Obsidian vault's markdown notes:
list, search, read, create, update, and backlinks. Mirrors the shape of a
Notion connector (search / fetch / create-page / update-page) but works
directly against local markdown files instead of a remote API, so it plays
correctly with Obsidian LiveSync -- writes land on disk in the vault the
Obsidian app already watches and syncs from.

Vault root resolution: OBSIDIAN_VAULT_PATH env var, else /app/obsidian (the
default Docker Compose bind-mount target), else OBSIDIAN_VAULT_HOST_DIR (the
host folder that mount comes from, used by native runs such as the macOS
app). No further path guessing -- a misconfigured mount should fail loudly
instead of silently finding nothing.

Deliberately self-contained (stdlib + mcp only, no `src`/`core` imports):
other built-ins (rag_server.py, memory_server.py) lazily import app internals
because they need live app managers. This server only ever touches plain
files under the vault root, so it skips that import surface (and the app's
heavier transitive dependencies, e.g. core/__init__.py -> httpx) entirely.
The hidden-dir pruning below intentionally mirrors src/index_walk.py's
policy; keep the two in sync if that policy changes.
"""

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("obsidian")

_NOTE_SUFFIX = ".md"
_MAX_READ_BYTES = 200_000  # guard against dumping a huge note into model context
_MAX_LIST_RESULTS = 200
_MAX_SEARCH_RESULTS = 30
_MAX_SEARCH_MATCHES_PER_FILE = 3
_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)
_EXCLUDED_DIR_NAMES = {"node_modules", "__pycache__", "venv"}


def _prune_dirs(dirs: list) -> None:
    dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in _EXCLUDED_DIR_NAMES]


def _is_indexable_file(name: str) -> bool:
    return not name.startswith(".")


def _atomic_write_text(path: str, text: str) -> None:
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _vault_candidates() -> list[str]:
    configured = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if configured:
        return [configured]
    host_dir = os.environ.get("OBSIDIAN_VAULT_HOST_DIR", "").strip()
    return ["/app/obsidian"] + ([host_dir] if host_dir else [])


def _vault_root() -> Path | None:
    for candidate in _vault_candidates():
        if os.path.isdir(candidate):
            return Path(candidate).resolve()
    return None


def _iter_notes(root: Path, folder: str = ""):
    start = root
    if folder:
        start = (root / folder.strip("/")).resolve()
        try:
            start.relative_to(root)
        except ValueError:
            return
        if not start.is_dir():
            return
    for dirpath, dirnames, filenames in os.walk(start):
        _prune_dirs(dirnames)
        for fn in filenames:
            if _is_indexable_file(fn) and fn.lower().endswith(_NOTE_SUFFIX):
                yield Path(dirpath) / fn


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace(os.sep, "/")


def _safe_resolve(root: Path, rel: str) -> Path | None:
    """Resolve a vault-relative note path, refusing traversal or symlink escape."""
    rel = (rel or "").strip().lstrip("/")
    if not rel:
        return None
    if not rel.lower().endswith(_NOTE_SUFFIX):
        rel += _NOTE_SUFFIX
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _resolve_by_title(root: Path, title: str) -> list:
    """[[wikilink]]-style resolution: match by filename stem, case-insensitive,
    anywhere in the vault."""
    needle = title.strip()
    if needle.lower().endswith(_NOTE_SUFFIX):
        needle = needle[: -len(_NOTE_SUFFIX)]
    needle_l = needle.lower()
    return [n for n in _iter_notes(root) if n.stem.lower() == needle_l]


def _resolve_target(root: Path, path: str = "", title: str = ""):
    """Returns (resolved_path_or_None, error_message_or_None)."""
    if path:
        resolved = _safe_resolve(root, path)
        if resolved is None:
            return None, f"Error: '{path}' is outside the vault or invalid."
        return resolved, None
    if title:
        matches = _resolve_by_title(root, title)
        if not matches:
            return None, f"Error: No note titled '{title}' found in the vault."
        if len(matches) > 1:
            options = "\n".join(f"  - {_rel(root, m)}" for m in matches[:20])
            return None, (
                f"Error: '{title}' is ambiguous, {len(matches)} notes match:\n"
                f"{options}\nUse 'path' to disambiguate."
            )
        return matches[0], None
    return None, "Error: provide either 'path' or 'title'."


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s.strip() != s or any(c in s for c in ':#[]{},&*!|>\'"%@`'):
        return json.dumps(s)
    return s


def _frontmatter_block(fm: dict) -> str:
    lines = ["---"]
    for k, v in fm.items():
        key = str(k)
        if isinstance(v, (list, tuple)):
            if not v:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_yaml_scalar(item)}" for item in v)
        else:
            lines.append(f"{key}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _do_list(root: Path, folder: str = "", tag: str = "", limit: int = _MAX_LIST_RESULTS) -> str:
    tag_needle = tag.strip().lstrip("#").lower() if tag else None
    results = []
    for note in _iter_notes(root, folder):
        if tag_needle:
            try:
                text = note.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if f"#{tag_needle}" not in text.lower():
                continue
        results.append(_rel(root, note))
    results.sort()
    scope_bits = []
    if folder:
        scope_bits.append(f"in '{folder}'")
    if tag_needle:
        scope_bits.append(f"tagged #{tag_needle}")
    scope = f" ({', '.join(scope_bits)})" if scope_bits else ""
    if not results:
        return f"No notes found{scope}."
    lines = [f"**{len(results)} note(s){scope}:**"]
    for r in results[:limit]:
        lines.append(f"  - {r}")
    if len(results) > limit:
        lines.append(f"  ... and {len(results) - limit} more")
    return "\n".join(lines)


def _do_search(root: Path, query: str, folder: str = "", tag: str = "") -> str:
    if not query or not query.strip():
        return "Error: search needs a non-empty 'query'."
    needle = query.strip().lower()
    tag_needle = tag.strip().lstrip("#").lower() if tag else None
    hits = []
    for note in _iter_notes(root, folder):
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if tag_needle and f"#{tag_needle}" not in text.lower():
            continue
        title_hit = needle in note.stem.lower()
        matched_lines = []
        if needle in text.lower():
            for line in text.splitlines():
                if needle in line.lower():
                    snippet = line.strip()
                    if len(snippet) > 160:
                        snippet = snippet[:157] + "..."
                    matched_lines.append(snippet)
                    if len(matched_lines) >= _MAX_SEARCH_MATCHES_PER_FILE:
                        break
        if title_hit or matched_lines:
            hits.append((_rel(root, note), matched_lines))
        if len(hits) >= _MAX_SEARCH_RESULTS:
            break
    if not hits:
        return f"No notes matched '{query}'."
    lines = [f"**{len(hits)} note(s) matching '{query}':**"]
    for path, snippets in hits:
        lines.append(f"\n- `{path}`")
        for s in snippets:
            lines.append(f"    > {s}")
    return "\n".join(lines)


def _do_read(root: Path, path: str = "", title: str = "") -> str:
    resolved, err = _resolve_target(root, path, title)
    if err:
        return err
    try:
        raw = resolved.read_bytes()
    except OSError as e:
        return f"Error: could not read '{_rel(root, resolved)}': {e}"
    truncated = len(raw) > _MAX_READ_BYTES
    text = raw[:_MAX_READ_BYTES].decode("utf-8", errors="ignore")
    header = f"# {_rel(root, resolved)}\n\n"
    if truncated:
        header += f"_(truncated at {_MAX_READ_BYTES} bytes; note is larger)_\n\n"
    return header + text


def _do_create(root: Path, path: str = "", title: str = "", content: str = "",
                frontmatter: dict = None, overwrite: bool = False) -> str:
    if not path and not title:
        return "Error: create needs 'path' or 'title'."
    if not path:
        safe_title = re.sub(r'[\\/:*?"<>|]', "-", title.strip()) or "Untitled"
        path = f"{safe_title}{_NOTE_SUFFIX}"
    resolved = _safe_resolve(root, path)
    if resolved is None:
        return f"Error: '{path}' is outside the vault or invalid."
    if resolved.exists() and not overwrite:
        return (
            f"Error: '{_rel(root, resolved)}' already exists. "
            "Use action=update, or overwrite=true to replace it."
        )
    body = content or ""
    if frontmatter:
        body = _frontmatter_block(frontmatter) + body
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(str(resolved), body)
    except OSError as e:
        return f"Error: could not write '{_rel(root, resolved)}': {e}"
    return f"Created '{_rel(root, resolved)}' ({len(body)} bytes)."


def _do_update(root: Path, path: str = "", title: str = "", content: str = "", mode: str = "append") -> str:
    resolved, err = _resolve_target(root, path, title)
    if err:
        return err
    if not content:
        return "Error: update needs non-empty 'content'."
    try:
        existing = resolved.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return f"Error: could not read '{_rel(root, resolved)}': {e}"
    if mode == "replace":
        new_text = content
    elif mode == "prepend":
        fm_match = _FRONTMATTER_RE.match(existing)
        if fm_match:
            insert_at = fm_match.end()
            new_text = existing[:insert_at] + content.rstrip("\n") + "\n\n" + existing[insert_at:]
        else:
            new_text = content.rstrip("\n") + "\n\n" + existing
    else:  # append (default)
        padded = existing
        if not padded.endswith("\n"):
            padded += "\n"
        if not padded.endswith("\n\n"):
            padded += "\n"
        new_text = padded + content
    try:
        _atomic_write_text(str(resolved), new_text)
    except OSError as e:
        return f"Error: could not write '{_rel(root, resolved)}': {e}"
    return f"Updated '{_rel(root, resolved)}' ({mode}, now {len(new_text)} bytes)."


def _do_backlinks(root: Path, path: str = "", title: str = "") -> str:
    resolved, err = _resolve_target(root, path, title)
    if err:
        return err
    needle = resolved.stem.lower()
    pattern = re.compile(r"\[\[([^\]|#]+)")
    hits = []
    for note in _iter_notes(root):
        if note == resolved:
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in pattern.finditer(text):
            if m.group(1).strip().lower() == needle:
                hits.append(_rel(root, note))
                break
    if not hits:
        return f"No backlinks to '{_rel(root, resolved)}'."
    lines = [f"**{len(hits)} note(s) link to '{_rel(root, resolved)}':**"]
    lines.extend(f"  - {h}" for h in sorted(hits))
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="manage_obsidian",
            description=(
                "Read and write notes in the user's Obsidian vault. Actions: "
                "'list' (browse notes, optionally by folder/tag), 'search' (text/tag search), "
                "'read' (fetch one note by path or [[title]]), 'create' (new note, optional frontmatter), "
                "'update' (append/prepend/replace an existing note's content), "
                "'backlinks' (find notes that [[link]] to a given note)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "search", "read", "create", "update", "backlinks"]},
                    "path": {"type": "string", "description": "Vault-relative note path, e.g. 'Courses/ECE 201.md'"},
                    "title": {"type": "string", "description": "Note title, resolved like an Obsidian [[wikilink]] when path is unknown"},
                    "folder": {"type": "string", "description": "Restrict list/search to this vault-relative folder"},
                    "query": {"type": "string", "description": "Search text (search action)"},
                    "tag": {"type": "string", "description": "Filter by an Obsidian #tag, with or without the leading #"},
                    "content": {"type": "string", "description": "Note body (create), or text to apply (update)"},
                    "frontmatter": {"type": "object", "description": "YAML frontmatter fields to set on create"},
                    "mode": {"type": "string", "enum": ["append", "prepend", "replace"], "description": "update action mode (default append)"},
                    "overwrite": {"type": "boolean", "description": "create action: allow replacing an existing note (default false)"},
                },
                "required": ["action"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "manage_obsidian":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    root = _vault_root()
    if root is None:
        hint = "' or '".join(_vault_candidates())
        return [TextContent(type="text", text=(
            f"Error: Obsidian vault not found at '{hint}'. "
            "Set OBSIDIAN_VAULT_PATH (or OBSIDIAN_VAULT_HOST_DIR for native runs), "
            "or check the docker-compose.yml bind mount."
        ))]

    arguments = arguments or {}
    action = arguments.get("action", "")
    try:
        if action == "list":
            text = _do_list(root, arguments.get("folder", ""), arguments.get("tag", ""))
        elif action == "search":
            text = _do_search(root, arguments.get("query", ""), arguments.get("folder", ""), arguments.get("tag", ""))
        elif action == "read":
            text = _do_read(root, arguments.get("path", ""), arguments.get("title", ""))
        elif action == "create":
            text = _do_create(
                root, arguments.get("path", ""), arguments.get("title", ""),
                arguments.get("content", ""), arguments.get("frontmatter"),
                bool(arguments.get("overwrite", False)),
            )
        elif action == "update":
            text = _do_update(
                root, arguments.get("path", ""), arguments.get("title", ""),
                arguments.get("content", ""), arguments.get("mode", "append"),
            )
        elif action == "backlinks":
            text = _do_backlinks(root, arguments.get("path", ""), arguments.get("title", ""))
        else:
            text = f"Error: Unknown action '{action}'. Use: list, search, read, create, update, backlinks"
    except Exception as e:
        text = f"Error: {type(e).__name__}: {e}"
    return [TextContent(type="text", text=text)]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
