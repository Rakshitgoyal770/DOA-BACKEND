# tests/conftest.py
"""
Shared test helpers.

`db` gives each test its own empty SQLite file with the real schema, so tests
never touch db/dao_intelligence.db. Insert helpers live in tests/helpers.py.
"""

import pytest

import db.schema as schema


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "DB_PATH", tmp_path / "test.db")
    conn = schema.get_connection()
    yield conn
    conn.close()
