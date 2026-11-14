"""
learnharness_server.py

MCP server providing read access to LearnHarness active learning records:
- Session history: teaching chats, practice transcripts, questions, and problem attempts.
- Learner thinking: private thinking traces, self-reported confidence, and hesitation.
- Knowledge graph: accumulated propositions, concepts, definitions, and citations.
- Reasoning chains: minimal prerequisite trees (premises -> conclusion).
- Learner profile: synthesized knowledge frontier and pedagogical recommendations.

Zero external dependencies beyond standard library and mcp.
Never mutates LearnHarness data.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("learnharness")

LEARNHARNESS_URL = os.environ.get("LEARNHARNESS_URL", "http://localhost:3000")


def _resolve_data_dir() -> Path:
    """Resolve the active LearnHarness data directory."""
    env_dir = os.environ.get("LH_DATA_DIR") or os.environ.get("LEARNHARNESS_DATA_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(Path.home() / "Documents/learn-harness/data")
    candidates.append(Path.home() / "Library" / "Application Support" / "LearnHarness" / "data")
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        candidates.append(base / "LearnHarness" / "data")

    for cand in candidates:
        try:
            resolved = cand.resolve()
            if resolved.is_dir():
                return resolved
        except Exception:
            continue

    # Fallback to the known local repo data directory
    default_dir = Path.home() / "Documents/learn-harness/data"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def _read_json_file(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tool_result_details(m: Dict[str, Any]) -> Dict[str, Any]:
    """Structured learner answer from a LearnHarness toolResult message.

    Prefers the `details` record; falls back to JSON in the text content
    (older sessions stored the answer only there).
    """
    details = m.get("details")
    if isinstance(details, dict):
        return details
    content = m.get("content")
    texts = [content] if isinstance(content, str) else [
        b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text"
    ]
    for t in texts:
        try:
            parsed = json.loads(t)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _selected_values(d: Dict[str, Any]) -> List[str]:
    """Option values the learner picked, across both answer record formats."""
    values = [a["value"] for a in d.get("answers") or [] if a.get("value")]
    return values or [v for v in d.get("selectedOptionIds") or [] if isinstance(v, str)]


def _answer_labels(d: Dict[str, Any], options: List[Dict[str, Any]]) -> List[str]:
    """Resolve answer labels against the original tool-call options.

    Labels stored with the answer can be mangled by client-side escaping, and
    bare indices are not consistently 0- or 1-based across sessions, so match
    by option value, then by position in the record's own option list, then
    fall back to the stored label. Unresolvable picks are reported as such.
    """
    by_value = {o.get("value"): o.get("label", "") for o in options if o.get("value")}
    stored = [o.get("index") for o in d.get("options") or []]
    labels = []
    for a in d.get("answers") or []:
        idx = a.get("index")
        if a.get("value") in by_value:
            labels.append(by_value[a["value"]])
        elif idx in stored and len(stored) == len(options):
            labels.append(options[stored.index(idx)].get("label", ""))
        elif a.get("label"):
            labels.append(a["label"])
        elif idx is not None:
            labels.append(f"(option index {idx}; label not recorded)")
    if not labels:
        labels = [by_value[v] for v in d.get("selectedOptionIds") or [] if v in by_value]
    return labels


def _summarize_learner_state(messages: List[Dict[str, Any]]) -> List[str]:
    """Build the 'Verified by learner' / 'Open questions' header for read_session."""
    calls: Dict[str, Dict[str, Any]] = {}
    answered = set()
    verified, missed, background = [], [], []

    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "toolCall" and b.get("name") in ("probe", "ask_user_question"):
                    calls[b.get("id", "")] = b
        elif m.get("role") == "toolResult" and m.get("toolCallId") in calls:
            call_id = m["toolCallId"]
            answered.add(call_id)
            args = calls[call_id].get("arguments") or {}
            d = _tool_result_details(m)
            question = args.get("question") or d.get("questionText") or ""
            labels = _answer_labels(d, args.get("options") or [])
            free_text = d.get("text") or ""
            conf = d.get("confidence")
            thinking = d.get("thinking") or ""

            correct = d.get("correct")
            if correct is None and args.get("correctAnswer") and _selected_values(d):
                correct = args["correctAnswer"] in _selected_values(d)

            entry = f"- **Q:** {question}\n  - **Learner answered:** {'; '.join(labels) or free_text or '(no answer)'}"
            if conf is not None:
                entry += f" (confidence {conf}%)"
            if free_text and labels:
                entry += f"\n  - **Learner's written answer:** {free_text}"
            if thinking:
                entry += f"\n  - **Learner's reasoning:** {thinking}"

            if correct is True:
                verified.append(entry)
            elif correct is False:
                missed.append(entry)
            else:
                background.append(entry)

    open_qs = [
        f"- {(c.get('arguments') or {}).get('question', '')}"
        for cid, c in calls.items() if cid not in answered
    ]

    lines = ["## Learner State Summary"]
    if verified:
        lines += ["### Verified by learner (answered correctly — build on these, do not re-teach)", *verified, ""]
    if missed:
        lines += ["### Answered incorrectly (address these misconceptions first)", *missed, ""]
    if background:
        lines += ["### Background / self-report", *background, ""]
    if open_qs:
        lines += ["### Open questions (posed to the learner, not yet answered)", *open_qs, ""]
    lines += [
        "### Grounding instructions",
        "- Open your answer by restating, in one or two sentences, what the learner verified above.",
        "- Connect new material explicitly to the learner's own reasoning where relevant.",
        "- If the request overlaps an open question, ask the learner for their answer first instead of answering it for them.",
        "- End with exactly one diagnostic question for the learner, phrased as a question (ending in '?'), and do not include its answer.",
        "",
    ]
    return lines


def _read_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return records


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="learnharness_list_sessions",
            description="List LearnHarness teaching and practice sessions, showing session ID, title, goal, message count, and timestamps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of sessions to return (default: 20)",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="learnharness_read_session",
            description="Read a full LearnHarness session transcript, including teacher explanations, questions, learner answers, private thinking traces, and self-reported confidence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (e.g. chat_abc123 or the filename without .json)",
                    },
                    "include_thinking": {
                        "type": "boolean",
                        "description": "Whether to include the learner's private thinking traces and confidence ratings (default: true)",
                        "default": True,
                    },
                    "max_messages": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="learnharness_search_graph",
            description="Search propositions and concept definitions in LearnHarness's accumulated knowledge graph by keyword or pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or pattern (e.g. 'derivative', 'eigenvalue', 'transformer', 'resistor')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of propositions to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="learnharness_get_chains",
            description="Retrieve reasoning chains (premises -> conclusion) from LearnHarness to understand the minimal prerequisite dependency tree for a concept.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Optional proposition node ID to filter chains where this node is either a premise or conclusion.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional keyword search against premise or conclusion statements.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of chains to return (default: 20)",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="learnharness_learner_profile",
            description="Summarize the learner's current knowledge frontier: recent goals, verified concepts, areas with low confidence or confusion, and pedagogical guidelines for tailoring answers.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="learnharness_live_status",
            description="Check the status of the running LearnHarness web application, configured model slots, and graph metrics.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    data_dir = _resolve_data_dir()

    if name == "learnharness_list_sessions":
        limit = int(arguments.get("limit") or 20)
        chats_dir = data_dir / "chats"
        if not chats_dir.is_dir():
            return [TextContent(type="text", text="No LearnHarness chats directory found.")]

        session_files = sorted(
            chats_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not session_files:
            return [TextContent(type="text", text=f"No sessions found in {chats_dir}.")]

        results = []
        for p in session_files[:limit]:
            doc = _read_json_file(p)
            if not isinstance(doc, dict):
                continue
            sid = p.stem
            title = doc.get("title") or "Untitled Lesson"
            created = doc.get("createdAt") or ""
            updated = doc.get("updatedAt") or ""
            msgs = doc.get("messages") or []
            goal = doc.get("goal") or doc.get("topic") or ""

            results.append(
                f"- **`{sid}`**: {title}\n"
                f"  - Goal: {goal or '(not specified)'}\n"
                f"  - Turns: {len(msgs)} messages | Updated: {updated[:19] if updated else created[:19]}"
            )

        output = [
            f"### LearnHarness Sessions ({len(results)} found, data dir: `{data_dir}`)\n",
            "\n".join(results),
        ]
        return [TextContent(type="text", text="\n".join(output))]

    elif name == "learnharness_read_session":
        sid = arguments.get("session_id", "").strip()
        include_thinking = arguments.get("include_thinking", True)
        max_messages = int(arguments.get("max_messages") or 50)

        clean_sid = sid.replace(".json", "")
        file_path = data_dir / "chats" / f"{clean_sid}.json"
        doc = _read_json_file(file_path)
        if not doc or not isinstance(doc, dict):
            return [TextContent(type="text", text=f"Session `{clean_sid}` not found in {data_dir}/chats.")]

        title = doc.get("title") or "Untitled Session"
        goal = doc.get("goal") or doc.get("topic") or ""
        messages = doc.get("messages") or []

        lines = [
            f"# Session: {title} (`{clean_sid}`)",
            f"- **Goal**: {goal or 'N/A'}",
            f"- **Total Messages**: {len(messages)}",
            "",
            *(_summarize_learner_state(messages) if include_thinking else []),
            "## Transcript Excerpt",
        ]

        for idx, m in enumerate(messages[-max_messages:], 1):
            role = m.get("role", "unknown").upper()
            content = m.get("content", "")
            thinking = m.get("thinking", "") or m.get("learnerThinking", "")
            confidence = m.get("confidence")

            text_content = ""
            if m.get("role") == "toolResult" and m.get("toolName") in ("probe", "ask_user_question"):
                # Learner answers: render the structured record instead of raw JSON.
                d = _tool_result_details(m)
                ans = "; ".join(a.get("label", "") or str(a.get("index", "")) for a in d.get("answers") or []) or d.get("text", "")
                text_content = f"[Learner answer to {m['toolName']}: {ans}" + (
                    f" — correct: {d['correct']}]" if "correct" in d else "]"
                )
                thinking = thinking or d.get("thinking", "")
                confidence = confidence if confidence is not None else d.get("confidence")
            elif isinstance(content, str):
                text_content = content
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") in ("tool-call", "toolCall"):
                            name = block.get("toolName") or block.get("name", "")
                            args = block.get("arguments") or {}
                            if args.get("question"):
                                opts = " | ".join(o.get("label", "") for o in args.get("options") or [])
                                parts.append(f"[Tool Call: {name}] {args['question']}" + (f"\n  Options: {opts}" if opts else ""))
                            else:
                                parts.append(f"[Tool Call: {name}]")
                        elif block.get("type") == "tool-result":
                            res = str(block.get("result", ""))
                            parts.append(f"[Tool Result: {res[:200]}...]" if len(res) > 200 else f"[Tool Result: {res}]")
                text_content = "\n".join(parts)

            lines.append(f"### {idx}. [{role}]")
            if text_content.strip():
                lines.append(text_content.strip())

            if include_thinking:
                if thinking:
                    lines.append(f"> **Learner's Private Thinking**: {thinking.strip()}")
                if confidence is not None:
                    lines.append(f"> **Learner Self-Reported Confidence**: {confidence}%")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "learnharness_search_graph":
        query = (arguments.get("query") or "").strip().lower()
        limit = int(arguments.get("limit") or 20)

        nodes_file = data_dir / "graph" / "nodes.jsonl"
        records = _read_jsonl_file(nodes_file)

        if not records:
            return [TextContent(type="text", text=f"No propositions found in {nodes_file}. Have lessons been extracted yet?")]

        pattern = re.compile(re.escape(query).replace(r"\*", ".*"), re.IGNORECASE) if query else None

        matches = []
        for node in records:
            nid = node.get("id", "")
            name_val = node.get("name", "")
            stmt = node.get("statement", "")
            aliases = node.get("aliases") or []

            searchable = f"{name_val} {stmt} {' '.join(aliases)}"
            if not query or (pattern and pattern.search(searchable)):
                matches.append(node)
                if len(matches) >= limit:
                    break

        if not matches:
            return [TextContent(type="text", text=f"No propositions matching query '{query}'.")]

        out = [f"### LearnHarness Propositions matching '{query}' ({len(matches)} results)\n"]
        for m in matches:
            nid = m.get("id")
            name_val = m.get("name")
            stmt = m.get("statement")
            prov = m.get("provenance") or []
            prov_str = ", ".join(f"`{p.get('chatId', '')}`" for p in prov[:3] if isinstance(p, dict))

            out.append(
                f"- **{name_val}** (`{nid}`)\n"
                f"  - Statement: {stmt}\n"
                f"  - Sources: {prov_str or 'none'}"
            )

        return [TextContent(type="text", text="\n".join(out))]

    elif name == "learnharness_get_chains":
        node_id = (arguments.get("node_id") or "").strip()
        query = (arguments.get("query") or "").strip().lower()
        limit = int(arguments.get("limit") or 20)

        chains_file = data_dir / "graph" / "chains.jsonl"
        nodes_file = data_dir / "graph" / "nodes.jsonl"

        chains = _read_jsonl_file(chains_file)
        nodes = {n.get("id"): n for n in _read_jsonl_file(nodes_file) if isinstance(n, dict)}

        if not chains:
            return [TextContent(type="text", text=f"No reasoning chains found in {chains_file}.")]

        filtered = []
        for ch in chains:
            conclusion = ch.get("conclusion", "")
            premises = ch.get("premises") or []

            if node_id:
                if node_id != conclusion and node_id not in premises:
                    continue

            if query:
                c_stmt = nodes.get(conclusion, {}).get("statement", "")
                p_stmts = " ".join(nodes.get(p, {}).get("statement", "") for p in premises)
                if query not in c_stmt.lower() and query not in p_stmts.lower():
                    continue

            filtered.append(ch)
            if len(filtered) >= limit:
                break

        if not filtered:
            return [TextContent(type="text", text="No matching reasoning chains found.")]

        out = [f"### LearnHarness Reasoning Chains ({len(filtered)} found)\n"]
        for ch in filtered:
            cid = ch.get("conclusion")
            c_node = nodes.get(cid, {})
            c_name = c_node.get("name", cid)
            c_stmt = c_node.get("statement", "")

            premises = ch.get("premises") or []
            premise_descs = []
            for pid in premises:
                p_node = nodes.get(pid, {})
                premise_descs.append(f"    - `{pid}`: {p_node.get('name', pid)} — {p_node.get('statement', '')}")

            out.append(
                f"#### Conclusion: **{c_name}** (`{cid}`)\n"
                f"*{c_stmt}*\n"
                f"**Required Premises (Prerequisites):**\n" + ("\n".join(premise_descs) if premise_descs else "    (None)")
            )

        return [TextContent(type="text", text="\n".join(out))]

    elif name == "learnharness_learner_profile":
        chats_dir = data_dir / "chats"
        nodes_file = data_dir / "graph" / "nodes.jsonl"

        recent_sessions = []
        low_confidence_topics = []
        high_confidence_topics = []

        if chats_dir.is_dir():
            files = sorted(chats_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:10]:
                doc = _read_json_file(f)
                if not doc or not isinstance(doc, dict):
                    continue
                title = doc.get("title") or f.stem
                goal = doc.get("goal") or doc.get("topic") or ""
                recent_sessions.append(f"`{f.stem}`: {title} ({goal})")

                for m in doc.get("messages") or []:
                    conf = m.get("confidence")
                    text = m.get("content", "")
                    if conf is not None:
                        topic_tag = title
                        if conf < 60:
                            low_confidence_topics.append(f"- **{topic_tag}**: Confidence {conf}% on question/topic")
                        elif conf >= 80:
                            high_confidence_topics.append(f"- **{topic_tag}**: Confirmed understanding {conf}%")

        node_count = len(_read_jsonl_file(nodes_file))

        profile = [
            "# Learner Knowledge Frontier Profile (from LearnHarness)",
            f"- **Accumulated Propositions in Graph**: {node_count}",
            f"- **Recent Learning Sessions**: {len(recent_sessions)}",
            "",
            "## Recent Goals & Study Topics",
            "\n".join(f"- {s}" for s in recent_sessions) if recent_sessions else "- No recorded sessions yet.",
            "",
            "## Discovered Struggle Points (Low Confidence / Hesitation)",
            "\n".join(low_confidence_topics[:5]) if low_confidence_topics else "- No explicit struggle points recorded.",
            "",
            "## Confirmed Strengths (High Confidence)",
            "\n".join(high_confidence_topics[:5]) if high_confidence_topics else "- No high-confidence records yet.",
            "",
            "## Pedagogical Guidelines for Odysseus Answers",
            "1. **Never Assume Prerequisite Knowledge**: Build from the learner's verified baseline one reasoning step at a time.",
            "2. **Address Confusions Directly**: If the question touches any low-confidence topics above, explicitly verify their intuition before moving to advanced applications.",
            "3. **Ask Interactive Checks**: Conclude substantive explanations with a 1-sentence verification question rather than monologue summaries.",
        ]
        return [TextContent(type="text", text="\n".join(profile))]

    elif name == "learnharness_live_status":
        status_info = {
            "data_dir": str(data_dir),
            "app_url": LEARNHARNESS_URL,
            "server_live": False,
            "models": [],
            "slots": {},
        }
        try:
            req = urllib.request.Request(f"{LEARNHARNESS_URL}/api/models", headers={"User-Agent": "Odysseus-MCP"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status_info["server_live"] = True
                status_info["slots"] = data.get("slots", {})
                status_info["models"] = [m.get("id") for m in data.get("models", [])[:5]]
        except Exception as e:
            status_info["error"] = str(e)

        return [TextContent(type="text", text=f"```json\n{json.dumps(status_info, indent=2)}\n```")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
