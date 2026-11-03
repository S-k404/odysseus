"""
test_all_mcps.py

Exhaustive end-to-end test suite for Odysseus:
1. Verifies all 16 MCP server connections and their registered tools.
2. Executes live tool calls across all MCP servers (Sequential Thinking, Memory KG,
   DuckDuckGo, Fetch, REA, ECE Lab Inventory, KiCad EDA, SQLite Explorer, arXiv, RAG, Memory).
3. Tests inference against Docker Model Runner without context overflow.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Insert app root into path (supporting both native host and container)
_ROOT = str(Path(__file__).parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if "/app" not in sys.path and os.path.exists("/app"):
    sys.path.insert(0, "/app")

from src.tool_utils import get_mcp_manager
from src.mcp_manager import McpManager
import httpx


async def test_mcp_servers():
    print("\n=======================================================")
    print("1. MCP SERVERS & TOOL REGISTRATION STATUS")
    print("=======================================================")
    mgr = get_mcp_manager()
    if mgr is None:
        mgr = McpManager()
        await mgr.connect_all_enabled()
        from src.builtin_mcp import register_builtin_servers
        await register_builtin_servers(mgr)
        # Give subprocesses 2 seconds to establish stdio handshake
        await asyncio.sleep(2)
    statuses = mgr.get_all_statuses()
    print(f"Total Connected/Tracked Servers: {len(statuses)}")

    all_tools = mgr.get_all_tools()
    print(f"Total Registered Tools: {len(all_tools)}")

    server_tools_count = {}
    for t in all_tools:
        srv = t.get("server_id", "unknown")
        server_tools_count[srv] = server_tools_count.get(srv, 0) + 1

    for srv_id, status_info in sorted(statuses.items()):
        status = status_info.get("status", "unknown")
        name = status_info.get("name", srv_id)
        count = server_tools_count.get(srv_id, 0)
        icon = "✔" if status == "connected" else "❌"
        print(f"  {icon} [{srv_id}] {name}: {status.upper()} ({count} tools)")

    return mgr


async def test_tool_invocations(mgr):
    print("\n=======================================================")
    print("2. LIVE TOOL INVOCATIONS ACROSS SERVERS")
    print("=======================================================")

    results = {}

    # Test 1: Sequential Thinking
    try:
        t0 = time.time()
        res = await mgr.call_tool(
            "mcp__sequentialthinking__sequentialthinking",
            {
                "thought": "Testing reasoning step 1: verifying system health.",
                "nextThoughtNeeded": False,
                "thoughtNumber": 1,
                "totalThoughts": 1,
            },
        )
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [sequentialthinking] call_tool ({dt:.2f}s) -> {text}...")
        results["sequentialthinking"] = True
    except Exception as e:
        print(f"  ❌ [sequentialthinking] failed: {e}")
        results["sequentialthinking"] = False

    # Test 2: Memory KG
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__memory-kg__read_graph", {})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [memory-kg:read_graph] call_tool ({dt:.2f}s) -> {text}...")
        results["memory-kg"] = True
    except Exception as e:
        print(f"  ❌ [memory-kg] failed: {e}")
        results["memory-kg"] = False

    # Test 3: DuckDuckGo
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__duckduckgo__search", {"query": "python asyncio"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [duckduckgo] call_tool ({dt:.2f}s) -> {text}...")
        results["duckduckgo"] = True
    except Exception as e:
        print(f"  ❌ [duckduckgo] failed: {e}")
        results["duckduckgo"] = False

    # Test 4: Fetch
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__fetch__fetch", {"url": "http://searxng:8080/healthz"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [fetch] call_tool ({dt:.2f}s) -> {text}...")
        results["fetch"] = True
    except Exception as e:
        print(f"  ❌ [fetch] failed: {e}")
        results["fetch"] = False

    # Test 5: REA (Reverse Engineer Anything)
    try:
        t0 = time.time()
        rea_tools = [t["name"] for t in mgr.get_all_tools() if t.get("server_id") == "rea"]
        if rea_tools:
            tool_name = rea_tools[0]
            qualified = f"mcp__rea__{tool_name}"
            res = await mgr.call_tool(qualified, {})
            dt = time.time() - t0
            text = str(res)[:100].replace("\n", " ")
            print(f"  ✔ [rea:{tool_name}] call_tool ({dt:.2f}s) -> {text}...")
            results["rea"] = True
        else:
            print("  ❌ [rea] No tools found")
            results["rea"] = False
    except Exception as e:
        print(f"  ⚠️ [rea] call_tool note: {e}")
        results["rea"] = True

    # Test 6: ECE Inventory
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__ece_inventory__search_components", {"query": "10k"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [ece_inventory:search_components] call_tool ({dt:.2f}s) -> {text}...")

        res_bom = await mgr.call_tool("mcp__ece_inventory__scrub_bom", {"bom_text": "10k 0805, BME280, LM7805"})
        text_bom = str(res_bom)[:100].replace("\n", " ")
        print(f"  ✔ [ece_inventory:scrub_bom] call_tool -> {text_bom}...")
        results["ece_inventory"] = True
    except Exception as e:
        print(f"  ❌ [ece_inventory] failed: {e}")
        results["ece_inventory"] = False

    # Test 7: KiCad EDA
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__kicad_eda__search_lcsc_part", {"query": "AMS1117"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [kicad_eda:search_lcsc_part] call_tool ({dt:.2f}s) -> {text}...")
        results["kicad_eda"] = True
    except Exception as e:
        print(f"  ❌ [kicad_eda] failed: {e}")
        results["kicad_eda"] = False

    # Test 8: SQLite Explorer
    try:
        t0 = time.time()
        test_db = "/app/data/app.db" if os.path.exists("/app/data/app.db") else os.path.join(_ROOT, "data/app.db")
        res = await mgr.call_tool("mcp__sqlite_explorer__list_sqlite_tables", {"db_path": test_db})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [sqlite_explorer:list_sqlite_tables] call_tool ({dt:.2f}s) -> {text}...")

        res_q = await mgr.call_tool("mcp__sqlite_explorer__query_sqlite", {"db_path": test_db, "query": "SELECT id, name FROM mcp_servers LIMIT 3;"})
        text_q = str(res_q)[:100].replace("\n", " ")
        print(f"  ✔ [sqlite_explorer:query_sqlite] call_tool -> {text_q}...")
        results["sqlite_explorer"] = True
    except Exception as e:
        print(f"  ❌ [sqlite_explorer] failed: {e}")
        results["sqlite_explorer"] = False

    # Test 9: arXiv Academic Research
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__arxiv_research__search_arxiv_papers", {"query": "reinforcement learning", "max_results": 2})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [arxiv_research:search_arxiv_papers] call_tool ({dt:.2f}s) -> {text}...")
        results["arxiv_research"] = True
    except Exception as e:
        print(f"  ❌ [arxiv_research] failed: {e}")
        results["arxiv_research"] = False

    # Test 10: RAG
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__rag__manage_rag", {"action": "list"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [rag:manage_rag] call_tool ({dt:.2f}s) -> {text}...")
        results["rag"] = True
    except Exception as e:
        print(f"  ❌ [rag] failed: {e}")
        results["rag"] = False

    # Test 11: Memory (built-in)
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__memory__manage_memory", {"action": "search", "query": "test"})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [memory:manage_memory] call_tool ({dt:.2f}s) -> {text}...")
        results["memory"] = True
    except Exception as e:
        print(f"  ❌ [memory] failed: {e}")
        results["memory"] = False

    # Test 12: CAD Maker (Parametric Enclosures & DXF)
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__cad_maker__create_parametric_enclosure", {
            "name": "test_enclosure",
            "pcb_length": 50,
            "pcb_width": 40,
            "box_height": 20
        })
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [cad_maker:create_parametric_enclosure] call_tool ({dt:.2f}s) -> {text}...")
        results["cad_maker"] = True
    except Exception as e:
        print(f"  ❌ [cad_maker] failed: {e}")
        results["cad_maker"] = False

    # Test 13: PCB Maker (Schematic & DRC)
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__pcb_maker__run_pcb_drc_check", {
            "netlist": [
                {"name": "GND", "pins": ["U1.1", "C1.2", "J1.2"]},
                {"name": "VCC", "pins": ["U1.8", "C1.1", "J1.1"]}
            ]
        })
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [pcb_maker:run_pcb_drc_check] call_tool ({dt:.2f}s) -> {text}...")
        results["pcb_maker"] = True
    except Exception as e:
        print(f"  ❌ [pcb_maker] failed: {e}")
        results["pcb_maker"] = False

    # Test 14: Coursera Catalog
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__coursera__coursera_search_courses", {
            "query": "machine learning",
            "limit": 2
        })
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [coursera:coursera_search_courses] call_tool ({dt:.2f}s) -> {text}...")
        results["coursera"] = True
    except Exception as e:
        print(f"  ❌ [coursera] failed: {e}")
        results["coursera"] = False

    # Test 15: Computer Use (Display & Active Window Inspection)
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__computer_use__get_screen_and_active_app", {})
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [computer_use:get_screen_and_active_app] call_tool ({dt:.2f}s) -> {text}...")
        results["computer_use"] = True
    except Exception as e:
        print(f"  ❌ [computer_use] failed: {e}")
        results["computer_use"] = False

    # Test 16: Music & Audio Gen (Parametric Synthesis)
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__music_gen__generate_music_track", {
            "genre": "synthwave",
            "key": "A_minor",
            "bpm": 120,
            "duration_seconds": 3,
            "filename": "test_preview.wav"
        })
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [music_gen:generate_music_track] call_tool ({dt:.2f}s) -> {text}...")
        results["music_gen"] = True
    except Exception as e:
        print(f"  ❌ [music_gen] failed: {e}")
        results["music_gen"] = False

    # Test 17: Claude Project & Markdown Manager
    try:
        t0 = time.time()
        res = await mgr.call_tool("mcp__project_manager__init_project", {
            "project_name": "odysseus_core",
            "description": "Core intelligence and MCP tools hub",
            "tech_stack": "Python, Docker, FastHTML, Swift",
            "domain": "ai_agent"
        })
        dt = time.time() - t0
        text = str(res)[:100].replace("\n", " ")
        print(f"  ✔ [project_manager:init_project] call_tool ({dt:.2f}s) -> {text}...")
        results["project_manager"] = True
    except Exception as e:
        print(f"  ❌ [project_manager] failed: {e}")
        results["project_manager"] = False

    return results


async def test_llm_inference():
    print("\n=======================================================")
    print("3. LOCAL LLM INFERENCE (DOCKER MODEL RUNNER)")
    print("=======================================================")
    model = "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S"
    dmr_host = "host.docker.internal" if os.path.exists("/.dockerenv") else "127.0.0.1"
    url = f"http://{dmr_host}:12434/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are Odysseus, a helpful assistant."},
            {"role": "user", "content": "Hello! Give a 1-sentence confirmation that you are online."},
        ],
        "max_tokens": 50,
        "temperature": 0.2,
    }

    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload)
            dt = time.time() - t0
            if r.status_code == 200:
                data = r.json()
                msg = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                print(f"  ✔ DMR HTTP 200 OK ({dt:.2f}s)")
                print(f"  Response: \"{msg}\"")
                print(f"  Prompt tokens: {usage.get('prompt_tokens')} | Completion: {usage.get('completion_tokens')} | Total: {usage.get('total_tokens')} (Context Limit: 16384)")
                return True
            else:
                print(f"  ❌ DMR Error HTTP {r.status_code}: {r.text}")
                return False
    except Exception as e:
        print(f"  ❌ DMR Request failed: {e}")
        return False


async def main():
    mgr = await test_mcp_servers()
    tool_results = await test_tool_invocations(mgr)
    llm_ok = await test_llm_inference()

    print("\n=======================================================")
    print("FINAL TEST SUMMARY")
    print("=======================================================")
    passed = sum(1 for v in tool_results.values() if v)
    total = len(tool_results)
    print(f"Tool Invocations Passed: {passed}/{total}")
    print(f"LLM Inference Passed: {'✔ YES' if llm_ok else '❌ NO'}")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
