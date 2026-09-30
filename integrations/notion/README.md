# Notion (read-only)

A built-in MCP server (`mcp_servers/notion_server.py`) that lets the agent search
and read your Notion workspace live. It has one tool, `manage_notion`, with three
actions: `search`, `read` and `query`. It cannot create, edit or delete anything in
Notion, and it never writes to disk. Results are only cached in memory for about
45 seconds.

## Enable it

1. Create an internal integration at <https://www.notion.so/profile/integrations>
   with only the **Read content** capability.
2. Share the pages you want searched with it (page > ... > Connections; sub-pages
   inherit access).
3. Put the integration secret in `.env`:

   ```
   NOTION_TOKEN=your_secret_here
   ```

4. Restart Odysseus (`docker compose up -d`). The Docker Compose files already pass
   `NOTION_TOKEN` through; if it is unset the server is simply not registered.

Optional: install the `notion-search` skill so the model knows how to use the tool:

```bash
mkdir -p data/skills/notion
cp -R integrations/notion/skills/notion-search data/skills/notion/
```

## How it behaves

- Notion's search API matches page and database **titles** only. The tool also
  searches each keyword separately and ranks the merged results by how many appear
  in the title. Read the best hits to get the content; `read` takes `find=<words>`
  to return only the matching lines of a long page.
- Requests are paced at about 2.8 per second (Notion's average limit is 3), reuse
  connections, read page trees in parallel, and retry 429/5xx honoring
  `Retry-After`.
- Read-only is enforced in the tool schema and again in the request layer, which
  refuses anything except GETs, `POST /search` and `POST /databases/<id>/query`.
- Attachment links are pre-signed, so only file names and captions are shown. The
  token and query strings are never included in errors.
- Page text is returned labelled as data, not instructions.

Tests: `python -m pytest tests/test_notion_server.py`
