# Odysseus Antigravity Integration

This directory contains the skill bundle that lets Antigravity (Gemini) agents use
Odysseus. It follows Antigravity's own customization layout: a skill is
`skills/<name>/SKILL.md`, and the machine-wide root is `~/.gemini/config/`.

## User Flow

1. Open Odysseus Settings > Integrations.
2. Add an Antigravity Agent.
3. Copy the full setup commands shown after the generated token.
4. Toggle the tools the agent is allowed to use.
5. Run the setup commands in a terminal:

```bash
export ODYSSEUS_URL=http://your-odysseus-host:7000
export ODYSSEUS_API_TOKEN=ody_generated_token
mkdir -p ~/.gemini/config
curl -fsSL -H "Authorization: Bearer $ODYSSEUS_API_TOKEN" "$ODYSSEUS_URL/api/antigravity/plugin.zip" -o /tmp/odysseus-antigravity-skill.zip
python3 -m zipfile -e /tmp/odysseus-antigravity-skill.zip ~/.gemini/config/
```

Antigravity discovers skills under `~/.gemini/config/skills/` and shows only each
skill's name and description until the agent decides to use it. The agent needs
`ODYSSEUS_URL` and `ODYSSEUS_API_TOKEN` in its environment.

## What's in the bundle

- `skills/odysseus/SKILL.md` — the skill definition (name and description
  frontmatter, then the instructions).
- `skills/odysseus/scripts/odysseus_api.py` — small helper that calls the scoped
  `/api/codex/*` endpoints (the canonical scope-gated agent API shared by every
  agent integration; the `codex` path is historic).

## Scope enforcement

The token is scope-gated. Every tool surface is checked server-side in Odysseus,
so an agent that calls a forbidden endpoint gets `403` until the matching toggle
is enabled in Settings > Integrations > Antigravity Agent.
