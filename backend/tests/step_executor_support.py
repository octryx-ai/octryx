"""Tests for the generic StepExecutor.

All external I/O (DB, run_agent, execute_tool) is mocked so the tests run
without a live database or LLM.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def make_step(**kwargs) -> SimpleNamespace:
    """Create a minimal TaskStep-like namespace."""
    defaults = dict(
        id=str(uuid.uuid4()),
        position=1,
        name="Test Step",
        step_type="analysis",
        instructions="Do the thing.",
        connector=None,
        connector_action=None,
        connector_params_json="{}",
        runtime_selector_json="{}",
        context_fields_json="[]",
        allowed_tools_json="[]",
        spawn_strategy="per_item",
        spawn_count=None,
        max_fix_attempts=2,
        condition_expr=None,
        condition_true_step=None,
        condition_false_step=None,
        agent_timeout_seconds=300,
        is_enabled=True,
    )
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    # Replicate model properties
    ns.connector_params = json.loads(ns.connector_params_json)
    ns.runtime_selector = json.loads(ns.runtime_selector_json)
    ns.context_fields = json.loads(ns.context_fields_json)
    return ns


def make_task(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=str(uuid.uuid4()),
        name="Test Task",
        task_type="agent_run",
        agent_type="change",
        project_id=str(uuid.uuid4()),
        owner_id=str(uuid.uuid4()),
        max_concurrent_agents=3,
        config={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_task_run(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=str(uuid.uuid4()),
        task_id=None,
        session_id=None,
        steps_log=[],
        output=None,
    )
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    ns.steps_log = []
    return ns


def make_scheduler(**kwargs) -> MagicMock:
    """Return a mock TaskScheduler with _run_agent_for_task stubbed."""
    sched = MagicMock()
    fake_session = SimpleNamespace(id=str(uuid.uuid4()))
    fake_result = {"response": "✅ done", "session_id": fake_session.id}
    sched._run_agent_for_task = AsyncMock(return_value=(fake_session, fake_result))
    sched._assign_task_run_session = AsyncMock()
    return sched
