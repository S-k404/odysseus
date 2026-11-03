import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(sessions, fetch_started_at, pick, switch_pending=False):
    source = f"""
    import {{ keepRecentModelPick }} from './static/js/modelPickReconcile.js';
    const out = keepRecentModelPick({json.dumps(sessions)}, {fetch_started_at}, {json.dumps(pick)}, {json.dumps(switch_pending)});
    console.log(JSON.stringify(out));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


STALE = [{"id": "a", "model": "ai/big-chat:2"}, {"id": "b", "model": "ai/other:1"}]
PICK = {"model": "ai/small-chat:1", "endpoint_url": "http://x/v1", "endpoint_id": "e1",
        "session_id": "a", "persisted": True, "done_at": 1000}


def test_response_requested_before_the_patch_finished_keeps_the_pick():
    out = _run(STALE, 900, PICK)
    assert out[0]["model"] == "ai/small-chat:1"
    assert out[0]["endpoint_url"] == "http://x/v1"
    assert out[1]["model"] == "ai/other:1"  # other chats are untouched


def test_response_requested_while_the_patch_is_in_flight_keeps_the_pick():
    pick = {**PICK, "persisted": False, "done_at": None}
    assert _run(STALE, 5000, pick, switch_pending=True)[0]["model"] == "ai/small-chat:1"


def test_response_requested_after_the_patch_is_trusted():
    # Requested after the PATCH finished: the server's answer is the truth, even
    # if it differs (e.g. the model was changed from another window since).
    assert _run(STALE, 1001, PICK)[0]["model"] == "ai/big-chat:2"


def test_no_pick_or_unknown_session_changes_nothing():
    assert _run(STALE, 900, None) == STALE
    assert _run(STALE, 900, {**PICK, "session_id": "gone"}) == STALE
    assert _run(STALE, 900, {**PICK, "session_id": ""}) == STALE
    assert _run("not a list", 900, PICK) == "not a list"
