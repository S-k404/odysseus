"""tests/test_decensor_chat_flow.py

Verify chat-to-agent intent escalation, domain selection, and output promotion
for decensoring / uncensoring image requests.
"""
import os
import tempfile
from pathlib import Path
from src.action_intents import classify_tool_intent
from src.agent_loop import _DOMAIN_TOOL_MAP, _classify_agent_request
from src.tool_execution import _promote_decensor_fields


def test_decensor_intent_classification():
    queries = [
        "decensor it",
        "decensor this",
        "can you decensor this image",
        "please uncensor it",
        "remove the mosaic from this picture",
        "remove censor bars",
        "unblur image",
    ]
    for q in queries:
        intent = classify_tool_intent(q)
        assert intent.needs_tools is True, f"Expected needs_tools for {q!r}"
        assert intent.category == "decensor", f"Expected category 'decensor' for {q!r}"

    # Non-action questions should not trigger tool intent
    assert classify_tool_intent("what is a decensor").needs_tools is False


def test_decensor_domain_and_tool_mapping():
    assert "decensor" in _DOMAIN_TOOL_MAP
    tools = _DOMAIN_TOOL_MAP["decensor"]
    assert "mcp__uncensor__decensor_image" in tools
    assert "mcp__uncensor__uncensor_image" in tools
    assert "mcp__uncensor__find_censored_regions" in tools

    req = _classify_agent_request([{"role": "user", "content": "decensor it"}], "decensor it")
    assert "decensor" in req["domains"]
    assert req["low_signal"] is False


def test_promote_decensor_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "sample_uncensored.png"
        out_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-decensored-bytes")

        res = {
            "exit_code": 0,
            "stdout": f"Filled in 1 region(s):\nsaved: {out_file}\ntime: 0.3 s",
        }
        _promote_decensor_fields(res)

        assert res.get("image_path") == str(out_file)
        assert res.get("image_url") is not None
        assert res["image_url"].startswith("/api/generated-image/")
        assert res.get("image_model") == "Er0manga FFC"


def test_promote_decensor_preview_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "sample_preview.png"
        out_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-preview-bytes")

        res = {
            "exit_code": 0,
            "stdout": f"1. mosaic at x=100 y=90 size 192x120\npreview: {out_file}",
        }
        _promote_decensor_fields(res)

        assert res.get("image_path") == str(out_file)
        assert res.get("image_url") is not None
        assert res["image_url"].startswith("/api/generated-image/")
        assert res.get("image_prompt") == "Decensored preview"


def test_decensor_domain_rules_and_prompt_assembly():
    from src.agent_loop import _domain_rules_for_tools, _assemble_prompt, _DOMAIN_RULES
    assert "decensor" in _DOMAIN_RULES
    rules = _domain_rules_for_tools({"mcp__uncensor__decensor_image"})
    assert any("Decensor / Uncensor rules" in r for r in rules)

    prompt = _assemble_prompt({"mcp__uncensor__decensor_image", "read_file"}, set())
    assert "Decensor / Uncensor rules" in prompt


def test_ensure_ram_for_decensor_tool(monkeypatch):
    import asyncio
    from src import ram_optimizer as ro

    monkeypatch.setattr(ro, "runner_urls", lambda: [])
    freed = []

    async def free(urls, keep=""):
        freed.append(keep)
        return {"steps": ["unloaded chat-model"]}

    # When RAM is plenty (40 GB), no free needed
    res = asyncio.run(ro.ensure_ram_for_tool(
        "mcp__uncensor__decensor_image",
        snapshot=lambda: {"total_gb": 48.0, "used_gb": 8.0, "available_gb": 40.0},
        free=free,
    ))
    assert res is None and freed == []

    # When RAM is tight (2 GB available), 8 GB decensor tool needs to free local models
    res = asyncio.run(ro.ensure_ram_for_tool(
        "mcp__uncensor__decensor_image",
        snapshot=lambda: {"total_gb": 48.0, "used_gb": 46.0, "available_gb": 2.0},
        free=free,
    ))
    assert res == ["unloaded chat-model"] and freed == [""]


def test_decensor_skips_vl_analysis_and_strips_image_urls(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.chat_handler import ChatHandler

    vl_called = []

    def fake_vl(path, owner=None):
        vl_called.append(path)
        return {"text": "explicit pornographic description", "model": "mock-vl"}

    monkeypatch.setattr("src.chat_handler.analyze_image_with_vl_result", fake_vl)

    upload_handler = MagicMock()
    upload_handler.is_image_file.return_value = True
    upload_handler.resolve_upload.return_value = {
        "id": "att1",
        "name": "sample.jpeg",
        "path": "/fake/sample.jpeg",
        "mime": "image/jpeg",
    }
    upload_handler.inside_base_dir.return_value = True

    handler = ChatHandler(None, None, None, None, None, upload_handler)
    sess = MagicMock()
    sess.model = "qwen3.6-35b"
    sess.endpoint_url = "http://127.0.0.1:12434/v1"

    enhanced, user_content, text_for_ctx, _, att_meta = asyncio.run(
        handler.preprocess_message("decensor this image", ["att1"], sess)
    )

    # VL analysis must NOT be invoked
    assert vl_called == []
    # Explicit caption must NOT be injected
    assert "explicit pornographic description" not in enhanced
    assert "[Image attached: sample.jpeg]" in enhanced
    # user_content must be clean text (image_url stripped)
    assert isinstance(user_content, str)
    assert "image_url" not in user_content


