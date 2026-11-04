"""static/js/localModels.js under Node: the toast for "Optimise memory" matches what the server did."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = Path(__file__).resolve().parent.parent / "static" / "js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

_DRIVER = r"""
globalThis.window = { location: { origin: 'http://odysseus.test' } };
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
const { optimiseSummary } = await import('./localModels.mjs');
const reports = JSON.parse(process.argv[2]);
console.log(JSON.stringify(reports.map(optimiseSummary)));
"""

_REPORTS = {
    "freed": {"steps": ["unloaded qwen3-8b"], "freed_gb": 9.4, "available_gb": 31.2, "suggestions": []},
    # The runner had not handed its memory back yet when this was measured: still say what happened.
    "unloaded_but_unmeasured": {"steps": ["unloaded qwen3-8b", "unloaded decensor model"], "freed_gb": 0.0, "available_gb": 12.0, "suggestions": []},
    "nothing_loaded": {"steps": [], "freed_gb": 0.0, "available_gb": 12.4, "suggestions": [{"app": "Docker's virtual machine", "gb": 6.5}, {"app": "Zen", "gb": 2.9}, {"app": "claude", "gb": 2.4}]},
    "busy": {"steps": ["skipped model unload: a reply is generating"], "skipped": "busy", "freed_gb": None},
}


@pytest.fixture(scope="module")
def toasts(tmp_path_factory):
    work = tmp_path_factory.mktemp("optimise")
    (work / "localModels.mjs").write_text((_JS / "localModels.js").read_text(encoding="utf-8"), encoding="utf-8")
    (work / "driver.mjs").write_text(_DRIVER, encoding="utf-8")
    proc = subprocess.run(["node", "driver.mjs", json.dumps(list(_REPORTS.values()))], cwd=work, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return dict(zip(_REPORTS, json.loads(proc.stdout)))


def test_a_measured_gain_is_reported_in_gb(toasts):
    assert toasts["freed"] == "Freed 9.4 GB, 31 GB free."


def test_an_unload_is_never_reported_as_nothing_to_free(toasts):
    assert toasts["unloaded_but_unmeasured"].startswith("Unloaded 2 items, 12 GB free.")


def test_with_no_model_loaded_it_says_so_and_names_the_biggest_holders(toasts):
    assert toasts["nothing_loaded"] == (
        "No model was loaded, so nothing of Odysseus to free, 12 GB free. "
        "Biggest other apps: Docker's virtual machine 6.5 GB, Zen 2.9 GB."
    )


def test_a_busy_reply_is_explained(toasts):
    assert "reply is generating" in toasts["busy"]
