"""scripts/register_rapid_mlx.py on a throwaway database: what it writes, that it is safe to repeat, and that it waits for the app."""

import importlib.util
import json
import socket
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import McpServer, ModelEndpoint

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "register_rapid_mlx.py"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("register_rapid_mlx", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    ModelEndpoint.__table__.create(engine)
    McpServer.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_it_adds_the_endpoint_with_tool_calls_on_and_the_model_listed(script, db):
    done = script.register(db, "qwen3.6-35b-4bit", 8081, research=False, ldr_command="/x/ldr-mcp")

    row = db.query(ModelEndpoint).one()
    assert done == ["added model endpoint http://127.0.0.1:8081/v1 with model 'qwen3.6-35b-4bit'"]
    assert row.base_url == "http://127.0.0.1:8081/v1" and row.is_enabled and row.model_type == "llm"
    assert row.supports_tools is True and row.endpoint_kind == "local"
    assert json.loads(row.cached_models) == ["qwen3.6-35b-4bit"] == json.loads(row.pinned_models)
    assert db.query(McpServer).count() == 0


def test_the_research_connector_uses_the_same_engine_and_model(script, db):
    script.register(db, "qwen3.6-35b-4bit", 8081, research=True, ldr_command="/x/ldr-mcp")

    server = db.query(McpServer).one()
    env = json.loads(server.env)
    assert server.name == "Local Deep Research" and server.transport == "stdio" and server.command == "/x/ldr-mcp"
    assert server.args == "[]" and server.is_enabled
    assert env["LDR_LLM_OPENAI_ENDPOINT_URL"] == "http://127.0.0.1:8081/v1" and env["LDR_LLM_MODEL"] == "qwen3.6-35b-4bit"
    assert env["DO_NOT_TRACK"] == "1"


def test_running_it_twice_updates_instead_of_duplicating(script, db):
    script.register(db, "old-model", 8081, research=True, ldr_command="/x/ldr-mcp")
    done = script.register(db, "qwen3.6-35b-4bit", 8081, research=True, ldr_command="/y/ldr-mcp")

    assert db.query(ModelEndpoint).count() == 1 and db.query(McpServer).count() == 1
    assert done[0].startswith("updated model endpoint") and done[1].startswith("updated connector")
    assert json.loads(db.query(ModelEndpoint).one().cached_models) == ["qwen3.6-35b-4bit"]
    assert db.query(McpServer).one().command == "/y/ldr-mcp"
    assert json.loads(db.query(McpServer).one().env)["LDR_LLM_MODEL"] == "qwen3.6-35b-4bit"


def test_other_endpoints_are_left_alone(script, db):
    db.add(ModelEndpoint(id="keep", name="Local Model Server", base_url="http://127.0.0.1:12434/v1", pinned_models='["a"]'))
    db.commit()

    script.register(db, "m", 8081, research=False, ldr_command="/x")

    kept = db.query(ModelEndpoint).filter(ModelEndpoint.id == "keep").one()
    assert kept.name == "Local Model Server" and kept.pinned_models == '["a"]' and kept.supports_tools is None
    assert db.query(ModelEndpoint).count() == 2


def test_it_detects_a_running_app():
    from importlib import util
    spec = util.spec_from_file_location("register_rapid_mlx2", _SCRIPT)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert module.app_is_running(port) is True
    finally:
        listener.close()
    assert module.app_is_running(port) is False  # nothing listens once it is closed


def test_the_default_run_changes_nothing(script, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["register_rapid_mlx.py", "--model", "m", "--research"])
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "Local Deep Research" in out
