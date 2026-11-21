"""Launch wiring of code intelligence: same session context, skip flag, never blocks."""

from __future__ import annotations

import json
from pathlib import Path

from octryx_claude import cli

from .conftest import BASE_URL


def test_launch_runs_code_intelligence_with_the_session_context(launch_env, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--", "-p", "hi"]) == 0

    context, cwd = launch_env["code_intelligence"]
    argv = json.loads(launch_env["record"].read_text())["argv"]
    assert argv[argv.index("--session-id") + 1] == context.session_key
    assert context.workspace_id == "ws-1" and context.base_url == BASE_URL
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert "code intelligence: off (internal_error)" in capsys.readouterr().err


def test_no_code_intelligence_flag_sends_nothing(launch_env, capsys):
    assert cli.main(["--no-code-intelligence", "--", "-p", "hi"]) == 0

    assert "code_intelligence" not in launch_env["steps"] and launch_env["record"].exists()
    assert "octryx-claude: code intelligence: off (skipped_by_flag)\n" in capsys.readouterr().err
