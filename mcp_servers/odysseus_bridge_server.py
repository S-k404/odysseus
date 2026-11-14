"""
odysseus_bridge_server.py

Model Context Protocol (MCP) server providing access to Odysseus:
- Memories: Retrieve, search, and store long-term facts, preferences, and project context.
- Todos & Notes: List, add, update, and track action items and time-based reminders.
- Calendar: Query and schedule events.
- Documents: Search and retrieve personal knowledge documents.
- Agent Loop: Directly dispatch tasks to Odysseus's local Qwen 35B agent.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Ensure Odysseus root is in python path
ODYSSEUS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ODYSSEUS_DIR))

server = Server("odysseus")

DATA_DIR = ODYSSEUS_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
MEMORY_PATH = DATA_DIR / "memory.json"

DEFAULT_OWNER = os.environ.get("ODYSSEUS_OWNER", "admin")


# ==============================================================================
# Database & File Helpers
# ==============================================================================

def _get_db_connection():
    import sqlite3
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _load_memories_json() -> List[Dict[str, Any]]:
    if not MEMORY_PATH.exists():
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"[odysseus_mcp] Error loading memory.json: {e}\n")
        return []


def _save_memories_json(entries: List[Dict[str, Any]]) -> None:
    temp_path = MEMORY_PATH.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    temp_path.replace(MEMORY_PATH)


# ==============================================================================
# Tool Declarations
# ==============================================================================

@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="odysseus_get_memories",
            description="Retrieve and search long-term facts, preferences, project details, and user profile information stored in Odysseus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional keyword or search term to filter memories"
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter: 'fact', 'project', 'preference', 'identity'"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximum number of memories to return (default: 20)"
                    }
                }
            }
        ),
        Tool(
            name="odysseus_add_memory",
            description="Save a new persistent memory, fact, user preference, or project insight into Odysseus's long-term memory store.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The statement or fact to remember"
                    },
                    "category": {
                        "type": "string",
                        "default": "fact",
                        "description": "Category for the memory ('fact', 'project', 'preference', 'identity')"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="odysseus_manage_notes",
            description="List, add, update, toggle, or delete todos, checklists, reminders, and notes in Odysseus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'list', 'add', 'update', 'complete', 'delete'"
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the note or task"
                    },
                    "content": {
                        "type": "string",
                        "description": "Detailed body text or note description"
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date / reminder time (e.g. ISO string '2026-11-10T15:00:00' or natural language)"
                    },
                    "note_id": {
                        "type": "string",
                        "description": "ID of the note/task (required for 'update', 'complete', 'delete')"
                    },
                    "note_type": {
                        "type": "string",
                        "default": "todo",
                        "description": "'todo', 'note', or 'list'"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="odysseus_manage_calendar",
            description="Query scheduled calendar events or create new calendar entries in Odysseus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "'list' to view events, 'add' to create an event, 'delete' to remove"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Title or summary of the event (required for 'add')"
                    },
                    "dtstart": {
                        "type": "string",
                        "description": "Start datetime ISO or natural language (e.g. '2026-11-10T10:00:00')"
                    },
                    "dtend": {
                        "type": "string",
                        "description": "End datetime ISO or natural language (e.g. '2026-11-10T11:00:00')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event details or notes"
                    },
                    "event_uid": {
                        "type": "string",
                        "description": "UID of the event to delete"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="odysseus_search_documents",
            description="Search Odysseus's personal document library and master notes by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search in document titles and contents"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of documents to return"
                    }
                }
            }
        ),
        Tool(
            name="odysseus_read_document",
            description="Read the full text content of a specific document from Odysseus by ID or title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID or exact title to read"
                    }
                },
                "required": ["doc_id"]
            }
        ),
        Tool(
            name="odysseus_ask_agent",
            description="Forward a prompt or complex task directly to Odysseus's autonomous local Qwen 35B agent loop.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Instruction or question for Odysseus"
                    },
                    "max_rounds": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum agent reasoning rounds (default: 5)"
                    }
                },
                "required": ["prompt"]
            }
        ),
    ]


# ==============================================================================
# Tool Execution Handlers
# ==============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "odysseus_get_memories":
            return await _handle_get_memories(arguments)
        elif name == "odysseus_add_memory":
            return await _handle_add_memory(arguments)
        elif name == "odysseus_manage_notes":
            return await _handle_manage_notes(arguments)
        elif name == "odysseus_manage_calendar":
            return await _handle_manage_calendar(arguments)
        elif name == "odysseus_search_documents":
            return await _handle_search_documents(arguments)
        elif name == "odysseus_read_document":
            return await _handle_read_document(arguments)
        elif name == "odysseus_ask_agent":
            return await _handle_ask_agent(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing {name}: {type(e).__name__}: {str(e)}")]


# ------------------------------------------------------------------------------
# 1. Memories Handlers
# ------------------------------------------------------------------------------

async def _handle_get_memories(args: Dict[str, Any]) -> List[TextContent]:
    query = (args.get("query") or "").strip().lower()
    category = (args.get("category") or "").strip().lower()
    limit = int(args.get("limit") or 20)

    entries = _load_memories_json()
    results = []
    for item in entries:
        if category and item.get("category", "").lower() != category:
            continue
        text = item.get("text", "")
        if query and query not in text.lower() and query not in item.get("category", "").lower():
            continue
        results.append(item)

    if not results:
        msg = f"No memories found matching query='{query}' category='{category}'."
        return [TextContent(type="text", text=msg)]

    lines = [f"# Odysseus Stored Memories ({len(results)} matches, limit {limit})\n"]
    for i, m in enumerate(results[:limit], 1):
        cat = m.get("category", "fact")
        txt = m.get("text", "")
        mid = m.get("id", "")
        lines.append(f"{i}. **[{cat.upper()}]** {txt} *(id: `{mid}`)*")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_add_memory(args: Dict[str, Any]) -> List[TextContent]:
    text = args.get("text", "").strip()
    if not text:
        return [TextContent(type="text", text="Error: 'text' cannot be empty.")]

    category = args.get("category", "fact").strip().lower()
    new_id = str(uuid.uuid4())
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    new_entry = {
        "id": new_id,
        "text": text,
        "timestamp": now_ts,
        "source": "mcp_client",
        "category": category,
        "uses": 1,
        "owner": DEFAULT_OWNER,
        "session_id": "MCP Integration"
    }

    # 1. Append to memory.json
    entries = _load_memories_json()
    entries.append(new_entry)
    _save_memories_json(entries)

    # 2. Also insert into SQLite memories table
    try:
        with _get_db_connection() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO memories (id, text, category, source, owner, session_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id, text, category, "mcp_client", DEFAULT_OWNER, "MCP Integration", now_ts)
            )
            con.commit()
    except Exception as e:
        sys.stderr.write(f"[odysseus_mcp] SQLite insert notice: {e}\n")

    return [TextContent(type="text", text=f"Successfully stored memory (`{new_id}`):\n**[{category.upper()}]** {text}")]


# ------------------------------------------------------------------------------
# 2. Notes / Todos Handlers
# ------------------------------------------------------------------------------

async def _handle_manage_notes(args: Dict[str, Any]) -> List[TextContent]:
    action = (args.get("action") or "list").strip().lower()
    title = (args.get("title") or "").strip()
    content = (args.get("content") or "").strip()
    due_date = (args.get("due_date") or "").strip()
    note_id = (args.get("note_id") or "").strip()
    note_type = (args.get("note_type") or "todo").strip()

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with _get_db_connection() as con:
        if action == "list":
            rows = con.execute(
                "SELECT id, title, content, note_type, due_date, archived FROM notes WHERE archived = 0 ORDER BY updated_at DESC"
            ).fetchall()
            if not rows:
                return [TextContent(type="text", text="No active notes or todos found in Odysseus.")]
            lines = [f"# Odysseus Notes & Todos ({len(rows)} items)\n"]
            for r in rows:
                due_info = f" *(Due: {r['due_date']})*" if r["due_date"] else ""
                lines.append(f"- **[{r['note_type'].upper()}]** `{r['id']}`: {r['title']}{due_info}\n  {r['content']}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif action == "add":
            if not title:
                return [TextContent(type="text", text="Error: 'title' is required to add a note/todo.")]
            nid = str(uuid.uuid4())
            con.execute(
                """
                INSERT INTO notes (id, owner, title, content, note_type, due_date, archived, pinned, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (nid, DEFAULT_OWNER, title, content, note_type, due_date, now_iso, now_iso)
            )
            con.commit()
            due_str = f" with due date: {due_date}" if due_date else ""
            return [TextContent(type="text", text=f"Created {note_type} `{nid}`: **{title}**{due_str}")]

        elif action in ("complete", "archive"):
            if not note_id:
                return [TextContent(type="text", text="Error: 'note_id' is required to complete/archive a note.")]
            con.execute("UPDATE notes SET archived = 1, updated_at = ? WHERE id LIKE ?", (now_iso, f"{note_id}%"))
            con.commit()
            return [TextContent(type="text", text=f"Marked note/todo `{note_id}` as completed/archived.")]

        elif action == "delete":
            if not note_id:
                return [TextContent(type="text", text="Error: 'note_id' is required to delete a note.")]
            con.execute("DELETE FROM notes WHERE id LIKE ?", (f"{note_id}%",))
            con.commit()
            return [TextContent(type="text", text=f"Deleted note/todo `{note_id}`.")]

        else:
            return [TextContent(type="text", text=f"Unknown action: {action}. Use 'list', 'add', 'complete', or 'delete'.")]


# ------------------------------------------------------------------------------
# 3. Calendar Handlers
# ------------------------------------------------------------------------------

async def _handle_manage_calendar(args: Dict[str, Any]) -> List[TextContent]:
    action = (args.get("action") or "list").strip().lower()
    summary = (args.get("summary") or "").strip()
    dtstart = (args.get("dtstart") or "").strip()
    dtend = (args.get("dtend") or "").strip()
    description = (args.get("description") or "").strip()
    event_uid = (args.get("event_uid") or "").strip()

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with _get_db_connection() as con:
        if action == "list":
            rows = con.execute(
                "SELECT uid, summary, dtstart, dtend, location, description FROM calendar_events ORDER BY dtstart ASC LIMIT 30"
            ).fetchall()
            if not rows:
                return [TextContent(type="text", text="No calendar events found in Odysseus.")]
            lines = [f"# Odysseus Calendar Events ({len(rows)} events)\n"]
            for r in rows:
                lines.append(f"- **{r['summary']}** (`{r['uid']}`)\n  Start: {r['dtstart']} | End: {r['dtend']}\n  Notes: {r['description'] or 'None'}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif action == "add":
            if not summary or not dtstart:
                return [TextContent(type="text", text="Error: 'summary' and 'dtstart' are required to schedule an event.")]
            uid = str(uuid.uuid4())
            con.execute(
                """
                INSERT INTO calendar_events (uid, calendar_id, summary, description, dtstart, dtend, all_day, is_utc, created_at, updated_at)
                VALUES (?, 'primary', ?, ?, ?, ?, 0, 1, ?, ?)
                """,
                (uid, summary, description, dtstart, dtend or dtstart, now_iso, now_iso)
            )
            con.commit()
            return [TextContent(type="text", text=f"Scheduled calendar event `{uid}`: **{summary}** at {dtstart}")]

        elif action == "delete":
            if not event_uid:
                return [TextContent(type="text", text="Error: 'event_uid' is required to delete an event.")]
            con.execute("DELETE FROM calendar_events WHERE uid LIKE ?", (f"{event_uid}%",))
            con.commit()
            return [TextContent(type="text", text=f"Deleted calendar event `{event_uid}`.")]

        else:
            return [TextContent(type="text", text=f"Unknown calendar action: {action}. Use 'list', 'add', or 'delete'.")]


# ------------------------------------------------------------------------------
# 4. Documents Handlers
# ------------------------------------------------------------------------------

async def _handle_search_documents(args: Dict[str, Any]) -> List[TextContent]:
    query = (args.get("query") or "").strip().lower()
    limit = int(args.get("limit") or 10)

    with _get_db_connection() as con:
        if query:
            rows = con.execute(
                """
                SELECT id, title, language, updated_at, substr(current_content, 1, 150) as preview
                FROM documents
                WHERE lower(title) LIKE ? OR lower(current_content) LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit)
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT id, title, language, updated_at, substr(current_content, 1, 150) as preview
                FROM documents LIMIT ?
                """,
                (limit,)
            ).fetchall()

        if not rows:
            return [TextContent(type="text", text=f"No documents found matching query '{query}'.")]

        lines = [f"# Odysseus Documents ({len(rows)} found)\n"]
        for r in rows:
            lines.append(f"- **{r['title']}** (`{r['id']}` - {r['language']})\n  Preview: {r['preview']}...")

        return [TextContent(type="text", text="\n".join(lines))]


async def _handle_read_document(args: Dict[str, Any]) -> List[TextContent]:
    doc_id = (args.get("doc_id") or "").strip()
    if not doc_id:
        return [TextContent(type="text", text="Error: 'doc_id' is required.")]

    with _get_db_connection() as con:
        row = con.execute(
            "SELECT id, title, language, current_content, updated_at FROM documents WHERE id = ? OR title = ?",
            (doc_id, doc_id)
        ).fetchone()

        if not row:
            return [TextContent(type="text", text=f"Document '{doc_id}' not found.")]

        header = f"# {row['title']} (ID: `{row['id']}` | Language: {row['language']})\n\n"
        return [TextContent(type="text", text=header + (row["current_content"] or ""))]


# ------------------------------------------------------------------------------
# 5. Autonomous Agent Delegation Handler
# ------------------------------------------------------------------------------

async def _handle_ask_agent(args: Dict[str, Any]) -> List[TextContent]:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return [TextContent(type="text", text="Error: 'prompt' cannot be empty.")]

    max_rounds = int(args.get("max_rounds") or 5)

    from src.agent_loop import stream_agent_loop

    endpoint_url = "http://127.0.0.1:12436/v1"
    model = "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S"

    messages = [
        {
            "role": "user",
            "content": prompt,
            "metadata": {"_tool_approval_chat_session_granted": True}
        }
    ]

    response_chunks = []
    async for chunk in stream_agent_loop(
        endpoint_url=endpoint_url,
        model=model,
        messages=messages,
        max_rounds=max_rounds,
        owner=DEFAULT_OWNER,
    ):
        if not chunk.startswith("data: "):
            continue
        data_body = chunk[6:].strip()
        if data_body == "[DONE]":
            break
        try:
            ev = json.loads(data_body)
            if "delta" in ev:
                response_chunks.append(ev["delta"])
        except Exception:
            pass

    full_output = "".join(response_chunks).strip()
    if not full_output:
        full_output = "(Odysseus agent finished execution with empty text response)"

    return [TextContent(type="text", text=full_output)]


# ==============================================================================
# Main Entry Point
# ==============================================================================

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
