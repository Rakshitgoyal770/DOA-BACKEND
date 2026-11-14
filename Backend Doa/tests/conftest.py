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


@pytest.fixture(autouse=True)
def agent_pipeline_unless_a_test_asks(monkeypatch):
    """Existing chat tests script the agent; a test of the planned pipeline sets CHAT_PIPELINE itself.
    Without this default a test could reach a real model provider through the planner."""
    monkeypatch.setenv("CHAT_PIPELINE", "agent")
