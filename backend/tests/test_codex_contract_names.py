"""A Codex session's run contract names Codex's own tools."""

from __future__ import annotations

from app.services.workflow_runs.octryx.codex_names import codex_on_device
from app.services.workflow_runs.octryx.contract_phase import _for_codex


def test_the_contract_names_codex_tools_for_a_codex_session():
    claude = ["Read (read_workspace_file)", "Write (write_workspace_file)", "Bash (run_test_suite)",
              "LS/Glob (list_workspace_directory)", "mcp__octryx-knowledge__workflow_run_status"]
    assert codex_on_device(claude) == [
        "shell (cat, sed -n, head) (read_workspace_file)", "apply_patch (write_workspace_file)",
        "shell (run_test_suite)", "shell (ls, find) (list_workspace_directory)",
        "mcp__octryx_knowledge__workflow_run_status"]
    contract = {"phase": {"tools": {"on_device": claude[:2], "on_device_note": "x", "allow": [], "deny": []}}}
    _for_codex(contract)
    assert contract["phase"]["tools"]["on_device"][1] == "apply_patch (write_workspace_file)"
    assert "apply_patch" in contract["phase"]["tools"]["on_device_note"]


def test_a_gateway_session_registered_as_codex_runs_codex_without_a_device_job():
    """The device job sits on the platform session, the model talks through its gateway session;
    the gateway session's registered engine decides."""
    import asyncio
    from types import SimpleNamespace

    from app.services.workflow_runs.octryx.contract_phase import _runs_codex

    codex = SimpleNamespace(id="s1", metadata_={"engine": "codex"})
    assert asyncio.run(_runs_codex(None, codex)) is True
    assert asyncio.run(_runs_codex(None, SimpleNamespace(id="", metadata_={"client": "claude_code"}))) is False
