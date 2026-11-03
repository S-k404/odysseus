#!/usr/bin/env python3
"""
project_manager_server.py - Claude-Style Project & Markdown Document Manager

Provides tools for:
- Initializing structured project workspaces (workspace/projects/<name>/) with standard CLAUDE.md guidelines
- Writing proper, clean markdown documents (specifications, architecture, designs, task checklists)
- Separating persistent project work from normal one-time/ephemeral chats
- Querying project context and active tasks
- Exporting chat conversations into formal project markdown documentation
"""

import os
import sys
import json
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("project_manager")

WORKSPACE_DIR = Path(os.environ.get("ODYSSEUS_REPO_DIR") or Path(__file__).resolve().parent.parent) / "workspace"
PROJECTS_DIR = WORKSPACE_DIR / "projects"
CHATS_DIR = WORKSPACE_DIR / "chats"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
CHATS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "unnamed_project"


@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="init_project",
            description="Initialize a dedicated project workspace with a Claude-style CLAUDE.md manifest, docs/, src/, artifacts/, and tasks.md. Keeps project work isolated from one-time chats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Unique name of the project (e.g. 'smart_drone_controller', 'weather_ai', 'iot_gateway')"
                    },
                    "description": {
                        "type": "string",
                        "description": "High-level summary of the project goals and purpose"
                    },
                    "tech_stack": {
                        "type": "string",
                        "description": "Primary languages, frameworks, or EDA tools (e.g. 'Python, FastAPI, KiCad, OpenSCAD')"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Project domain (e.g. 'software', 'hardware_pcb', 'cad_3d', 'ai_research')",
                        "default": "software"
                    }
                },
                "required": ["project_name", "description"]
            }
        ),
        Tool(
            name="save_project_markdown",
            description="Create or update a proper, Claude-style markdown document (.md) in the project workspace with YAML frontmatter, clean headings, and structured sections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project under workspace/projects/"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename (e.g. 'system_architecture.md', 'api_spec.md', 'circuit_review.md')"
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable title of the document"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content with sections, code blocks, or tables"
                    },
                    "category": {
                        "type": "string",
                        "description": "Target folder: 'docs' (default), 'artifacts', 'specs', or root",
                        "default": "docs"
                    }
                },
                "required": ["project_name", "filename", "title", "content"]
            }
        ),
        Tool(
            name="get_project_context",
            description="Retrieve the complete project context from CLAUDE.md and tasks.md to ground project-specific work and architectural rules.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project to inspect"
                    }
                },
                "required": ["project_name"]
            }
        ),
        Tool(
            name="list_projects",
            description="List all active projects in the workspace, showing their directory path, CLAUDE.md manifest, and documentation files.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="archive_one_time_chat",
            description="Archive a one-time, transient chat session into workspace/chats/ as a formatted markdown log, keeping it completely separate from project directories.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_title": {
                        "type": "string",
                        "description": "Title or topic of the one-time chat"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full conversation text or summary to archive"
                    },
                    "model": {
                        "type": "string",
                        "description": "Model used during the chat turn"
                    }
                },
                "required": ["chat_title", "content"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    if name == "init_project":
        raw_name = arguments.get("project_name", "")
        pname = _safe_name(raw_name)
        desc = arguments.get("description", "Project workspace initialized in Odysseus.")
        stack = arguments.get("tech_stack", "General / Python")
        domain = arguments.get("domain", "software")

        proj_path = PROJECTS_DIR / pname
        proj_path.mkdir(parents=True, exist_ok=True)
        (proj_path / "docs").mkdir(exist_ok=True)
        (proj_path / "src").mkdir(exist_ok=True)
        (proj_path / "artifacts").mkdir(exist_ok=True)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        claude_md = f"""---
project: {pname}
created: {now_str}
domain: {domain}
status: active
---

# {raw_name}

> **Project Brief**: {desc}

---

## 📌 Project Overview & Goals
- **Domain**: `{domain}`
- **Primary Tech Stack**: `{stack}`
- **Status**: Active Development
- **Workspace Location**: `workspace/projects/{pname}/`

---

## 🛠️ Architecture & Directory Layout
```text
workspace/projects/{pname}/
├── CLAUDE.md          # Core project guidelines, constraints & instructions
├── tasks.md           # Active task checklist & milestone tracking
├── README.md          # Public-facing documentation
├── docs/              # System architecture, API specifications & research
├── src/               # Core source code & implementation files
└── artifacts/         # Schemas, 3D CAD/PCB models, exported assets
```

---

## 📐 Conventions & Rules
1. **Separation of Work**: Keep all permanent code, design decisions, and documentation in `docs/` and `src/`.
2. **Commitment to Quality**: Document all public functions, maintain clean directory hierarchy, and verify DRC / unit tests before closing tasks.
3. **Living Documentation**: Keep `tasks.md` and `CLAUDE.md` updated as architecture evolves.

---

## 📋 Initial Milestones
- [x] Workspace initialized with Claude-style directory structure
- [ ] Requirements specification documented in `docs/`
- [ ] Core implementation draft in `src/`
- [ ] Testing and validation
"""
        claude_path = proj_path / "CLAUDE.md"
        claude_path.write_text(claude_md, encoding="utf-8")

        tasks_md = f"""# {raw_name} — Active Tasks
*Last updated: {now_str}*

## 🚀 Active Workstream
- [ ] Define system requirements & architecture
- [ ] Implement core logic / design
- [ ] Run verification tests

## 📦 Deliverables & Docs
- `CLAUDE.md`: Project blueprint
- `docs/`: Technical specifications
"""
        (proj_path / "tasks.md").write_text(tasks_md, encoding="utf-8")

        readme_md = f"""# {raw_name}

{desc}

- **Tech Stack**: {stack}
- **Managed by**: Odysseus (Claude-style Project Workspace)
"""
        (proj_path / "README.md").write_text(readme_md, encoding="utf-8")

        return [TextContent(type="text", text=f"### ✔ Project Initialized: `{pname}`\n\n- **Project Directory**: `{proj_path}`\n- **Claude Manifest**: `{claude_path}`\n- **Subfolders Created**: `docs/`, `src/`, `artifacts/`\n- **Task Checklist**: `{proj_path / 'tasks.md'}`\n\nAll project work, code, and markdown documents will be kept strictly organized in this folder, isolated from one-time chats.")]

    elif name == "save_project_markdown":
        pname = _safe_name(arguments.get("project_name", ""))
        fname = arguments.get("filename", "document.md")
        if not fname.endswith(".md"):
            fname += ".md"
        title = arguments.get("title", "Project Document")
        content = arguments.get("content", "").strip()
        category = arguments.get("category", "docs").strip()

        proj_path = PROJECTS_DIR / pname
        if not proj_path.exists():
            proj_path.mkdir(parents=True, exist_ok=True)
            (proj_path / "docs").mkdir(exist_ok=True)

        target_dir = proj_path / category if category in ("docs", "artifacts", "specs") else proj_path
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / fname

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build clean Claude-style Markdown with YAML frontmatter if not already present
        if not content.startswith("---"):
            formatted_md = f"""---
title: "{title}"
project: "{pname}"
category: "{category}"
created: "{now_str}"
status: "active"
---

# {title}

{content}
"""
        else:
            formatted_md = content

        file_path.write_text(formatted_md, encoding="utf-8")
        return [TextContent(type="text", text=f"### ✔ Saved Project Markdown: `{file_path}`\n\n- **Project**: `{pname}`\n- **Category**: `{category}`\n- **Size**: {len(formatted_md)} characters\n\nThis file is organized inside the project workspace and cleanly separated from general one-time conversations.")]

    elif name == "get_project_context":
        pname = _safe_name(arguments.get("project_name", ""))
        proj_path = PROJECTS_DIR / pname
        if not proj_path.exists():
            return [TextContent(type="text", text=f"Error: Project '{pname}' does not exist in `workspace/projects/`. Call `list_projects` to see available projects or `init_project` to create it.")]

        claude_path = proj_path / "CLAUDE.md"
        tasks_path = proj_path / "tasks.md"

        manifest = claude_path.read_text(encoding="utf-8") if claude_path.exists() else "No CLAUDE.md found."
        tasks = tasks_path.read_text(encoding="utf-8") if tasks_path.exists() else "No tasks.md found."

        docs = [p.name for p in (proj_path / "docs").glob("*.md")] if (proj_path / "docs").exists() else []

        summary = f"""### 📁 Project Context: `{pname}`
**Location**: `{proj_path}`
**Existing Docs**: {', '.join(docs) if docs else 'None yet'}

---
#### CLAUDE.md (Project Blueprint):
{manifest}

---
#### tasks.md (Active Work):
{tasks}
"""
        return [TextContent(type="text", text=summary)]

    elif name == "list_projects":
        projects = []
        if PROJECTS_DIR.exists():
            for p in sorted(PROJECTS_DIR.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    docs = list(p.glob("**/*.md"))
                    claude_f = p / "CLAUDE.md"
                    has_manifest = claude_f.exists()
                    mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    projects.append({
                        "name": p.name,
                        "path": str(p),
                        "manifest": has_manifest,
                        "md_count": len(docs),
                        "modified": mtime
                    })

        if not projects:
            return [TextContent(type="text", text="No projects found in `workspace/projects/`. You can create one with `init_project`.")]

        lines = ["### 📂 Active Projects in Workspace:\n", "| Project Name | Markdown Docs | CLAUDE.md | Last Modified | Path |", "|---|---|---|---|---|"]
        for pr in projects:
            has_m = "✔ Yes" if pr["manifest"] else "❌ No"
            lines.append(f"| **{pr['name']}** | {pr['md_count']} files | {has_m} | {pr['modified']} | `{pr['path']}` |")

        lines.append("\n*All project files are kept strictly isolated from normal one-time chats in `workspace/chats/`.*")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "archive_one_time_chat":
        title = arguments.get("chat_title", "Untitled Chat")
        content = arguments.get("content", "").strip()
        model = arguments.get("model", "General")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_fname = _safe_name(title) + f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        out_file = CHATS_DIR / safe_fname

        formatted_chat = f"""---
title: "{title}"
type: "one_time_chat"
model: "{model}"
archived_at: "{now_str}"
project: null
---

# 💬 One-Time Chat: {title}
*Archived on: {now_str} | Model: {model}*

---

{content}
"""
        out_file.write_text(formatted_chat, encoding="utf-8")
        return [TextContent(type="text", text=f"### ✔ One-Time Chat Archived: `{out_file}`\nSaved to `workspace/chats/` without affecting any project workspace.")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


if __name__ == "__main__":
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    asyncio.run(main())

