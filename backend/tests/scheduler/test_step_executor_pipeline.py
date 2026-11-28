"""Full StepExecutor pipelines with a mocked database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.execution.step_executor import StepExecutor
from tests.step_executor_support import make_scheduler, make_step, make_task, make_task_run


def make_db(steps: list) -> AsyncMock:
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = steps
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    return db


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_steps_execute_in_position_order(self):
        execution_order: list[str] = []

        async def fake_run_agent_for_task(db, task, prompt, **kwargs):
            execution_order.append(kwargs.get("session_metadata", {}).get("step_name", "?"))
            fake_sess = SimpleNamespace(id=str(uuid.uuid4()))
            return fake_sess, {"response": "✅ ok"}

        scheduler = make_scheduler()
        scheduler._run_agent_for_task = AsyncMock(side_effect=fake_run_agent_for_task)

        steps = [
            make_step(
                position=1,
                name="Fetch",
                step_type="connector_fetch",
                connector_action="search_jira_tickets",
                connector_params_json='{"jql":"x"}',
            ),
            make_step(position=2, name="Analyse", step_type="analysis"),
            make_step(position=3, name="Output", step_type="output", connector_action=None),
        ]
        steps[0].connector_params = {"jql": "x"}

        db = make_db(steps)

        with (
            patch("app.services.project.get_project_config", new_callable=AsyncMock, return_value={}),
            patch("app.tools.registry.execute_tool", new_callable=AsyncMock, return_value={"results": []}),
            patch(
                "app.scheduler.execution.step_executor.StepExecutor._load_agent_for_step",
                new_callable=AsyncMock,
                return_value=(None, None, None),
            ),
        ):
            ex = StepExecutor(scheduler)
            task = make_task()
            task_run = make_task_run()
            context = await ex.execute(db, task, task_run)

        assert list(context["steps"].keys()) == ["1", "2", "3"]
        assert "Analyse" in execution_order

    @pytest.mark.asyncio
    async def test_disabled_step_skipped(self):
        steps = [
            make_step(position=1, name="Step A", step_type="analysis", is_enabled=True),
            make_step(position=2, name="Step B", step_type="analysis", is_enabled=False),
            make_step(position=3, name="Step C", step_type="analysis", is_enabled=True),
        ]
        # make_db only returns enabled steps (the WHERE clause filters them)
        enabled_steps = [s for s in steps if s.is_enabled]
        db = make_db(enabled_steps)

        scheduler = make_scheduler()
        with patch(
            "app.scheduler.execution.step_executor.StepExecutor._load_agent_for_step",
            new_callable=AsyncMock,
            return_value=(None, None, None),
        ):
            ex = StepExecutor(scheduler)
            context = await ex.execute(db, make_task(), make_task_run())

        assert "2" not in context["steps"]
        assert "1" in context["steps"]
        assert "3" in context["steps"]

    @pytest.mark.asyncio
    async def test_no_steps_raises_value_error(self):
        db = make_db([])
        ex = StepExecutor(make_scheduler())
        with pytest.raises(ValueError, match="no enabled steps"):
            await ex.execute(db, make_task(), make_task_run())

    @pytest.mark.asyncio
    async def test_step_error_does_not_abort_pipeline(self):
        async def fail_agent(db, task, prompt, **kwargs):
            raise RuntimeError("agent exploded")

        scheduler = make_scheduler()
        scheduler._run_agent_for_task = AsyncMock(side_effect=fail_agent)

        steps = [
            make_step(position=1, name="Boom", step_type="analysis"),
            make_step(position=2, name="Continue", step_type="analysis"),
        ]
        db = make_db(steps)

        call_count = 0

        async def counting_agent(db, task, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first step fails")
            return SimpleNamespace(id=str(uuid.uuid4())), {"response": "✅ ok"}

        scheduler._run_agent_for_task = AsyncMock(side_effect=counting_agent)

        with patch(
            "app.scheduler.execution.step_executor.StepExecutor._load_agent_for_step",
            new_callable=AsyncMock,
            return_value=(None, None, None),
        ):
            ex = StepExecutor(scheduler)
            context = await ex.execute(db, make_task(), make_task_run())

        assert context["steps"]["1"].status == "error"
        assert context["steps"]["2"].status == "success"
