"""Contract: coding-workspace git, lit and drawio keep exit status and closed codes, never their output (X6)."""

from __future__ import annotations

import json
import subprocess

import pytest

from app.services import diagram_export_service
from app.services.document_ingestion import parse as document_parse

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
