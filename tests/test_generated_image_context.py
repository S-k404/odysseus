"""Describing a picture fast: src/chat_handler.py helpers.

A picture this app generated is already described by its own prompt, and a picture described once keeps its
description by content, so asking about it again never needs another look by a vision model.
"""

import types

from src import chat_handler as ch


def test_the_same_picture_gets_the_same_cache_file_whatever_it_is_called(tmp_path, monkeypatch):
    monkeypatch.setattr(ch, "UPLOAD_DIR", str(tmp_path))
    a, b, other = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    a.write_bytes(b"pixels")
    b.write_bytes(b"pixels")
    other.write_bytes(b"different pixels")

    assert ch._image_hash_cache_path(str(a)) == ch._image_hash_cache_path(str(b))
    assert ch._image_hash_cache_path(str(a)) != ch._image_hash_cache_path(str(other))
    assert ch._image_hash_cache_path(str(a)).startswith(str(tmp_path / ".vision" / "by-hash"))
    assert ch._image_hash_cache_path(str(tmp_path / "missing.png")) is None


class _Db:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def query(self, model):
        return self

    def filter(self, *conditions):
        return self

    def first(self):
        return self.row

    def close(self):
        self.closed = True


def _gallery(monkeypatch, row):
    import src.database as database
    db = _Db(row)
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    return db


def test_a_generated_picture_is_described_by_the_prompt_that_made_it(monkeypatch):
    db = _gallery(monkeypatch, types.SimpleNamespace(prompt="a lighthouse at sunset, watercolor", caption=""))

    text = ch._generated_image_context("/uploads/abc123.png")

    assert 'from the prompt: "a lighthouse at sunset, watercolor"' in text and "not analysed" in text
    assert db.closed


def test_a_saved_caption_is_added_when_there_is_one(monkeypatch):
    _gallery(monkeypatch, types.SimpleNamespace(prompt="a red fox", caption="A fox standing in snow."))
    assert "Description of the result: A fox standing in snow." in ch._generated_image_context("fox.png")
    _gallery(monkeypatch, types.SimpleNamespace(prompt="a red fox", caption="[vision model unavailable]"))
    assert "not analysed" in ch._generated_image_context("fox.png")


def test_a_picture_that_was_not_generated_here_gets_no_shortcut(monkeypatch):
    _gallery(monkeypatch, None)
    assert ch._generated_image_context("holiday.jpg") is None
    assert ch._generated_image_context("") is None
    _gallery(monkeypatch, types.SimpleNamespace(prompt="", caption=""))
    assert ch._generated_image_context("empty.png") is None
