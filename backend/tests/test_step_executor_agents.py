"""Agent loading and sub-agent spawning in the StepExecutor."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.execution.step_executor import StepExecutor, StepResult
from app.services.agent_definition_execution_outcomes import AgentDefinitionExecutionError
from app.services.agent_definition_execution_states import (
    EXECUTION_MODE_DRAFT,
    EXECUTION_MODE_PUBLISHED,
    NOT_PUBLISHED_ERROR_CODE,
    SOURCE_LIVE_DRAFT_ROW,
    STATUS_NEEDS_PUBLICATION,
    STATUS_RESOLVED,
    AgentDefinitionResolution,
)
from tests.step_executor_support import make_scheduler, make_step, make_task, make_task_run

# ---------------------------------------------------------------------------
# Agent loading
# ---------------------------------------------------------------------------


class TestAgentLoading:
    @pytest.mark.asyncio
    async def test_step_level_empty_agent_id_suppresses_task_agent_and_keeps_runtime_target(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            connector_params_json='{"agent_definition_id": ""}',
            runtime_selector_json='{"runtime_target_id": "rt-step"}',
        )
        step.connector_params = {"agent_definition_id": ""}
        step.runtime_selector = {"runtime_target_id": "rt-step"}
        task = make_task(config={"agent_definition_id": "agent-task", "thinking_level": "deep"})

        result = await ex._load_agent_for_step(step, task, AsyncMock())

        assert result == (None, "rt-step", "deep")

    @pytest.mark.asyncio
    async def test_step_agent_overrides_task_agent_and_agent_fields_override_fallbacks(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            connector_params_json='{"agent_definition_id": "agent-step"}',
            runtime_selector_json='{"runtime_target_id": "rt-step"}',
        )
        step.connector_params = {"agent_definition_id": "agent-step"}
        step.runtime_selector = {"runtime_target_id": "rt-step"}
        task = make_task(config={"agent_definition_id": "agent-task", "thinking_level": "light"})

        # The loader does not query and serialize the live row itself.
        # It asks the explicit resolution boundary and takes the runtime target
        # and thinking level from the *resolved* header.
        db = AsyncMock()
        resolution = AgentDefinitionResolution(
            definition_id="agent-step",
            mode=EXECUTION_MODE_DRAFT,
            status=STATUS_RESOLVED,
            source=SOURCE_LIVE_DRAFT_ROW,
            payload={
                "id": "agent-step",
                "name": "Agent",
                "runtimeTargetId": "rt-agent",
                "thinkingLevel": "deep",
                "prompt": "prompt-body",
            },
        )

        with patch(
            "app.services.agent_definition_execution.resolve_agent_definition_for_execution",
            new_callable=AsyncMock,
            return_value=resolution,
        ) as mock_resolve:
            agent_def, runtime_target_id, thinking_level = await ex._load_agent_for_step(step, task, db)

        mock_resolve.assert_awaited_once_with(db, definition_id="agent-step")
        assert agent_def == resolution.payload
        assert runtime_target_id == "rt-agent"
        assert thinking_level == "deep"

    @pytest.mark.asyncio
    async def test_unpublished_definition_fails_the_step_with_typed_state(self):
        """Published mode refuses unpublished content instead of executing it.

        A background step has no caller to answer 409 to, so it fails: running the
        step without the agent definition it was configured with would execute a
        different turn than the one that was configured. The typed refusal is
        persisted on the step, which is what a run log has to show.
        """
        ex = StepExecutor(make_scheduler())
        step = make_step(
            connector_params_json='{"agent_definition_id": "agent-step"}',
            runtime_selector_json='{"runtime_target_id": "rt-step"}',
        )
        step.connector_params = {"agent_definition_id": "agent-step"}
        step.runtime_selector = {"runtime_target_id": "rt-step"}
        task = make_task(config={"thinking_level": "light"})
        refused = AgentDefinitionResolution(
            definition_id="agent-step",
            mode=EXECUTION_MODE_PUBLISHED,
            status=STATUS_NEEDS_PUBLICATION,
        )

        with patch(
            "app.services.agent_definition_execution.resolve_agent_definition_for_execution",
            new_callable=AsyncMock,
            return_value=refused,
        ):
            with pytest.raises(AgentDefinitionExecutionError) as raised:
                await ex._load_agent_for_step(step, task, AsyncMock())

            # The dispatcher turns it into a failed step carrying the typed state.
            result = await ex._execute_step(
                step, {}, AsyncMock(), task, make_task_run()
            )

        assert raised.value.code == NOT_PUBLISHED_ERROR_CODE
        assert result.status == "error"
        assert result.error == NOT_PUBLISHED_ERROR_CODE
        assert result.refusal["status"] == STATUS_NEEDS_PUBLICATION
        assert result.refusal["definition_id"] == "agent-step"
        # It survives into the persisted step log, not only in memory.
        assert result.to_dict()["refusal"]["code"] == NOT_PUBLISHED_ERROR_CODE


# ---------------------------------------------------------------------------
# sub_agent_spawn step
# ---------------------------------------------------------------------------


class TestSubAgentSpawn:
    @pytest.mark.asyncio
    async def test_no_items_returns_success_with_zero_spawned(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(step_type="sub_agent_spawn", context_fields_json="[]")
        step.context_fields = []
        result = await ex._exec_sub_agent_spawn(
            step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
        )
        assert result.status == "success"
        assert result.output["spawned"] == 0

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self):
        """Ensure max_concurrent_agents limits simultaneous executions."""
        concurrent_count = 0
        max_seen = 0

        async def fake_run_agent(**kwargs):
            nonlocal concurrent_count, max_seen
            concurrent_count += 1
            max_seen = max(max_seen, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            yield SimpleNamespace(role="assistant", content="done", tool_results=None)

        items = [{"key": f"T-{i}"} for i in range(6)]
        step = make_step(
            step_type="sub_agent_spawn",
            context_fields_json=json.dumps(["steps.1.output.new_items"]),
        )
        step.context_fields = ["steps.1.output.new_items"]
        sr = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"new_items": items},
        )
        context = {"task_name": "T", "steps": {"1": sr}}
        task = make_task(max_concurrent_agents=2)

        with (
            patch(
                "app.scheduler.execution.step_executor.StepExecutor._load_agent_for_step",
                new_callable=AsyncMock,
                return_value=(None, None, None),
            ),
            patch("app.scheduler.execution.step_executor.async_session_factory") as mock_factory,
            patch("app.scheduler.execution.step_executor.run_agent", side_effect=fake_run_agent),
        ):
            # async context manager mock for setup_db
            setup_db_mock = MagicMock()
            setup_db_mock.add = MagicMock()
            setup_db_mock.commit = AsyncMock()
            setup_db_mock.__aenter__ = AsyncMock(return_value=setup_db_mock)
            setup_db_mock.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value = setup_db_mock

            ex = StepExecutor(make_scheduler())
            result = await ex._exec_sub_agent_spawn(step, context, AsyncMock(), task, make_task_run())

        assert result.output["spawned"] == 6
        assert max_seen <= 2, f"Concurrency limit breached: {max_seen} simultaneous agents"
