"""Shared pytest fixtures: fake zwjs server transcript, FakeLLM, db paths."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture()
def tmp_db(tmp_path):
    from app.db import Database
    return Database(tmp_path / "test.db")


class FakeLLM:
    """Records calls and returns canned responses."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def chat(self, messages, system=None, tools=None, force_json=False):
        self.calls.append({"messages": messages, "system": system, "tools": tools})
        return self.responses.pop(0) if self.responses else {
            "text": json.dumps({"summary": "ok", "observations": [],
                                "recommended_actions": []}),
            "tool_calls": [], "tokens_in": 100, "tokens_out": 20,
        }
