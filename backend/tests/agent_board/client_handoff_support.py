"""Shared board, object store and gateway header helpers for the client handoff tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.services.agent_board import handoff_attachments
from tests.agent_board.test_takeover_rest import Board
from tests.agent_gateway.seat_presence_support import _gateway_headers
from tests.knowledge_evidence_s3_support import FakeS3Client, object_store

BASE = "/api/v1/agent-gateway/handoff"


AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(repo.parent / "gitconfig")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c",
                           "commit.gpgsign=false", *args], cwd=repo, env=env, capture_output=True, check=True,
                          text=True).stdout.strip()


def _bundle(tmp_path: Path, files: dict[str, str]) -> bytes:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "gitconfig").write_text("")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name, content in files.items():
        (repo / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "work")
    _git(repo, "bundle", "create", "-q", str(tmp_path / "work.bundle"), "main")
    return (tmp_path / "work.bundle").read_bytes()


# --- attachments ----------------------------------------------------------------------------------------------


@pytest.fixture
async def board(db):
    return await Board().build(db)


@pytest.fixture
def store(monkeypatch):
    fake = FakeS3Client()
    monkeypatch.setattr(handoff_attachments, "attachment_store", lambda: object_store(fake))
    return fake


async def _headers(db, board, user_id=None, session_key=None):
    user_id = user_id or board.anna
    return await _gateway_headers(db, user_id, board.ws, session_key or board.anna_key)
