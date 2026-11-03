import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _eval(body: str):
    source = f"import * as page from './static/js/projectsPage.js';\n{body}"
    out = subprocess.run(["node", "--input-type=module", "-e", source], cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


def test_projects_are_grouped_counted_and_sorted_by_latest_activity():
    got = _eval("""
      const sessions = [
        {id: 'a', folder: 'Hardware', updated_at: '2026-11-01T10:00:00'},
        {id: 'b', folder: 'Hardware', updated_at: '2026-11-03T09:00:00'},
        {id: 'c', folder: 'Research', updated_at: '2026-11-02T09:00:00'},
        {id: 'd', folder: null, updated_at: '2026-11-03T12:00:00'},
        {id: 'e', folder: 'Research', archived: true, updated_at: '2026-11-04T12:00:00'},
        {id: 'f', folder: 'Assistant', updated_at: '2026-11-04T12:00:00'},
      ];
      console.log(JSON.stringify(page.summarizeProjects(sessions, ['Website', 'Tasks', ''])));
    """)
    assert [p["name"] for p in got] == ["Hardware", "Research", "Website"]
    assert [p["count"] for p in got] == [2, 1, 0]            # archived, loose and Assistant chats don't count
    assert got[0]["latestId"] == "b" and got[2]["latestId"] is None  # empty folders still listed


def test_ties_and_bad_input_are_handled():
    got = _eval("""
      console.log(JSON.stringify([
        page.summarizeProjects(null, ['b', 'a']).map(p => p.name),
        page.summarizeProjects(undefined).length,
        page.filterProjects([{name: 'Hardware Scoping'}, {name: 'Research'}], ' SCOP ').map(p => p.name),
        page.filterProjects([{name: 'X'}], '').length,
      ]));
    """)
    assert got == [["a", "b"], 0, ["Hardware Scoping"], 1]


def test_times_are_relative_and_server_utc_timestamps_are_read_as_utc():
    got = _eval("""
      const now = Date.parse('2026-11-03T12:00:00Z');
      console.log(JSON.stringify([
        page.relativeTime('2026-11-03T11:59:40Z', now),
        page.relativeTime('2026-11-03T11:25:00Z', now),
        page.relativeTime('2026-11-03T09:00:00Z', now),
        page.relativeTime('2026-11-02T09:00:00Z', now),
        page.relativeTime('2026-10-30T09:00:00Z', now),
        page.relativeTime('2026-11-03T11:55:00', now),   // no zone: the server's UTC, not local time
        page.relativeTime('', now),
        page.relativeTime('garbage', now),
      ]));
    """)
    assert got == ["just now", "35 min ago", "3 h ago", "yesterday", "4 d ago", "5 min ago", "", ""]
