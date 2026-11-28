"""Run quality counters: a person's action on a run, refused Stops by check type, red-before and fail-fast,
device reconnects and devices online; counted in memory at the event, never by a database query."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.models import Project
from app.services.code_style.store import set_workspace_profile
from app.services.devices.hub import DeviceHub, device_hub
from app.services.observability import agent_metrics, run_quality_metrics
from app.services.observability.token_profile import metrics as token_metrics
from app.services.workflow_runs.octryx.code_limits import STYLE_CHECK
from app.services.workflow_runs.octryx.stop import run_stop
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import admin_user
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_code_limits import STYLE, _call
from tests.workflow_run_octryx_continuation_support import _device_run
from tests.workflow_run_octryx_support import ROOT, _bound_run

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture(autouse=True)
def _empty():
    agent_metrics.reset()
    device_hub.clear()
    yield
    agent_metrics.reset()
    device_hub.clear()


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def _interventions() -> dict[str, float]:
    return {key[-1]: value for key, value in run_quality_metrics.INTERVENTIONS.series.items()}


@pytest.mark.asyncio
async def test_a_persons_action_on_a_run_counts_once_it_is_done_and_a_refused_one_never(client, db):
    admin, _device, _thread, run = await _device_run(db)
    await db.commit()
    path = f"/api/v1/workflow-runs/{run.id}/emergency-stop"
    assert (await client.post(path, json={"reason": " "}, headers=bearer(admin.id))).status_code == 422
    assert _interventions() == {}
    assert (await client.post(path, json={"reason": "leaking secrets"}, headers=bearer(admin.id))).status_code == 200
    assert _interventions() == {"emergency_stop": 1}
    [labels] = run_quality_metrics.INTERVENTIONS.series
    assert labels[0] == run.workflow_key and run.id not in labels


@pytest.mark.asyncio
async def test_a_stop_refused_as_not_done_counts_by_the_failed_checks_type(db):
    run, gateway, _key, workspace_id = await _bound_run(db)
    admin = await admin_user(db)
    await set_workspace_profile(db, await db.get(Project, workspace_id), STYLE, actor_id=admin.id)
    later = utc_now() + timedelta(seconds=5)
    rows = [_call(gateway, "Edit", at=later, file_path=f"{ROOT}/pay/totals.py"),
            _call(gateway, "Bash", at=later + timedelta(seconds=1), command="pytest -q",
                  excerpt="tests/test_zero.py::test_zero PASSED")]
    too_big = {"workflow_run_facts": {"sizes": {"files": {"pay/totals.py": 512}, "functions": []}}}
    blocked = await run_stop(db, session=gateway, hook_input=too_big, tool_calls=rows, test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked"
    assert not run_quality_metrics.STOP_NOT_DONE.series
    await db.commit()
    assert run_quality_metrics.STOP_NOT_DONE.series == {(str(run.workflow_key), STYLE_CHECK): 1}


def test_red_before_and_fail_fast_skips_per_pipeline_report():
    run_quality_metrics.pipeline_reported("bug-fix", {"state": "red", "unproven": ["tests/test_a.py::test_a"],
                                                      "commands": [{"command": "pytest", "exit_code": 1},
                                                                   {"command": "e2e", "skipped": "not run"}]})
    run_quality_metrics.pipeline_reported("bug-fix", {"state": "green", "unproven": []})
    run_quality_metrics.pipeline_reported("docs", {"state": "green"})
    assert run_quality_metrics.RED_BEFORE.series == {("bug-fix", "unproven"): 1, ("bug-fix", "proven"): 1,
                                                     ("docs", "not_required"): 1}
    assert run_quality_metrics.PIPELINE_SKIPPED.series == {("bug-fix",): 1}


class _Connection:
    def __init__(self, device_id: str, healthy: bool = True) -> None:
        self.device_id, self._healthy = device_id, healthy

    def healthy(self) -> bool:
        return self._healthy


@pytest.mark.asyncio
async def test_devices_online_and_reconnects_come_from_the_hub():
    hub = DeviceHub()
    await hub.attach(_Connection("d1"))
    await hub.attach(_Connection("d2", healthy=False))
    assert run_quality_metrics.online_lines(hub)[-1] == "octryx_devices_online 1"
    await hub.attach(_Connection("d1"))
    assert run_quality_metrics.DEVICE_RECONNECTS.series == {(): 1}


def test_the_token_labels_never_read_the_database():
    source = Path(token_metrics.__file__).read_text(encoding="utf-8")
    assert "select(" not in source and ".execute(" not in source
    source = Path(run_quality_metrics.__file__).read_text(encoding="utf-8")
    assert "select(" not in source and ".execute(" not in source
