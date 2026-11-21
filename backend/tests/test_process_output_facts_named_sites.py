"""Contract: coding-workspace git, lit and drawio keep exit status and closed codes, never their output (X6)."""

from __future__ import annotations

import json
import subprocess

import pytest

from app.services import diagram_export_service
from app.services.document_ingestion import parse as document_parse
from app.services.secure_work.coding import workspace_git

FAKE_TOKEN = "ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123"
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
TOOL_OUTPUT = f"fatal: unable to access '{CREDENTIALED_URL}' token {FAKE_TOKEN} at {INTERNAL_PATH}"
MARKERS = (FAKE_TOKEN, "tok3n", CREDENTIALED_URL, INTERNAL_PATH)


def _assert_clean(value: object) -> None:
    serialized = json.dumps(value, default=str)
    for marker in MARKERS:
        assert marker not in serialized


def _poisoned_run(returncode: int, stdout: str = TOOL_OUTPUT):
    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=TOOL_OUTPUT)

    return fake_run


def test_coding_workspace_git_evidence_keeps_subcommand_exit_status_and_outcome_only(tmp_path, monkeypatch):
    source_root = tmp_path / "srv" / "internal" / "x6-secret-path"
    (source_root / ".git").mkdir(parents=True)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    sha = "0123456789abcdef0123456789abcdef01234567"

    def fake_run(argv, **_kwargs):
        if argv[1] == "clone":
            (workspace_root / ".git").mkdir()
            return subprocess.CompletedProcess(argv, 0, stdout=TOOL_OUTPUT, stderr=TOOL_OUTPUT)
        if argv[1:3] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{sha}\n", stderr=TOOL_OUTPUT)
        return subprocess.CompletedProcess(argv, 128, stdout=TOOL_OUTPUT, stderr=TOOL_OUTPUT)

    monkeypatch.setattr(workspace_git.subprocess, "run", fake_run)
    result = workspace_git._materialize_local_git_workspace(
        source_root=source_root, workspace_root=workspace_root, feature_branch="feature/x6", base_branch="main"
    )

    assert result["base_commit"] == sha
    assert result["status"] == "blocked"  # the checkout failed with exit 128
    assert result["evidence"]["commands"] == [
        {"git": "clone", "exit_code": 0, "outcome": "succeeded"},
        {"git": "rev-parse", "exit_code": 0, "outcome": "succeeded"},
        {"git": "rev-parse", "exit_code": 128, "outcome": "failed"},
        {"git": "checkout", "exit_code": 128, "outcome": "failed"},
    ]
    _assert_clean(result)
    assert str(source_root) not in json.dumps(result)


def test_lit_and_drawio_failures_carry_the_exit_status_only(tmp_path, monkeypatch):
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(document_parse.subprocess, "run", _poisoned_run(3))
    parsed = document_parse.parse_document_file(document, parsed_dir=tmp_path / "parsed")
    assert (parsed.success, parsed.error) == (False, "lit_parse_failed exit_code=3")
    _assert_clean({"error": parsed.error, "text": parsed.text})

    monkeypatch.setattr(diagram_export_service.subprocess, "run", _poisoned_run(9))
    with pytest.raises(diagram_export_service.DiagramRenderError) as raised:
        diagram_export_service._run_drawio_export("drawio", "<mxfile/>", 2)
    assert str(raised.value) == "drawio_export_failed exit_code=9"
    _assert_clean(str(raised.value))
