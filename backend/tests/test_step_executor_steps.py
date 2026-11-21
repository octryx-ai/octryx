"""Condition, connector fetch, analysis and verification steps of the StepExecutor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.execution.step_executor import StepExecutor
from tests.step_executor_support import make_scheduler, make_step, make_task, make_task_run

# ---------------------------------------------------------------------------
# Condition step
# ---------------------------------------------------------------------------


class TestConditionStep:
    @pytest.mark.asyncio
    async def test_true_branch(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="condition",
            condition_expr="len(context['steps']) > 0",
            condition_true_step=3,
            condition_false_step=5,
        )
        context = {"steps": {"1": MagicMock()}}
        result = await ex._exec_condition(step, context, AsyncMock(), make_task(), make_task_run())
        assert result.status == "success"
        assert result.output["next_position"] == 3
        assert result.output["condition_result"] is True

    @pytest.mark.asyncio
    async def test_false_branch(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="condition",
            condition_expr="False",
            condition_true_step=3,
            condition_false_step=5,
        )
        result = await ex._exec_condition(step, {"steps": {}}, AsyncMock(), make_task(), make_task_run())
        assert result.output["next_position"] == 5

    @pytest.mark.asyncio
    async def test_bad_expression_defaults_false(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="condition",
            condition_expr="this_will_raise_nameerror()",
            condition_true_step=2,
            condition_false_step=4,
        )
        result = await ex._exec_condition(step, {"steps": {}}, AsyncMock(), make_task(), make_task_run())
        assert result.output["next_position"] == 4

    @pytest.mark.asyncio
    async def test_unsafe_expression_is_rejected(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="condition",
            condition_expr="__import__('os').system('echo hacked')",
            condition_true_step=2,
            condition_false_step=4,
        )
        result = await ex._exec_condition(step, {"steps": {}}, AsyncMock(), make_task(), make_task_run())
        assert result.output["condition_result"] is False
        assert result.output["next_position"] == 4

    @pytest.mark.asyncio
    async def test_empty_expr_returns_error(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(step_type="condition", condition_expr="")
        result = await ex._exec_condition(step, {}, AsyncMock(), make_task(), make_task_run())
        assert result.status == "error"


# ---------------------------------------------------------------------------
# connector_fetch step
# ---------------------------------------------------------------------------


class TestConnectorFetch:
    @pytest.mark.asyncio
    async def test_calls_execute_tool_with_params(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="connector_fetch",
            connector="jira",
            connector_action="search_jira_tickets",
            connector_params_json='{"jql": "project=OCX", "limit": 5}',
        )
        step.connector_params = {"jql": "project=OCX", "limit": 5}

        tool_result = {"results": [{"key": "OCX-1", "updated": "2026-03-01"}]}

        with (
            patch("app.scheduler.execution.step_executor.StepExecutor._load_agent_for_step"),
            patch("app.services.project.get_project_config", new_callable=AsyncMock, return_value={}),
            patch("app.tools.registry.execute_tool", new_callable=AsyncMock, return_value=tool_result) as mock_tool,
        ):
            db = AsyncMock()
            db.commit = AsyncMock()
            task = make_task()
            task_run = make_task_run()
            result = await ex._exec_connector_fetch(step, {"steps": {}}, db, task, task_run)

        mock_tool.assert_awaited_once()
        call_args = mock_tool.call_args
        assert call_args[0][0] == "search_jira_tickets"
        assert result.status == "success"
        assert result.output["new_item_count"] == 1

    @pytest.mark.asyncio
    async def test_error_from_tool_becomes_step_error(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(
            step_type="connector_fetch",
            connector_action="search_jira_tickets",
            connector_params_json="{}",
        )
        step.connector_params = {}

        with (
            patch("app.services.project.get_project_config", new_callable=AsyncMock, return_value={}),
            patch(
                "app.tools.registry.execute_tool", new_callable=AsyncMock, return_value={"error": "Jira unreachable"}
            ),
        ):
            result = await ex._exec_connector_fetch(step, {"steps": {}}, AsyncMock(), make_task(), make_task_run())

        assert result.status == "error"
        assert "Jira unreachable" in (result.error or "")

    @pytest.mark.asyncio
    async def test_missing_connector_action_returns_error(self):
        ex = StepExecutor(make_scheduler())
        step = make_step(step_type="connector_fetch", connector_action=None)
        step.connector_params = {}
        result = await ex._exec_connector_fetch(step, {}, AsyncMock(), make_task(), make_task_run())
        assert result.status == "error"


# ---------------------------------------------------------------------------
# analysis step
# ---------------------------------------------------------------------------


class TestAnalysisStep:
    @pytest.mark.asyncio
    async def test_calls_run_agent_for_task(self):
        scheduler = make_scheduler()
        ex = StepExecutor(scheduler)
        step = make_step(step_type="analysis", instructions="Analyse carefully.")

        with patch.object(ex, "_load_agent_for_step", new_callable=AsyncMock, return_value=(None, None, None)):
            db = AsyncMock()
            db.commit = AsyncMock()
            task = make_task()
            task_run = make_task_run()
            result = await ex._exec_analysis(step, {"task_name": "T", "steps": {}}, db, task, task_run)

        scheduler._run_agent_for_task.assert_awaited_once()
        assert result.status == "success"
        assert len(result.session_ids) == 1

    @pytest.mark.asyncio
    async def test_skip_session_reuse_is_passed(self):
        scheduler = make_scheduler()
        ex = StepExecutor(scheduler)
        step = make_step(step_type="analysis")

        with patch.object(ex, "_load_agent_for_step", new_callable=AsyncMock, return_value=(None, None, None)):
            await ex._exec_analysis(step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run())

        call_kwargs = scheduler._run_agent_for_task.call_args[1]
        assert call_kwargs.get("skip_session_reuse") is True


# ---------------------------------------------------------------------------
# verification step
# ---------------------------------------------------------------------------


class TestVerificationStep:
    @pytest.mark.asyncio
    async def test_passes_on_success_response(self):
        scheduler = make_scheduler()
        fake_session = SimpleNamespace(id="sess-1")
        scheduler._run_agent_for_task = AsyncMock(return_value=(fake_session, {"response": "✅ All checks passed"}))
        ex = StepExecutor(scheduler)
        step = make_step(step_type="verification", max_fix_attempts=2)

        with patch.object(ex, "_load_agent_for_step", new_callable=AsyncMock, return_value=(None, None, None)):
            result = await ex._exec_verification(
                step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
            )

        assert result.status == "success"
        assert result.fix_attempts == 0

    @pytest.mark.asyncio
    async def test_retries_on_failure_and_eventually_errors(self):
        scheduler = make_scheduler()
        fake_session = SimpleNamespace(id="sess-1")
        scheduler._run_agent_for_task = AsyncMock(return_value=(fake_session, {"response": "❌ verification failed"}))
        ex = StepExecutor(scheduler)
        step = make_step(step_type="verification", max_fix_attempts=2)

        with patch.object(ex, "_load_agent_for_step", new_callable=AsyncMock, return_value=(None, None, None)):
            result = await ex._exec_verification(
                step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
            )

        assert result.status == "error"
        assert result.fix_attempts == 2
        # Called 3 times: initial + 2 retries
        assert scheduler._run_agent_for_task.await_count == 3
