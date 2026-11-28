from __future__ import annotations

import json
import os

from octryx_claude import device_cli_status, status_block, tools
from octryx_claude.platform import PlatformResult
from tests.conftest import BASE_URL


def _record(state, data: dict) -> None:
    folder = tools.tools_root(state.root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / tools.ENSURE_FILE).write_text(json.dumps(data))


def test_a_tool_the_service_is_fetching_is_not_called_missing(state, monkeypatch):
    monkeypatch.setattr(tools, "inventory", lambda _root: {"playwright": "1.64.1", "chromium": None, "gitleaks": None})
    never = tools.tool_states(state.root)
    assert never["playwright"] == "1.64.1"
    assert never["chromium"].startswith("not installed yet") and tools.INSTALL_COMMAND in never["chromium"]
    _record(state, {"pid": os.getpid(), "started": 1.0})
    assert tools.tool_states(state.root)["chromium"] == "being installed by the device service"
    _record(state, {"finished": 2.0, "problems": ["gitleaks: no pinned build for linux_riscv"]})
    done = tools.tool_states(state.root)
    assert done["gitleaks"].startswith("missing (no pinned build for linux_riscv; run: octryx-claude device tools")
    assert done["chromium"].startswith("not installed yet")


def test_ensure_records_its_start_and_its_problems(state, monkeypatch):
    seen = []
    failed = ["chromium: playwright install failed"]
    monkeypatch.setattr(tools, "_ensure", lambda root, fetch: seen.append(
        json.loads((tools.tools_root(root) / tools.ENSURE_FILE).read_text())) or failed)
    assert tools.ensure(state.root) == ["chromium: playwright install failed"]
    assert seen[0]["pid"] == os.getpid() and "finished" not in seen[0]
    record = json.loads((tools.tools_root(state.root) / tools.ENSURE_FILE).read_text())
    assert record["problems"] == ["chromium: playwright install failed"] and record["finished"]


def test_the_device_status_says_when_no_model_can_run_a_session(state, monkeypatch, capsys):
    config = state.config()
    state.write_config({**config, "base_url": BASE_URL, "workspace_id": "ws-1"})
    body = {"state": "allowed", "seat": {"seat_mode": "allowed", "reason": None},
            "models": {"governed": [], "seat": [], "seat_allows_governed_models": False}}
    monkeypatch.setattr("octryx_claude.platform.call_control_plane",
                        lambda *a, **k: PlatformResult("ok", body=body, status_code=200, state="allowed"))
    assert device_cli_status.model_note(state) == status_block.NO_MODEL_AVAILABLE
    (state.root / ".seat-session-ok").touch()  # a seat login the launcher saw work
    assert device_cli_status.model_note(state) == ""
