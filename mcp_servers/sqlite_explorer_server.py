"""
sqlite_explorer_server.py

MCP server providing direct, safe SQLite database exploration and querying
for local databases in the workspace (e.g. app.db, homebox.db, custom project databases).
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("sqlite_explorer")


def _resolve_db_path(db_path: str) -> Path:
    p = Path(db_path)
    if p.is_absolute() and p.exists():
        return p
    workspaces = [
        Path("/app/data"),
        Path("/app/workspace"),
        Path("/app/workspace/Homebox/data"),
        Path("/Users/shamit/Documents/Docker"),
        Path("/Users/shamit/Documents/Docker/Odysseus/data"),
        Path.cwd(),
    ]
    for ws in workspaces:
        cand = ws / db_path.lstrip("/")
        if cand.exists():
            return cand
    return p


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_sqlite_tables",
            description="List all tables, views, and row counts in a local SQLite database file (e.g. 'data/app.db', 'Homebox/data/homebox.db').",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_path": {
                        "type": "string",
                        "description": "Path to the SQLite database file (absolute or relative to workspace)",
                    }
                },
                "required": ["db_path"],
            },
        ),
        Tool(
            name="describe_sqlite_table",
            description="Inspect schema, column names, data types, primary keys, and foreign keys for a specific table in a SQLite database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_path": {
                        "type": "string",
                        "description": "Path to the SQLite database file",
                    },
                    "table_name": {
                        "type": "string",
                        "description": "The table name to inspect",
                    },
                },
                "required": ["db_path", "table_name"],
            },
        ),
        Tool(
            name="query_sqlite",
            description="Execute a safe, read-only SQL query (SELECT, PRAGMA) against a local SQLite database and return results as a Markdown table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_path": {
                        "type": "string",
                        "description": "Path to the SQLite database file",
                    },
                    "query": {
                        "type": "string",
                        "description": "Read-only SQL query (e.g. 'SELECT * FROM entities LIMIT 10')",
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum number of rows to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": ["db_path", "query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    raw_path = arguments.get("db_path", "")
    db_path = _resolve_db_path(raw_path)

    if not db_path.is_file():
        return [TextContent(type="text", text=f"Error: Database file not found at '{raw_path}'")]

    if name == "list_sqlite_tables":
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name;")
            objects = cur.fetchall()

            table_stats = []
            for obj_type, obj_name in objects:
                count = "N/A"
                if obj_type == "table":
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM \"{obj_name}\";")
                        count = str(cur.fetchone()[0])
                    except Exception:
                        pass
                table_stats.append((obj_name, obj_type, count))
            conn.close()

            file_size_kb = db_path.stat().st_size / 1024
            out = [
                f"# SQLite Database: {db_path.name} ({file_size_kb:.1f} KB)",
                f"- Total Objects: {len(table_stats)}\n",
                "| Object Name | Type | Row Count |",
                "| :--- | :--- | :--- |",
            ]
            for obj_name, obj_type, count in table_stats:
                out.append(f"| `{obj_name}` | {obj_type} | {count} |")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error reading database: {e}")]

    elif name == "describe_sqlite_table":
        table_name = arguments.get("table_name", "").strip()
        if not table_name:
            return [TextContent(type="text", text="Error: table_name is required")]

        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info(\"{table_name}\");")
            columns = cur.fetchall()

            if not columns:
                conn.close()
                return [TextContent(type="text", text=f"Table '{table_name}' not found in {db_path.name}")]

            cur.execute(f"PRAGMA foreign_key_list(\"{table_name}\");")
            fks = cur.fetchall()
            conn.close()

            out = [
                f"# Schema for Table: `{table_name}` ({db_path.name})\n",
                "| CID | Column Name | Data Type | Not Null | Default Value | PK |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
            for cid, cname, ctype, notnull, dflt, pk in columns:
                pk_flag = "🔑 Yes" if pk else "No"
                nn_flag = "Yes" if notnull else "No"
                out.append(f"| {cid} | **{cname}** | `{ctype or 'ANY'}` | {nn_flag} | {dflt or 'NULL'} | {pk_flag} |")

            if fks:
                out.append("\n### Foreign Keys:")
                for fk in fks:
                    out.append(f"- Column `{fk[3]}` -> References `{fk[2]}({fk[4]})`")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error inspecting table '{table_name}': {e}")]

    elif name == "query_sqlite":
        query = arguments.get("query", "").strip()
        max_rows = min(int(arguments.get("max_rows", 50)), 200)

        # Safety: only permit read-only statements
        prohibited = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "REPLACE", "ATTACH", "DETACH"]
        first_token = query.split()[0].upper() if query else ""
        if any(p in query.upper() for p in ["DROP TABLE", "DELETE FROM", "UPDATE ", "INSERT INTO"]):
            return [TextContent(type="text", text="Security Warning: Only read-only queries (SELECT, PRAGMA, EXPLAIN) are permitted via this tool.")]

        if first_token not in ["SELECT", "PRAGMA", "EXPLAIN", "WITH"]:
            return [TextContent(type="text", text="Security Warning: Query must begin with SELECT, PRAGMA, WITH, or EXPLAIN.")]

        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(query)
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows)
            conn.close()

            if not col_names:
                return [TextContent(type="text", text="Query executed successfully (0 columns returned).")]

            out = [
                f"### Query Results ({len(rows)} row(s)):\n",
                "| " + " | ".join(col_names) + " |",
                "| " + " | ".join([":---"] * len(col_names)) + " |",
            ]
            for r in rows:
                row_str = " | ".join(str(v).replace("\n", " ") if v is not None else "*NULL*" for v in r)
                out.append(f"| {row_str} |")

            return [TextContent(type="text", text="\n".join(out))]
        except Exception as e:
            return [TextContent(type="text", text=f"SQL Query Error: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
