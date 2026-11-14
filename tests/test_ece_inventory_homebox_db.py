"""ECE inventory connector vs. Homebox's current (entity-based) SQLite schema.

Homebox stores locations as rows in ``entities`` (type ``is_location = 1``) next
to the items. The connector used to list every row as a component, so a fresh
Homebox reported "Living Room" and "Garage" as lab parts, always claimed the
location was "Homebox Storage", dropped tags and custom fields, and opened the
live DB read-write (which can delete the container's WAL/SHM files on close).

The tests build a throwaway DB with the same table layout; they never read the
real Homebox data.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

_SERVER = Path(__file__).resolve().parent.parent / "mcp_servers" / "ece_inventory_server.py"


@pytest.fixture
def ece():
    spec = importlib.util.spec_from_file_location("ece_inventory_server_under_test", _SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


_SCHEMA = """
CREATE TABLE entity_types (id text primary key, name text, is_location bool);
CREATE TABLE entities (
    id text primary key, name text, description text, notes text, quantity real,
    model_number text, manufacturer text, import_ref text, archived bool default 0,
    entity_type_entities text, entity_children text, entity_location_entities text);
CREATE TABLE tags (id text primary key, name text);
CREATE TABLE tag_entities (tag_id text, entity_id text);
CREATE TABLE entity_fields (
    id text primary key, name text, text_value text, number_value integer, entity_fields text);
"""


def _ent(conn, id, name, type_id, parent=None, qty=1, ref=None, archived=0, location=None):
    conn.execute(
        "INSERT INTO entities (id, name, quantity, import_ref, archived, entity_type_entities,"
        " entity_children, entity_location_entities) VALUES (?,?,?,?,?,?,?,?)",
        (id, name, qty, ref, archived, type_id, parent, location),
    )


@pytest.fixture
def homebox(tmp_path, ece, monkeypatch):
    """A Homebox dir with data/homebox.db: Lab > Cabinet A > Drawer 1 (+ Bench), 2 items."""
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "homebox.db")
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO entity_types VALUES ('L', 'Location', 1), ('I', 'Item', 0)")
    _ent(conn, "lab", "Electronics Lab", "L")
    _ent(conn, "cab", "Cabinet A", "L", parent="lab")
    _ent(conn, "dr1", "Drawer 1", "L", parent="cab")
    _ent(conn, "bench", "Bench", "L", parent="lab")
    _ent(conn, "r10k", "10k resistor", "I", parent="dr1", qty=7, ref="ECE-RES-10K")
    _ent(conn, "led", "Red LED", "I", parent="dr1", qty=3, ref="ECE-LED")
    _ent(conn, "old", "Retired part", "I", parent="dr1", qty=9, archived=1)
    conn.execute("INSERT INTO tags VALUES ('t1', 'Resistor'), ('t2', 'SMD')")
    conn.execute("INSERT INTO tag_entities VALUES ('t1', 'r10k'), ('t2', 'r10k')")
    conn.execute(
        "INSERT INTO entity_fields VALUES ('f1', 'Value', '10k Ohm', NULL, 'r10k'),"
        " ('f2', 'Package', '0805 SMD', NULL, 'r10k'), ('f3', 'Unrelated', 'x', NULL, 'r10k')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(ece, "HOMEBOX_DIR_CANDIDATES", [tmp_path])
    return tmp_path


def _by_name(components):
    return {c["name"]: c for c in components}


def test_locations_and_archived_rows_are_not_components(ece, homebox):
    names = {c["name"] for c in ece._load_all_components()}
    assert names == {"10k resistor", "Red LED"}


def test_item_gets_its_location_path_tags_and_custom_fields(ece, homebox):
    r10k = _by_name(ece._load_all_components())["10k resistor"]
    assert r10k["location"] == "Electronics Lab / Cabinet A / Drawer 1"
    assert r10k["tags"] == ["Resistor", "SMD"]
    assert r10k["value"] == "10k Ohm"
    assert r10k["package"] == "0805 SMD"
    assert r10k["voltage_rating"] == ""
    assert r10k["quantity"] == 7
    assert r10k["source"] == "homebox.db"


def test_location_override_beats_parent(ece, homebox):
    conn = sqlite3.connect(homebox / "data" / "homebox.db")
    conn.execute("UPDATE entities SET entity_location_entities = 'bench' WHERE id = 'led'")
    conn.commit()
    conn.close()
    led = _by_name(ece._load_all_components())["Red LED"]
    assert led["location"] == "Electronics Lab / Bench"


def test_item_without_a_location_keeps_the_placeholder(ece, homebox):
    conn = sqlite3.connect(homebox / "data" / "homebox.db")
    conn.execute("UPDATE entities SET entity_children = NULL WHERE id = 'led'")
    conn.commit()
    conn.close()
    assert _by_name(ece._load_all_components())["Red LED"]["location"] == "Homebox Storage"


def test_location_cycle_does_not_hang(ece, homebox):
    conn = sqlite3.connect(homebox / "data" / "homebox.db")
    conn.execute("UPDATE entities SET entity_children = 'dr1' WHERE id = 'lab'")  # lab -> dr1 -> cab -> lab
    conn.commit()
    conn.close()
    assert _by_name(ece._load_all_components())["10k resistor"]["location"]


def test_live_homebox_stock_wins_over_the_seed_csv(ece, homebox):
    (homebox / "seed.csv").write_text(
        "HB.import_ref,HB.name,HB.quantity,HB.location\n"
        "ECE-RES-10K,10k seed,100,Seed / Drawer\n"
        "ECE-ONLY-CSV,CSV only part,5,Seed / Drawer\n"
    )
    by_ref = {c["import_ref"]: c for c in ece._load_all_components()}
    assert by_ref["ECE-RES-10K"]["quantity"] == 7
    assert by_ref["ECE-RES-10K"]["source"] == "homebox.db"
    assert by_ref["ECE-ONLY-CSV"]["source"] == "seed.csv"


def test_db_is_opened_read_only_and_wal_survives(ece, homebox, monkeypatch):
    """A writer (the container) is still connected: the loader must not touch its WAL."""
    db = homebox / "data" / "homebox.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO entities (id, name, quantity, entity_type_entities, entity_children)"
                   " VALUES ('new', 'Fresh part', 2, 'I', 'dr1')")
    writer.commit()
    assert (homebox / "data" / "homebox.db-wal").exists()

    opened = []
    real_connect = sqlite3.connect

    def spy(target, *a, **kw):
        opened.append(str(target))
        return real_connect(target, *a, **kw)

    monkeypatch.setattr(ece.sqlite3, "connect", spy)
    try:
        names = {c["name"] for c in ece._load_all_components()}
    finally:
        writer.close()

    assert "Fresh part" in names  # committed-but-uncheckpointed rows are visible
    assert opened and all("mode=ro" in t for t in opened)
