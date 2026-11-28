"""At the Codex seat's 5-hour limit the run takes the exhausted window's reset from the launcher's rollout windows
(``seat_rate_limits``) and goes on by itself after it, instead of pausing with an unknown reset."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.devices.seat_quota import rate_limit_reset, turn_limit
from app.services.workflow_runs.octryx.seat_fallback import REASON_NO_SAME_CLASS
from app.services.workflow_runs.states import STATUS_PAUSED
from app.services.workflow_runs.sweep import resume_after_seat_reset
from app.time_utils import utc_now
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

RESET = 1794850112  # 2026-11-16 17:28:32 UTC


def test_the_exhausted_windows_reset_is_the_seats_reset():
    windows = {"primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": RESET},
               "secondary": {"used_percent": 25.0, "window_minutes": 10080, "resets_at": RESET + 500_000}}
    assert rate_limit_reset(windows) == datetime.fromtimestamp(RESET, tz=UTC).replace(tzinfo=None)
    assert rate_limit_reset({"primary": {"used_percent": 80.0, "resets_at": RESET}}) is None
    said = datetime(2026, 11, 16, 15, 24)
    limit = turn_limit({"status": "error", "error": "usage_limit", "result_text": "", "seat_rate_limits": windows},
                       said_at=said)
    assert limit is not None and limit.reset_known and limit.until == rate_limit_reset(windows)
    unnamed = turn_limit({"status": "error", "error": "usage_limit", "result_text": ""}, said_at=said)
    assert unnamed is not None and not unnamed.reset_known


@pytest.mark.asyncio
async def test_a_run_paused_on_the_seats_named_reset_goes_on_by_itself_after_it(db):
    from tests.server_build_lock import lift_server_build_lock  # noqa: F401 - used through the fixture below
    from tests.workflow_run_octryx_support import _bound_run, _fix_definition

    run, _gateway, _key, _workspace_id = await _bound_run(db, _fix_definition(protect=False))
    reset = utc_now() + timedelta(minutes=10)
    pause = {"reason": "runtime_failed", "code": REASON_NO_SAME_CLASS, "reset_at": reset.isoformat(),
             "reset_known": True, "engine": "codex", "resume": {"kind": "restart", "node_id": run.current_node_id}}
    run.status, run.pause_reason = STATUS_PAUSED, "runtime_failed"
    run.node_state = {**dict(run.node_state or {}), "pause": pause}
    await db.commit()

    assert await resume_after_seat_reset(db, now=reset - timedelta(minutes=1)) == []
    assert await resume_after_seat_reset(db, now=reset + timedelta(seconds=1)) == [run.id]
    await db.refresh(run)
    assert run.status != STATUS_PAUSED and run.pause_reason is None


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def test_the_seat_allowance_is_a_gauge_per_engine_and_window_without_empty_series():
    from app.services.agent_gateway.allowance import Allowance
    from app.services.observability import seat_allowance_metrics as gauges

    gauges.reset()
    assert gauges.seat_allowance_lines() == []
    at = datetime(2026, 11, 16, 15, 24)
    gauges.observe("codex", Allowance(100.0, datetime(2026, 11, 16, 17, 28, 32), 25.0, None), at=at)
    gauges.observe("claude_code", Allowance(None, None, 12.5, None), at=at)
    gauges.observe("other", Allowance(1.0, None, 1.0, None), at=at)
    lines = gauges.seat_allowance_lines()
    assert 'octryx_seat_allowance_used_ratio{engine="codex",window="5h"} 1' in lines
    assert 'octryx_seat_allowance_used_ratio{engine="codex",window="7d"} 0.25' in lines
    assert 'octryx_seat_allowance_used_ratio{engine="claude_code",window="7d"} 0.125' in lines
    assert f'octryx_seat_allowance_resets_timestamp_seconds{{engine="codex",window="5h"}} {RESET}' in lines
    assert not any('engine="claude_code",window="5h"' in line for line in lines)
    assert not any('engine="other"' in line for line in lines)
    assert lines.count("# TYPE octryx_seat_allowance_used_ratio gauge") == 1
    gauges.reset()
