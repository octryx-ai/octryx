"""Shared helpers for the test_codex_driver_* modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _prepared(tmp_path: Path, **env: str) -> SimpleNamespace:
    session = tmp_path / "sessions" / "k1"
    session.mkdir(parents=True)
    return SimpleNamespace(
        session_key="k1", model="team-coder", profile="governed", settings_path=session / "settings.json",
        env={"PATH": "/usr/bin:/bin", "OCTRYX_SESSION_KEY": "k1", "OCTRYX_WORKSPACE_ID": "w1",
             "OCTRYX_CLAUDE_HOME": str(tmp_path),
             "ANTHROPIC_BASE_URL": "https://platform.test/api/v1/model-gateway/anthropic", **env},
        extra={"gateway": {"base_url": "https://platform.test", "session_key": "k1", "workspace_id": "w1",
                           "workflow_run": "run-1"},
               "hook_shim": "/opt/octryx/bin/octryx-claude", "permission_mode": "bypassPermissions"})


def _stop_replay(*rounds, then=None):
    from octryx_claude import plain_driver
    from octryx_claude.hooks import STOP_VERDICT_FILE
    from octryx_claude.state import write_private_json

    queue = list(rounds)

    def replay(prepared, cwd, shim="", prefix=()):
        answer, judged, *state = queue.pop(0) if len(queue) > 1 else queue[0]
        blocked = (answer or {}).get("decision") == "block"
        captured = plain_driver.deferred_stop_input(prepared) or {}
        if judged:
            write_private_json(plain_driver.deferred_stop_path(prepared).parent / STOP_VERDICT_FILE, {
                "outcome": "ok", "state": state[0] if state else ("blocked" if blocked else "passed"),
                "blocked": blocked, "session_id": captured.get("session_id"), "turn_id": captured.get("turn_id")})
        if then is not None:
            then()
        return answer, judged

    return replay
