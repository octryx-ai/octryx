from __future__ import annotations

import os

from octryx_claude import codex_seat, engine_report
from octryx_claude.device_runtime import device_report
from octryx_claude.profile_choice import CLAUDE_CREDENTIAL_FILE, SEAT_SESSION_MARKER


def _executable(path):
    path.write_text("#!/bin/sh\n")
    os.chmod(path, 0o755)
    return path


def test_codex_counts_only_as_an_executable_on_the_path_or_the_configured_one(tmp_path):
    assert engine_report.installed_engines({"PATH": str(tmp_path)}) == ["claude_code"]
    _executable(tmp_path / "codex")
    assert engine_report.installed_engines({"PATH": str(tmp_path)}) == ["claude_code", "codex"]
    elsewhere = _executable(tmp_path / "my-codex")
    configured = {"PATH": "", "OCTRYX_CODEX_PATH": str(elsewhere)}
    assert engine_report.installed_engines(configured) == ["claude_code", "codex"]
    (tmp_path / "not-runnable").write_text("")
    assert engine_report.installed_engines({"PATH": "", "OCTRYX_CODEX_PATH": str(tmp_path / "not-runnable")}) == \
        ["claude_code"]


def test_each_engine_reports_its_own_seat_login(state, monkeypatch):
    monkeypatch.setattr(codex_seat, "reported_login", lambda _root: False)
    assert engine_report.seat_engines(state) == []
    (state.root / SEAT_SESSION_MARKER).touch()
    assert engine_report.seat_engines(state) == ["claude_code"]
    (state.root / SEAT_SESSION_MARKER).unlink()
    monkeypatch.setattr(codex_seat, "reported_login", lambda _root: True)
    assert engine_report.seat_engines(state) == ["codex"], "a ChatGPT login is no Claude seat"
    seat_dir = state.claude_config_dir_for("seat")
    seat_dir.mkdir(parents=True, exist_ok=True)
    (seat_dir / CLAUDE_CREDENTIAL_FILE).write_text("{}")
    assert engine_report.seat_engines(state) == ["claude_code", "codex"]


def test_the_handshake_reports_both_lists(state, monkeypatch):
    monkeypatch.setattr(codex_seat, "reported_login", lambda _root: True)
    monkeypatch.setattr(engine_report, "installed_engines", lambda: ["claude_code"])
    report = device_report(state)
    assert (report["seat_engines"], report["engines"]) == (["codex"], ["claude_code"])
