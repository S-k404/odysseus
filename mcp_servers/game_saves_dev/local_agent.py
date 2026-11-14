"""Drive the local Docker Model Runner model over the game_saves MCP server.

Same model and same MCP tools Odysseus uses; logs every tool call.
usage: local_agent.py "<task>" [max_rounds]
"""
import asyncio, json, os, sys, time, urllib.request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S"
URL = "http://127.0.0.1:12434/v1/chat/completions"
SERVER = StdioServerParameters(
    command=os.path.expanduser("~/Documents/Docker/Odysseus/.venv/bin/python"),
    args=[os.path.expanduser("~/Documents/Docker/Odysseus/mcp_servers/game_save_server.py")],
    env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": os.path.expanduser("~")},
)
SYSTEM = (
    "You edit local single-player game saves with the provided tools. Work step by step: "
    "find the save files, read them with a narrow query, then patch. Only patch values that "
    "clearly hold currency or unlock/gallery state. Never patch config/settings files. "
    "When finished, reply with a short summary listing every file you changed and the new values."
)


def llm(messages, tools):
    body = {"model": MODEL, "messages": messages, "tools": tools, "max_tokens": 6000, "temperature": 0.2}
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=600))["choices"][0]["message"]
        except Exception as e:  # model reload or transient runner error
            print(f"[llm retry {attempt + 1}: {e}]", flush=True)
            time.sleep(10)
    raise RuntimeError("local model unavailable")


async def main(task, max_rounds):
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tl = (await s.list_tools()).tools
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}} for t in tl]
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
            for rnd in range(max_rounds):
                m = llm(messages, tools)
                calls = m.get("tool_calls") or []
                messages.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls} if calls else {"role": "assistant", "content": m.get("content") or ""})
                if not calls:
                    print("\n=== FINAL ===\n" + (m.get("content") or ""), flush=True)
                    return
                for c in calls:
                    args = json.loads(c["function"]["arguments"] or "{}")
                    print(f"\n[{rnd}] CALL {c['function']['name']} {json.dumps(args, ensure_ascii=False)[:400]}", flush=True)
                    res = await s.call_tool(c["function"]["name"], args)
                    text = res.content[0].text if res.content else ""
                    print("  -> " + text[:700].replace("\n", "\n     "), flush=True)
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": text[:8000]})
            print("\n=== STOPPED: round limit ===")


def check_ram(need_gib=18):
    """Same idea as Odysseus's RAM guard: this script calls the model runner directly, so it must not load the
    35B model into a Mac that cannot spare the memory. It stops instead of using a smaller model, because the
    smaller one is less reliable at editing saves. ODY_RAM_GUARD=0 skips the check."""
    import os, re, subprocess
    if os.environ.get("ODY_RAM_GUARD") == "0":
        return
    if os.environ.get("ODY_SPARE_GIB"):
        spare = float(os.environ["ODY_SPARE_GIB"])
    else:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        page = int(re.search(r"page size of (\d+)", out).group(1))
        pages = {k: int(v.rstrip(".")) for k, v in re.findall(r"^Pages ([a-z ]+):\s+([\d.]+)", out, re.M)}
        spare = (pages.get("free", 0) + pages.get("inactive", 0) + pages.get("speculative", 0)) * page / 2**30 - 4
    if spare < need_gib:
        sys.exit(f"not enough memory for the 35B model: about {spare:.0f} GiB can be spared, it needs about {need_gib}. "
                 f"Close some apps and retry (ODY_RAM_GUARD=0 skips this check and may freeze the Mac).")


if __name__ == "__main__":
    check_ram()
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15))
