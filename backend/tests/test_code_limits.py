"""The Workspace's code limits come from its code style only."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Project, ToolCall
from app.services.code_style.store import set_workspace_profile
from app.services.devices.device_runs_keys import DeviceRunsPolicyError, normalize_device_runs
from app.services.workflow_runs.octryx.stop import run_stop
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import ROOT, _bound_run

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


STYLE = {"max_lines_per_file": 300, "max_function_lines": 40, "exclude": [{"glob": "tests/**", "reason": "other"}]}


def test_the_device_run_settings_hold_no_code_conventions():
    with pytest.raises(DeviceRunsPolicyError) as refused:
        normalize_device_runs({"code_conventions": {"max_file_lines": 300}}, "p")
    assert refused.value.reason == "invalid_device_runs"


def _call(gateway, tool: str, *, at, **parameters) -> ToolCall:
    return ToolCall(session_id=gateway.id, tool_name=tool, parameters={"source": "gateway", **parameters},
                    result={"is_error": False, "excerpt": parameters.pop("excerpt", "")}, status="success",
                    created_at=at)


@pytest.mark.asyncio
async def test_a_changing_phase_stays_open_until_the_files_fit_the_workspace_code_style(db):
    run, gateway, _key, workspace_id = await _bound_run(db)
    admin = await admin_user(db)
    await set_workspace_profile(db, await db.get(Project, workspace_id), STYLE, actor_id=admin.id)
    later = utc_now() + timedelta(seconds=5)
    rows = [_call(gateway, "Edit", at=later, file_path=f"{ROOT}/pay/totals.py"),
            _call(gateway, "Bash", at=later + timedelta(seconds=1), command="pytest -q",
                  excerpt="tests/test_zero.py::test_zero PASSED")]
    too_big = {"workflow_run_facts": {"sizes": {"files": {"pay/totals.py": 512}, "functions": []}}}
    blocked = await run_stop(db, session=gateway, hook_input=too_big, tool_calls=rows, test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked" and "pay/totals.py: new file has 512 lines (max 300)" in blocked["detail"]
    phase = blocked["workflow_run"]["phase"]
    assert "code_conventions" not in phase
    fine = {"workflow_run_facts": {"sizes": {"files": {"pay/totals.py": 120}, "functions": []}}}
    passed = await run_stop(db, session=gateway, hook_input=fine, tool_calls=rows, test_prefixes=(("pytest",),))
    assert passed["state"] == "passed"
