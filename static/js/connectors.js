// static/js/connectors.js
// Connectors window: lists Odysseus's real MCP servers (/api/mcp/servers),
// shows their tools, manages servers you added, and adds new ones.

// Brand icons, keyed by the names SERVER_META refers to.
const ICONS = {
  "blender": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><circle cx=\"12\" cy=\"12\" r=\"10\" fill=\"#EA7600\"/><path d=\"M12 6a6 6 0 1 0 6 6 6 6 0 0 0-6-6zm0 9a3 3 0 1 1 3-3 3 3 0 0 1-3 3z\" fill=\"#fff\"/><circle cx=\"12\" cy=\"12\" r=\"1.5\" fill=\"#0056B3\"/><path d=\"M12 2v4M2 12h4M12 18v4M18 12h4\" stroke=\"#fff\" stroke-width=\"1.5\" stroke-linecap=\"round\"/></svg>",
  "canva": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#00C4CC\"/><path d=\"M16.8 9.2c-.3-1.6-1.5-2.8-3.1-3-2.1-.2-4.1 1.2-4.5 3.3-.5 2.5 1.1 5 3.6 5.4 1.4.2 2.7-.4 3.5-1.4.3-.4.2-1-.2-1.3-.4-.3-1-.2-1.3.2-.5.6-1.3.9-2.1.8-1.4-.2-2.3-1.5-2-2.8.2-1.2 1.3-2 2.5-1.9 1 .1 1.7.8 1.9 1.7.1.5.6.8 1.1.7.5-.1.8-.6.6-1.6z\" fill=\"#fff\"/></svg>",
  "chrome": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><circle cx=\"12\" cy=\"12\" r=\"10\" fill=\"#202124\"/><circle cx=\"12\" cy=\"12\" r=\"4.5\" fill=\"#1a73e8\"/><path d=\"M12 2a10 10 0 0 1 8.66 5H12\" stroke=\"#ea4335\" stroke-width=\"3\" stroke-linecap=\"round\"/><path d=\"M20.66 7A10 10 0 0 1 12 22l4.33-7.5\" stroke=\"#fbbc05\" stroke-width=\"3\" stroke-linecap=\"round\"/><path d=\"M12 22A10 10 0 0 1 3.34 7L12 12\" stroke=\"#34a853\" stroke-width=\"3\" stroke-linecap=\"round\"/></svg>",
  "cloudflare": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#F38020\"/><path d=\"M17.5 14.5a2.5 2.5 0 0 0 .5-4.95 4 4 0 0 0-7.8-1.05 3 3 0 0 0-3.2 3.1 2.5 2.5 0 0 0 .5 4.9h10z\" fill=\"#fff\"/></svg>",
  "coursera": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#0056D2\"/><path d=\"M12 5.5l5.5 3.5v6L12 18.5 6.5 15V9L12 5.5z\" stroke=\"#fff\" stroke-width=\"2\" stroke-linejoin=\"round\"/><circle cx=\"12\" cy=\"12\" r=\"2.2\" fill=\"#fff\"/></svg>",
  "figma": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#2C2D30\"/><path d=\"M8 6a2 2 0 0 1 2-2h2v4H10a2 2 0 0 1-2-2z\" fill=\"#F24E1E\"/><path d=\"M12 4h2a2 2 0 1 1 0 4h-2V4z\" fill=\"#FF7262\"/><path d=\"M8 10a2 2 0 0 1 2-2h2v4H10a2 2 0 0 1-2-2z\" fill=\"#A259FF\"/><path d=\"M12 10h2a2 2 0 1 1 0 4h-2v-4z\" fill=\"#1ABCFE\"/><path d=\"M8 14a2 2 0 0 1 2-2h2v2a2 2 0 0 1-4 0z\" fill=\"#0ACF83\"/></svg>",
  "github": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#181717\"/><path fill-rule=\"evenodd\" clip-rule=\"evenodd\" d=\"M12 4C7.58 4 4 7.58 4 12c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 20 12c0-4.42-3.58-8-8-8z\" fill=\"#fff\"/></svg>",
  "gmail": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#fff\"/><path d=\"M5 7l7 5 7-5v10H5V7z\" fill=\"#EA4335\"/><path d=\"M5 7l7 5V7H5z\" fill=\"#C5221F\"/><path d=\"M19 7l-7 5V7h7z\" fill=\"#C5221F\"/></svg>",
  "gdrive": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#fff\"/><path d=\"M9.5 5.5l5 8.5H4.5l5-8.5z\" fill=\"#0066DA\"/><path d=\"M14.5 14h5l-5-8.5h-5l5 8.5z\" fill=\"#00AC47\"/><path d=\"M4.5 14h10l-2.5 4.5h-10l2.5-4.5z\" fill=\"#FFBA00\"/></svg>",
  "notion": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#000\"/><path d=\"M6.5 6.5l3.5.5v11.5l-3.5-.5V6.5zm4 0h3l3.5 7.5V6.5h2.5v12h-3L13 11v7.5h-2.5V6.5z\" fill=\"#fff\"/></svg>",
  "pubmed": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#20558A\"/><path d=\"M7 6c2 3 8 3 10 0M7 12c2 3 8 3 10 0M7 18c2 3 8 3 10 0\" stroke=\"#fff\" stroke-width=\"1.8\" stroke-linecap=\"round\"/><line x1=\"12\" y1=\"4\" x2=\"12\" y2=\"20\" stroke=\"#fff\" stroke-width=\"2\" stroke-linecap=\"round\"/></svg>",
  "obsidian": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#7C3AED\"/><path d=\"M12 4l6 7-6 9-6-9 6-7z\" fill=\"#fff\"/></svg>",
  "kicad": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#185698\"/><circle cx=\"12\" cy=\"12\" r=\"6\" stroke=\"#fff\" stroke-width=\"2\"/><line x1=\"12\" y1=\"2\" x2=\"12\" y2=\"6\" stroke=\"#fff\" stroke-width=\"2\"/><line x1=\"12\" y1=\"18\" x2=\"12\" y2=\"22\" stroke=\"#fff\" stroke-width=\"2\"/><line x1=\"2\" y1=\"12\" x2=\"6\" y2=\"12\" stroke=\"#fff\" stroke-width=\"2\"/><line x1=\"18\" y1=\"12\" x2=\"22\" y2=\"12\" stroke=\"#fff\" stroke-width=\"2\"/></svg>",
  "arxiv": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#B31B1B\"/><path d=\"M7 16.5C8.5 18 10.2 19 12 19s3.5-1 5-2.5\" stroke=\"#fff\" stroke-width=\"2\" stroke-linecap=\"round\"/><circle cx=\"9\" cy=\"9.5\" r=\"1.5\" fill=\"#fff\"/><circle cx=\"15\" cy=\"9.5\" r=\"1.5\" fill=\"#fff\"/><path d=\"M12 6v6\" stroke=\"#fff\" stroke-width=\"2\" stroke-linecap=\"round\"/></svg>",
  "sqlite": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#003B57\"/><ellipse cx=\"12\" cy=\"7\" rx=\"6\" ry=\"2.5\" fill=\"#0079C1\"/><path d=\"M6 7v4c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5V7\" stroke=\"#37B0E6\" stroke-width=\"1.6\" fill=\"none\"/><path d=\"M6 11v4c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5V11\" stroke=\"#37B0E6\" stroke-width=\"1.6\" fill=\"none\"/><ellipse cx=\"12\" cy=\"7\" rx=\"6\" ry=\"2.5\" stroke=\"#fff\" stroke-width=\"1.4\"/></svg>",
  "cad_maker": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#0284C7\"/><path d=\"M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z\" stroke=\"#fff\" stroke-width=\"1.8\" stroke-linejoin=\"round\"/><path d=\"M12 12l8-4.5M12 12v9M12 12L4 7.5\" stroke=\"#fff\" stroke-width=\"1.8\"/></svg>",
  "pcb_maker": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#059669\"/><rect x=\"6\" y=\"6\" width=\"12\" height=\"12\" rx=\"2\" stroke=\"#fff\" stroke-width=\"1.8\"/><circle cx=\"9\" cy=\"9\" r=\"1.5\" fill=\"#fff\"/><circle cx=\"15\" cy=\"15\" r=\"1.5\" fill=\"#fff\"/><path d=\"M9 10.5v3h3\" stroke=\"#fff\" stroke-width=\"1.5\"/></svg>",
  "sequentialthinking": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#D97757\"/><path d=\"M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4\" stroke=\"#fff\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>",
  "memory-kg": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#4B5563\"/><circle cx=\"8\" cy=\"8\" r=\"3\" fill=\"#fff\"/><circle cx=\"16\" cy=\"8\" r=\"3\" fill=\"#fff\"/><circle cx=\"12\" cy=\"16\" r=\"3\" fill=\"#fff\"/><line x1=\"8\" y1=\"8\" x2=\"16\" y2=\"8\" stroke=\"#fff\" stroke-width=\"1.5\"/><line x1=\"8\" y1=\"8\" x2=\"12\" y2=\"16\" stroke=\"#fff\" stroke-width=\"1.5\"/><line x1=\"16\" y1=\"8\" x2=\"12\" y2=\"16\" stroke=\"#fff\" stroke-width=\"1.5\"/></svg>",
  "computer_use": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#3B82F6\"/><rect x=\"5\" y=\"5\" width=\"14\" height=\"10\" rx=\"1.5\" stroke=\"#fff\" stroke-width=\"1.6\"/><line x1=\"12\" y1=\"15\" x2=\"12\" y2=\"18\" stroke=\"#fff\" stroke-width=\"1.6\"/><line x1=\"8\" y1=\"18\" x2=\"16\" y2=\"18\" stroke=\"#fff\" stroke-width=\"1.6\"/></svg>",
  "music_gen": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#8B5CF6\"/><path d=\"M9 17V7l10-2v10\" stroke=\"#fff\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/><circle cx=\"7\" cy=\"17\" r=\"2\" fill=\"#fff\"/><circle cx=\"17\" cy=\"15\" r=\"2\" fill=\"#fff\"/></svg>",
  "project_manager": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\"><rect width=\"24\" height=\"24\" rx=\"6\" fill=\"#D97757\"/><path d=\"M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z\" stroke=\"#fff\" stroke-width=\"1.6\" stroke-linejoin=\"round\"/><path d=\"M9 13h6M9 10h3\" stroke=\"#fff\" stroke-width=\"1.5\" stroke-linecap=\"round\"/></svg>",
};

// Display details for built-in servers, keyed by the id /api/mcp/servers
// reports. group: 'service' = talks to an online service, 'local' = runs on
// this machine. env lists the .env settings the server reads.
const SERVER_META = {
  builtin_browser: { label: "Browser", group: "local", icon: "chrome", desc: "Browser automation with Playwright: open pages, click, fill forms, take screenshots." },
  email: { label: "Email", group: "service", icon: "gmail", desc: "Read, search and send email over IMAP/SMTP.", env: ["IMAP_HOST", "IMAP_USER", "SMTP_HOST"] },
  notion: { label: "Notion", group: "service", icon: "notion", desc: "Search and read your Notion workspace (read-only).", env: ["NOTION_TOKEN"] },
  github: { label: "GitHub", group: "service", icon: "github", desc: "Search repositories, read files and list issues. Works without a token for public repos.", env: ["GITHUB_TOKEN (optional)"] },
  gdrive: { label: "Google Drive", group: "service", icon: "gdrive", desc: "Search Drive files and read their metadata.", env: ["GOOGLE_DRIVE_TOKEN"] },
  figma: { label: "Figma", group: "service", icon: "figma", desc: "Inspect Figma files and extract design tokens.", env: ["FIGMA_ACCESS_TOKEN"] },
  cloudflare: { label: "Cloudflare", group: "service", icon: "cloudflare", desc: "List Workers and look up DNS records.", env: ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"] },
  onshape_cad: { label: "Onshape", group: "service", desc: "Browse your Onshape CAD documents and their elements.", env: ["ONSHAPE_ACCESS_KEY", "ONSHAPE_SECRET_KEY"] },
  arxiv_research: { label: "arXiv", group: "service", icon: "arxiv", desc: "Search arXiv and read paper abstracts." },
  pubmed: { label: "PubMed", group: "service", icon: "pubmed", desc: "Search PubMed and read abstracts." },
  coursera: { label: "Coursera", group: "service", icon: "coursera", desc: "Search the Coursera course catalog." },
  fetch: { label: "Fetch", group: "service", desc: "Fetch web pages as Markdown (runs in Docker)." },
  duckduckgo: { label: "DuckDuckGo", group: "service", desc: "Web search through DuckDuckGo (runs in Docker)." },
  obsidian: { label: "Obsidian", group: "local", icon: "obsidian", desc: "Read and write notes in your Obsidian vault.", env: ["OBSIDIAN_VAULT_PATH or OBSIDIAN_VAULT_HOST_DIR"] },
  blender: { label: "Blender", group: "local", icon: "blender", desc: "Inspect scenes, run Python inside Blender and render thumbnails." },
  cad_maker: { label: "CAD Maker", group: "local", icon: "cad_maker", desc: "Parametric enclosures, STL/OpenSCAD parts and DXF drawings, saved to workspace/cad." },
  pcb_maker: { label: "PCB Maker", group: "local", icon: "pcb_maker", desc: "KiCad schematics, board outlines and JLCPCB BOM/CPL files; real DRC/ERC through kicad-cli." },
  kicad_eda: { label: "KiCad Inspector", group: "local", icon: "kicad", desc: "Read KiCad schematics and boards, and search LCSC/JLCPCB parts." },
  ece_inventory: { label: "ECE Lab Inventory", group: "local", desc: "Search lab stock from Homebox and check a BOM against it." },
  sqlite_explorer: { label: "SQLite Explorer", group: "local", icon: "sqlite", desc: "Read-only queries against local SQLite databases." },
  computer_use: { label: "Computer Use", group: "local", icon: "computer_use", desc: "Screenshots, screen recording, clicks and typing on this Mac." },
  music_gen: { label: "Music & Voice", group: "local", icon: "music_gen", desc: "Synthesised music, Kokoro speech and Whisper transcription.", env: ["SPEACHES_BASE_URL (optional)"] },
  canva: { label: "Design Helper", group: "local", icon: "canva", desc: "Canva-style format sizes, colour palettes and layout ideas. Works offline; it doesn't connect to a Canva account." },
  project_manager: { label: "Projects", group: "local", icon: "project_manager", desc: "Project folders with CLAUDE.md, docs and task files under workspace/projects." },
  rag: { label: "Document Search", group: "local", desc: "Search the documents you've indexed in Odysseus." },
  memory: { label: "Memory", group: "local", desc: "Odysseus long-term memory." },
  image_gen: { label: "Image Generation", group: "local", desc: "Generate images with the configured image model." },
  "memory-kg": { label: "Knowledge Graph", group: "local", icon: "memory-kg", desc: "Entity/relation memory stored in a Docker volume." },
  sequentialthinking: { label: "Sequential Thinking", group: "local", icon: "sequentialthinking", desc: "A step-by-step reasoning scratchpad (runs in Docker)." },
  rea: { label: "Reverse Engineer Anything", group: "local", desc: "Analyse files and binaries in a Docker sandbox." },
};

// Servers that can be added in one click, grouped for the Discover tab.
// Remote entries marked `checked` connected without signing in when this list
// was written; npx/uvx/docker ones are downloaded on first start and the add
// result shows whether they came up. `inputs` become env vars, or replace
// "{key}" in args when `arg` is set.
const CATALOG = [
  // Open-source / self-hosted versions of the connectors Claude offers.
  { id: "notion-official", group: "claude", name: "Notion", desc: "Notion's own MCP server: search, read and edit pages and databases.", transport: "stdio", command: "npx", args: ["-y", "@notionhq/notion-mcp-server"], note: "Uses NOTION_TOKEN from your .env. Notion now favours its hosted server, so this one gets fewer updates." },
  { id: "google-workspace", group: "claude", name: "Google Workspace", desc: "Gmail, Calendar, Drive, Docs and Sheets (open source).", transport: "stdio", command: "uvx", args: ["workspace-mcp", "--tool-tier", "core"], env: { WORKSPACE_MCP_PORT: "8766" }, inputs: [
      { key: "GOOGLE_OAUTH_CLIENT_ID", label: "Google OAuth client ID", placeholder: "…apps.googleusercontent.com" },
      { key: "GOOGLE_OAUTH_CLIENT_SECRET", label: "Google OAuth client secret", placeholder: "Client secret", secret: true },
    ], note: "Needs a Desktop OAuth client from Google Cloud Console. The first tool call asks you to sign in to Google." },
  { id: "github-official", group: "claude", name: "GitHub", desc: "GitHub's official server: repos, issues, pull requests, code search, Actions.", transport: "stdio", command: "docker", args: ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"], inputs: [
      { key: "GITHUB_PERSONAL_ACCESS_TOKEN", label: "GitHub personal access token", placeholder: "github_pat_…", secret: true },
    ] },
  { id: "figma-framelink", group: "claude", name: "Figma", desc: "Read Figma files and frames as layout and styles for building UIs (Framelink, open source).", transport: "stdio", command: "npx", args: ["-y", "figma-developer-mcp", "--stdio"], inputs: [
      { key: "FIGMA_API_KEY", label: "Figma personal access token", placeholder: "figd_…", secret: true },
    ] },
  { id: "canva", group: "claude", name: "Canva", desc: "Canva's hosted server: search, create and export your designs.", transport: "http", url: "https://mcp.canva.com/mcp", note: "Sign-in with your Canva account." },

  // Matches your hardware, CAD, homelab and automation work.
  { id: "blender-live", group: "work", name: "Blender (live)", desc: "Drive a running Blender: build and edit scenes, materials, Poly Haven assets.", transport: "stdio", command: "uvx", args: ["mcp-for-blender"], note: "Run `uvx mcp-for-blender install-addon`, enable “MCP for Blender” in Blender's add-ons, then start it from the N-panel." },
  { id: "docker", group: "work", name: "Docker", desc: "List, start, stop, inspect and read logs of your containers, images and volumes.", transport: "stdio", command: "uvx", args: ["mcp-server-docker"], note: "It can also stop and remove containers, so keep tool approval on." },
  { id: "n8n", group: "work", name: "n8n", desc: "n8n node docs and workflow validation; with an API key, build and run workflows on your n8n.", transport: "stdio", command: "npx", args: ["-y", "n8n-mcp"], env: { MCP_MODE: "stdio", LOG_LEVEL: "error", DISABLE_CONSOLE_OUTPUT: "true", WEBHOOK_SECURITY_MODE: "moderate" }, inputs: [
      { key: "N8N_API_URL", label: "n8n URL (optional)", placeholder: "http://localhost:5678", optional: true },
      { key: "N8N_API_KEY", label: "n8n API key (optional)", placeholder: "From n8n → Settings → API", secret: true, optional: true },
    ] },

  // Docs and search.
  { id: "exa", group: "docs", name: "Exa Search", desc: "Web search and page fetching tuned for AI answers.", transport: "http", url: "https://mcp.exa.ai/mcp", checked: true },
  { id: "context7", group: "docs", name: "Context7", desc: "Current documentation for libraries and frameworks, for coding.", transport: "stdio", command: "npx", args: ["-y", "@upstash/context7-mcp"] },
  { id: "deepwiki", group: "docs", name: "DeepWiki", desc: "Ask questions about any public GitHub repository's code and docs.", transport: "http", url: "https://mcp.deepwiki.com/mcp", checked: true },
  { id: "huggingface", group: "docs", name: "Hugging Face", desc: "Search models, datasets and Spaces on the Hub.", transport: "http", url: "https://huggingface.co/mcp", checked: true },
  { id: "cloudflare-docs", group: "docs", name: "Cloudflare Docs", desc: "Search Cloudflare's developer documentation.", transport: "http", url: "https://docs.mcp.cloudflare.com/mcp", checked: true },
  { id: "ms-learn", group: "docs", name: "Microsoft Learn", desc: "Search Microsoft and Azure docs and code samples.", transport: "http", url: "https://learn.microsoft.com/api/mcp", checked: true },
  { id: "time", group: "docs", name: "Time", desc: "Current time and timezone conversion (Anthropic reference server).", transport: "stdio", command: "uvx", args: ["mcp-server-time"] },
  { id: "filesystem", group: "docs", name: "Filesystem", desc: "Read and write files inside one folder you choose (Anthropic reference server).", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "{path}"], inputs: [
      { key: "path", label: "Folder", placeholder: "/Users/you/Documents", arg: true },
    ] },
  { id: "git", group: "docs", name: "Git", desc: "Read history, diffs and status of a local repository (Anthropic reference server).", transport: "stdio", command: "uvx", args: ["mcp-server-git", "--repository", "{path}"], inputs: [
      { key: "path", label: "Repository folder", placeholder: "/Users/you/code/project", arg: true },
    ] },
];

const CATALOG_GROUPS = [
  { key: "claude", title: "Open-source versions of Claude's connectors" },
  { key: "work", title: "For your hardware, CAD and homelab work" },
  { key: "docs", title: "Docs & search" },
];

const API = "/api/mcp/servers";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusOf(s) {
  if (s.is_enabled === false) return { cls: "off", text: "Disabled" };
  if (s.needs_oauth || s.status === "needs_auth") return { cls: "warn", text: "Needs sign-in" };
  if (s.status === "connected") return { cls: "ok", text: "Connected" };
  if (s.status === "error") return { cls: "err", text: "Error" };
  if (s.status === "connecting") return { cls: "warn", text: "Connecting" };
  return { cls: "off", text: "Disconnected" };
}

class ConnectorsManager {
  constructor() {
    this.modal = null;
    this.servers = [];
    this.loadError = "";
    this.view = "installed"; // installed | discover | add | detail
    this.query = "";
    this.detailId = null;
    this.detailMsg = "";
    this.discoverMsgs = {};
    this.focusGroup = null;
  }

  init() {
    this.modal = document.getElementById("connectors-modal");
    if (!this.modal) return;
    this.body = this.modal.querySelector("#connectors-body");

    const bind = (id, fn) => { const b = document.getElementById(id); if (b) b.addEventListener("click", fn); };
    bind("tool-connectors-btn", () => this.open("connectors"));
    bind("rail-connectors", () => this.open("connectors"));
    bind("tool-extensions-btn", () => this.open("extensions"));
    bind("connectors-add-btn", () => this.show("add"));
    bind("connectors-refresh-btn", () => this.load());

    this.modal.querySelector(".connectors-close-btn")?.addEventListener("click", () => this.close());
    this.modal.addEventListener("click", (e) => { if (e.target === this.modal) this.close(); });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || this.modal.classList.contains("hidden")) return;
      if (this.view === "detail" || this.view === "add") this.show("installed");
      else this.close();
    });

    this.modal.querySelectorAll("[data-connectors-tab]").forEach(btn => {
      btn.addEventListener("click", () => this.show(btn.dataset.connectorsTab));
    });

    const search = this.modal.querySelector("#connectors-search-input");
    if (search) {
      search.addEventListener("input", () => {
        this.query = search.value.toLowerCase().trim();
        if (this.view === "detail" || this.view === "add") this.view = "installed";
        this.render();
      });
    }
  }

  open(mode = "connectors") {
    if (!this.modal) return;
    if (window.odysseusDismissAllModals) window.odysseusDismissAllModals("connectors-modal");
    this.modal.classList.remove("hidden");
    this.focusGroup = mode === "extensions" ? "local" : null;
    this.view = "installed";
    this.render();
    this.load();
  }

  close() {
    if (!this.modal) return;
    this.modal.classList.add("hidden");
  }

  show(view, detailId = null) {
    if (view !== "detail" || detailId !== this.detailId) this.detailMsg = "";
    this.view = view;
    this.detailId = detailId;
    this.render();
  }

  async load() {
    try {
      const res = await fetch(API, { credentials: "same-origin" });
      if (res.status === 401 || res.status === 403) {
        this.loadError = "Only an admin can manage connectors.";
      } else if (!res.ok) {
        this.loadError = `Couldn't load connectors (HTTP ${res.status}).`;
      } else {
        this.servers = await res.json();
        this.loadError = "";
      }
    } catch (e) {
      this.loadError = `Couldn't reach Odysseus: ${e.message || e}`;
    }
    if (this.view !== "add") this.render();
  }

  meta(s) {
    const m = SERVER_META[s.id] || {};
    const cat = s.is_builtin ? null : CATALOG.find(c => this.isCatalogServer(c, s));
    const isRemote = s.transport === "http" || s.transport === "sse";
    return {
      label: m.label || String(s.name || s.id).replace(/^Built-in:\s*/, ""),
      group: m.group || (isRemote ? "service" : "local"),
      desc: m.desc || (cat && cat.desc) || (isRemote ? s.url : [s.command, ...(s.args || [])].filter(Boolean).join(" ")),
      env: m.env || [],
      icon: (m.icon && ICONS[m.icon]) || "",
    };
  }

  iconHtml(label, icon) {
    if (icon) return `<span class="connector-icon">${icon}</span>`;
    return `<span class="connector-icon connector-icon-letter">${esc((label || "?").charAt(0).toUpperCase())}</span>`;
  }

  matches(...fields) {
    return !this.query || fields.some(f => String(f || "").toLowerCase().includes(this.query));
  }

  render() {
    if (!this.modal) return;
    this.modal.querySelectorAll("[data-connectors-tab]").forEach(b => {
      b.classList.toggle("active", b.dataset.connectorsTab === (this.view === "discover" ? "discover" : "installed"));
    });
    const views = { installed: "#connectors-installed-view", discover: "#connectors-discover-view", add: "#connectors-add-view", detail: "#connectors-detail-view" };
    for (const [name, sel] of Object.entries(views)) {
      this.modal.querySelector(sel)?.classList.toggle("hidden", name !== this.view);
    }
    if (this.view === "installed") this.renderInstalled();
    else if (this.view === "discover") this.renderDiscover();
    else if (this.view === "add") this.renderAdd();
    else if (this.view === "detail") this.renderDetail();
  }

  renderInstalled() {
    const el = this.modal.querySelector("#connectors-installed-view");
    if (this.loadError) {
      el.innerHTML = `<div class="connectors-empty">${esc(this.loadError)}</div>`;
      return;
    }
    if (!this.servers.length) {
      el.innerHTML = `<div class="connectors-empty">Loading connectors…</div>`;
      return;
    }
    const rows = this.servers
      .map(s => ({ s, m: this.meta(s) }))
      .filter(({ s, m }) => this.matches(m.label, m.desc, s.name, s.id))
      .sort((a, b) => a.m.label.localeCompare(b.m.label));
    const groups = [
      { key: "service", title: "Services" },
      { key: "local", title: "On this Mac" },
    ];
    const html = groups.map(g => {
      const items = rows.filter(r => r.m.group === g.key);
      if (!items.length) return "";
      return `<section class="connectors-group" data-group="${g.key}">
        <div class="connectors-group-title">${g.title}<span>${items.length}</span></div>
        ${items.map(({ s, m }) => {
          const st = statusOf(s);
          return `<button type="button" class="connector-row" data-server-id="${esc(s.id)}">
            ${this.iconHtml(m.label, m.icon)}
            <span class="connector-text">
              <span class="connector-name">${esc(m.label)}${s.is_builtin ? "" : ' <span class="connector-tag">Added</span>'}</span>
              <span class="connector-desc">${esc(m.desc)}</span>
            </span>
            <span class="connector-tools">${s.tool_count ? `${s.tool_count} tool${s.tool_count === 1 ? "" : "s"}` : ""}</span>
            <span class="connector-status ${st.cls}"><i></i>${st.text}</span>
          </button>`;
        }).join("")}
      </section>`;
    }).join("");
    el.innerHTML = html || `<div class="connectors-empty">No connectors match “${esc(this.query)}”.</div>`;
    el.querySelectorAll("[data-server-id]").forEach(row => {
      row.addEventListener("click", () => this.show("detail", row.dataset.serverId));
    });
    if (this.focusGroup) {
      el.querySelector(`[data-group="${this.focusGroup}"]`)?.scrollIntoView({ block: "start" });
      this.focusGroup = null;
    }
  }

  async renderDetail() {
    const el = this.modal.querySelector("#connectors-detail-view");
    const s = this.servers.find(x => x.id === this.detailId);
    if (!s) { this.show("installed"); return; }
    const m = this.meta(s);
    const st = statusOf(s);
    const where = s.transport === "http" || s.transport === "sse"
      ? s.url
      : [s.command, ...(s.args || [])].filter(Boolean).join(" ");
    el.innerHTML = `
      <button type="button" class="connectors-back">← All connectors</button>
      <div class="connector-detail-head">
        ${this.iconHtml(m.label, m.icon)}
        <div>
          <div class="connector-detail-name">${esc(m.label)}</div>
          <span class="connector-status ${st.cls}"><i></i>${st.text}${s.tool_count ? ` · ${s.tool_count} tools` : ""}</span>
        </div>
      </div>
      <p class="connector-detail-desc">${esc(m.desc)}</p>
      ${s.error ? `<div class="connectors-alert err">${esc(s.error)}</div>` : ""}
      ${this.signInHtml(s)}
      ${m.env.length ? `<div class="connector-detail-section"><div class="connector-detail-label">Settings</div><p class="connector-detail-note">Reads ${m.env.map(v => `<code>${esc(v)}</code>`).join(", ")} from <code>.env</code>. Restart Odysseus after changing it.</p></div>` : ""}
      ${s.is_builtin ? "" : `<div class="connector-detail-section"><div class="connector-detail-label">Runs</div><code class="connector-detail-cmd">${esc(where)}</code></div>`}
      ${s.is_builtin ? "" : `<div class="connector-detail-actions">
        <button type="button" class="connectors-btn" data-act="reconnect">Reconnect</button>
        <button type="button" class="connectors-btn" data-act="toggle">${s.is_enabled ? "Disable" : "Enable"}</button>
        <button type="button" class="connectors-btn danger" data-act="remove">Remove</button>
        <span class="connector-detail-msg">${esc(this.detailMsg)}</span>
      </div>`}
      <div class="connector-detail-section">
        <div class="connector-detail-label">Tools</div>
        <div class="connector-tools-list"><div class="connectors-empty">Loading tools…</div></div>
      </div>`;
    el.querySelector(".connectors-back").addEventListener("click", () => this.show("installed"));
    el.querySelector("[data-finish-signin]")?.addEventListener("click", () => this.finishSignIn(s, el));
    el.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => this.act(s, b.dataset.act)));
    this.body.scrollTop = 0;

    const list = el.querySelector(".connector-tools-list");
    try {
      const res = await fetch(`${API}/${encodeURIComponent(s.id)}/tools`, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const tools = await res.json();
      if (this.view !== "detail" || this.detailId !== s.id) return;
      if (!tools.length) {
        list.innerHTML = `<div class="connectors-empty">${s.status === "connected" ? "This server reports no tools." : "Tools appear once the server connects."}</div>`;
        return;
      }
      // Odysseus can switch individual tools off only for servers you added.
      const editable = !s.is_builtin;
      list.innerHTML = tools.map(t => `
        <label class="connector-tool${editable ? "" : " readonly"}">
          ${editable ? `<input type="checkbox" data-tool="${esc(t.name)}" ${t.is_disabled ? "" : "checked"}>` : ""}
          <span><strong>${esc(t.name)}</strong><span>${esc(t.description || "")}</span></span>
        </label>`).join("");
      if (editable) {
        list.querySelectorAll("input[data-tool]").forEach(cb => cb.addEventListener("change", async () => {
          const disabled = [...list.querySelectorAll("input[data-tool]")].filter(x => !x.checked).map(x => x.dataset.tool);
          await fetch(`${API}/${encodeURIComponent(s.id)}/tools`, {
            method: "PATCH", credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ disabled }),
          });
        }));
      }
    } catch (e) {
      list.innerHTML = `<div class="connectors-empty">Couldn't load tools: ${esc(e.message || e)}</div>`;
    }
  }

  signInHtml(s) {
    const href = s.auth_url || (s.needs_oauth && s.has_oauth ? `/api/mcp/oauth/authorize/${encodeURIComponent(s.id)}` : "");
    if (!href) return "";
    // The sign-in page opens in your browser, which can't hand the result
    // back to the app on its own, so the final address is pasted here.
    return `<div class="connector-detail-section">
      <div class="connector-detail-label">Sign in</div>
      <p class="connector-detail-note">1. <a href="${esc(href)}" target="_blank" rel="noopener">Open the sign-in page</a> and approve access. 2. Copy the address your browser ends up on and paste it here.</p>
      <div class="connector-signin-row">
        <input type="text" class="connectors-input" data-signin-url placeholder="http://127.0.0.1:…/api/mcp/oauth/callback?code=…" autocomplete="off">
        <button type="button" class="connectors-btn primary" data-finish-signin>Finish</button>
      </div>
    </div>`;
  }

  async finishSignIn(s, el) {
    const url = (el.querySelector("[data-signin-url]")?.value || "").trim();
    const say = (t) => {
      this.detailMsg = t;
      const m = el.querySelector(".connector-detail-msg");
      if (m) m.textContent = t; else window.uiModule?.showToast?.(t);
    };
    if (!url.includes("code=")) { say("Paste the full address that contains code=…"); return; }
    const fd = new FormData();
    fd.append("callback_url", url);
    try {
      const res = await fetch(`/api/mcp/oauth/exchange/${encodeURIComponent(s.id)}`, { method: "POST", body: fd, credentials: "same-origin" });
      say(res.ok ? "Signed in. Connecting…" : `Sign-in failed (HTTP ${res.status}).`);
    } catch (e) {
      say(`Sign-in failed: ${e.message || e}`);
    }
    setTimeout(() => this.load(), 2500);
  }

  async act(s, action) {
    // Kept on the instance because reloading status re-renders this view.
    const say = (t) => {
      this.detailMsg = t;
      const m = this.modal.querySelector("#connectors-detail-view .connector-detail-msg");
      if (m) m.textContent = t;
    };
    try {
      if (action === "reconnect") {
        say("Reconnecting…");
        const res = await fetch(`${API}/${encodeURIComponent(s.id)}/reconnect`, { method: "POST", credentials: "same-origin" });
        const d = await res.json().catch(() => ({}));
        say(d.connected ? `Connected (${d.tool_count || 0} tools)` : `Failed: ${d.error || d.detail || res.status}`);
      } else if (action === "toggle") {
        const fd = new FormData();
        fd.append("is_enabled", String(!s.is_enabled));
        say(s.is_enabled ? "Disabling…" : "Enabling…");
        await fetch(`${API}/${encodeURIComponent(s.id)}`, { method: "PATCH", body: fd, credentials: "same-origin" });
      } else if (action === "remove") {
        const ok = await (window.styledConfirm
          ? window.styledConfirm(`Remove “${this.meta(s).label}”? Its tools will no longer be available.`, { title: "Remove connector", confirmText: "Remove", danger: true })
          : Promise.resolve(window.confirm(`Remove ${this.meta(s).label}?`)));
        if (!ok) return;
        await fetch(`${API}/${encodeURIComponent(s.id)}`, { method: "DELETE", credentials: "same-origin" });
        await this.load();
        this.show("installed");
        return;
      }
    } catch (e) {
      say(`Failed: ${e.message || e}`);
    }
    await this.load();
  }

  // The package (npx/uvx) or image (docker) that identifies a catalog entry.
  catalogPackage(entry) {
    const names = (entry.args || []).filter(a => !a.startsWith("-") && !a.includes("{"));
    return entry.command === "docker" ? names[names.length - 1] : names[0];
  }

  isCatalogServer(entry, s) {
    return entry.url
      ? s.url === entry.url
      : s.command === entry.command && (s.args || []).includes(this.catalogPackage(entry));
  }

  installedFor(entry) {
    return this.servers.find(s => this.isCatalogServer(entry, s));
  }

  renderDiscover() {
    const el = this.modal.querySelector("#connectors-discover-view");
    const card = (c) => {
      const have = this.installedFor(c);
      const tag = c.url ? (c.checked ? "Remote" : "Remote · sign-in") : "Local";
      const inputs = have ? [] : (c.inputs || []);
      return `<div class="discover-card" data-catalog-id="${c.id}">
        ${this.iconHtml(c.name, "")}
        <div class="connector-text">
          <span class="connector-name">${esc(c.name)} <span class="connector-tag">${tag}</span></span>
          <span class="connector-desc">${esc(c.desc)}</span>
          ${c.note && !have ? `<span class="discover-note">${esc(c.note)}</span>` : ""}
          ${inputs.map(i => `<input type="${i.secret ? "password" : "text"}" class="connectors-input" data-catalog-input="${esc(i.key)}" placeholder="${esc(i.label)}${i.placeholder ? ` — ${esc(i.placeholder)}` : ""}" aria-label="${esc(i.label)}" autocomplete="off">`).join("")}
          <span class="discover-msg">${esc(this.discoverMsgs[c.id] || "")}</span>
        </div>
        ${have
          ? `<button type="button" class="connectors-btn" data-open="${esc(have.id)}">Added</button>`
          : `<button type="button" class="connectors-btn primary" data-add="${c.id}">Add</button>`}
      </div>`;
    };
    const sections = CATALOG_GROUPS.map(g => {
      const items = CATALOG.filter(c => c.group === g.key && this.matches(c.name, c.desc));
      if (!items.length) return "";
      return `<section class="connectors-group"><div class="connectors-group-title">${esc(g.title)}</div>${items.map(card).join("")}</section>`;
    }).join("");
    el.innerHTML = `
      <p class="connectors-intro">MCP servers you can add with one click. Remote ones run on the provider's side; local ones are downloaded with ${"<code>npx</code>"}, ${"<code>uvx</code>"} or Docker the first time they start. Tokens you enter are stored with the server in Odysseus.</p>
      ${sections || `<div class="connectors-empty">Nothing matches “${esc(this.query)}”.</div>`}`;
    el.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => this.show("detail", b.dataset.open)));
    el.querySelectorAll("[data-add]").forEach(b => b.addEventListener("click", () => this.addFromCatalog(b.dataset.add, b.closest(".discover-card"))));
  }

  async addFromCatalog(id, card) {
    const entry = CATALOG.find(c => c.id === id);
    if (!entry) return;
    const msg = card.querySelector(".discover-msg");
    const env = { ...(entry.env || {}) };
    let args = [...(entry.args || [])];
    for (const input of entry.inputs || []) {
      const value = (card.querySelector(`[data-catalog-input="${input.key}"]`)?.value || "").trim();
      if (!value) {
        if (input.optional) continue;
        msg.textContent = `Enter the ${input.label.toLowerCase()}.`;
        return;
      }
      if (input.arg) {
        if (!value.startsWith("/")) { msg.textContent = `Enter the full path of the ${input.label.toLowerCase()}.`; return; }
        args = args.map(a => a === `{${input.key}}` ? value : a);
      } else {
        env[input.key] = value;
      }
    }
    await this.submitServer({ name: entry.name, transport: entry.transport, command: entry.command, args, env, url: entry.url }, card.querySelector("[data-add]"), msg, entry.id);
  }

  renderAdd() {
    const el = this.modal.querySelector("#connectors-add-view");
    el.innerHTML = `
      <button type="button" class="connectors-back">← All connectors</button>
      <div class="connector-form">
        <label>Name<input type="text" class="connectors-input" id="cx-name" placeholder="My server"></label>
        <label>Type
          <select class="connectors-input" id="cx-transport">
            <option value="stdio">Local command (stdio)</option>
            <option value="http">Remote URL (streamable HTTP)</option>
            <option value="sse">Remote URL (SSE)</option>
          </select>
        </label>
        <div id="cx-stdio">
          <label>Command<input type="text" class="connectors-input" id="cx-command" placeholder="npx"></label>
          <label>Arguments <small>one per line</small><textarea class="connectors-input" id="cx-args" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/Users/you/Documents"></textarea></label>
          <label>Environment <small>KEY=value, one per line</small><textarea class="connectors-input" id="cx-env" rows="2" placeholder="API_TOKEN=..."></textarea></label>
        </div>
        <div id="cx-remote" class="hidden">
          <label>URL<input type="url" class="connectors-input" id="cx-url" placeholder="https://example.com/mcp"></label>
        </div>
        <div class="connector-detail-actions">
          <button type="button" class="connectors-btn primary" id="cx-save">Add server</button>
          <span class="connector-detail-msg" id="cx-msg"></span>
        </div>
      </div>`;
    const $ = (id) => el.querySelector(`#${id}`);
    el.querySelector(".connectors-back").addEventListener("click", () => this.show("installed"));
    $("cx-transport").addEventListener("change", () => {
      const remote = $("cx-transport").value !== "stdio";
      $("cx-stdio").classList.toggle("hidden", remote);
      $("cx-remote").classList.toggle("hidden", !remote);
    });
    $("cx-save").addEventListener("click", () => {
      const transport = $("cx-transport").value;
      const lines = (v) => v.split("\n").map(x => x.trim()).filter(Boolean);
      const env = {};
      for (const line of lines($("cx-env").value)) {
        const i = line.indexOf("=");
        if (i > 0) env[line.slice(0, i).trim()] = line.slice(i + 1).trim();
      }
      const spec = { name: $("cx-name").value.trim(), transport };
      if (transport === "stdio") Object.assign(spec, { command: $("cx-command").value.trim(), args: lines($("cx-args").value), env });
      else spec.url = $("cx-url").value.trim();
      if (!spec.name) { $("cx-msg").textContent = "Give it a name."; return; }
      if (transport === "stdio" ? !spec.command : !spec.url) { $("cx-msg").textContent = transport === "stdio" ? "Enter a command." : "Enter a URL."; return; }
      this.submitServer(spec, $("cx-save"), $("cx-msg"));
    });
    $("cx-name").focus();
  }

  async submitServer(spec, button, msg, catalogId = null) {
    const say = (t) => {
      if (catalogId) this.discoverMsgs[catalogId] = t;
      msg.textContent = t;
    };
    const fd = new FormData();
    fd.append("name", spec.name);
    fd.append("transport", spec.transport);
    if (spec.transport === "stdio") {
      fd.append("command", spec.command);
      fd.append("args", JSON.stringify(spec.args || []));
      fd.append("env", JSON.stringify(spec.env || {}));
    } else {
      fd.append("url", spec.url);
    }
    const label = button ? button.textContent : "";
    if (button) { button.disabled = true; button.textContent = "Adding…"; }
    say(spec.transport === "stdio" ? "Starting it — the first run may download the package." : "Connecting…");
    try {
      const res = await fetch(API, { method: "POST", body: fd, credentials: "same-origin" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        say(`Failed: ${d.detail || d.error || `HTTP ${res.status}`}`);
      } else if (d.connected || d.status === "connected") {
        say(`Connected — ${d.tool_count || 0} tools.`);
      } else if (d.needs_auth || d.needs_oauth) {
        say("Added. It needs you to sign in: open it from Installed to finish.");
        if (d.auth_url) window.open(d.auth_url, "_blank", "noopener");
      } else {
        say(`Added, but it didn't connect: ${d.error || d.status || "unknown error"}. Open it from Installed to retry or remove it.`);
      }
      await this.load();
    } catch (e) {
      say(`Failed: ${e.message || e}`);
    } finally {
      if (button && button.isConnected) { button.disabled = false; button.textContent = label; }
    }
  }
}

export const connectorsManager = new ConnectorsManager();
// app.js looks the module up under this name to close it with other windows.
window.connectorsManager = connectorsManager;
window.connectorsModule = connectorsManager;
