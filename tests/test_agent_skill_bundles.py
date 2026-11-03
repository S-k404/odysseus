"""Skill bundles served to external agents (Claude Code, Antigravity)."""

import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import codex_routes

ROOT = Path(__file__).resolve().parent.parent
BUNDLES = {
    "claude": ("/api/claude/plugin.zip", codex_routes.setup_claude_routes),
    "antigravity": ("/api/antigravity/plugin.zip", codex_routes.setup_antigravity_routes),
}


def _client(monkeypatch, setup):
    monkeypatch.setattr(codex_routes, "require_authenticated_request", lambda request: "alice")
    app = FastAPI()
    app.include_router(setup())
    return TestClient(app)


@pytest.mark.parametrize("agent", BUNDLES)
def test_plugin_zip_ships_only_the_skills_tree(monkeypatch, agent):
    path, setup = BUNDLES[agent]
    resp = _client(monkeypatch, setup).get(path)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert f"odysseus-{agent}-skill.zip" in resp.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert "skills/odysseus/SKILL.md" in names
    assert "skills/odysseus/scripts/odysseus_api.py" in names
    assert all(n.startswith("skills/") for n in names), names  # no README at the config root


def test_antigravity_skill_has_the_frontmatter_antigravity_requires():
    text = (ROOT / "integrations/antigravity/skills/odysseus/SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)

    assert front, "SKILL.md must start with a YAML frontmatter block"
    assert re.search(r"^name: odysseus$", front.group(1), re.M)
    assert re.search(r"^description: \S", front.group(1), re.M)
    assert "~/.gemini/config/skills/odysseus/scripts/odysseus_api.py" in text
    assert "~/.claude" not in text


def test_settings_install_command_matches_the_bundle_layout():
    js = (ROOT / "static/js/settings.js").read_text(encoding="utf-8")
    block = js[js.index("  antigravity: {\n    label: 'Antigravity Agent'"):]
    block = block[: block.index("\n  },\n};")]

    assert "namePrefix: 'antigravity agent'" in block
    assert "pluginPath: '/api/antigravity/plugin.zip'" in block
    # The zip extracts into ~/.gemini/config/, so the helper lands at skills/odysseus/scripts/.
    assert "-e /tmp/odysseus-antigravity-skill.zip ~/.gemini/config/" in block
    assert "~/.gemini/config/skills/odysseus/scripts/odysseus_api.py capabilities" in block


def test_extracted_helper_runs_from_the_antigravity_config_dir(monkeypatch, tmp_path):
    resp = _client(monkeypatch, codex_routes.setup_antigravity_routes).get("/api/antigravity/plugin.zip")
    config_dir = tmp_path / ".gemini" / "config"
    zipfile.ZipFile(io.BytesIO(resp.content)).extractall(config_dir)

    helper = config_dir / "skills" / "odysseus" / "scripts" / "odysseus_api.py"
    proc = subprocess.run(
        [sys.executable, "-I", str(helper), "capabilities"],
        env={"PATH": ""},  # no ODYSSEUS_URL / ODYSSEUS_API_TOKEN
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "ODYSSEUS_URL" in proc.stderr and "Antigravity Agent" in proc.stderr
