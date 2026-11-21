"""Uniform agent definition resolution provenance across StepExecutor steps."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.execution.step_executor import StepExecutor, StepResult
from app.services.agent_definition_execution_outcomes import payload_resolution_metadata
from app.services.agent_definition_execution_states import (
    EXECUTION_MODE_PUBLISHED,
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    RESOLUTION_METADATA_KEY,
    SOURCE_PUBLISHED_REVISION,
)
from tests.step_executor_support import make_scheduler, make_step, make_task, make_task_run

# ---------------------------------------------------------------------------
# Resolution provenance
# ---------------------------------------------------------------------------

#: A resolved published payload, the way ``_load_agent_for_step`` hands one over.
PUBLISHED_AGENT_PAYLOAD = {
    "id": "agent-step",
    "name": "Published Agent",
    PAYLOAD_MODE_KEY: EXECUTION_MODE_PUBLISHED,
    PAYLOAD_SOURCE_KEY: SOURCE_PUBLISHED_REVISION,
    PAYLOAD_REVISION_ID_KEY: "revision-1",
    PAYLOAD_REVISION_NUMBER_KEY: 3,
}


EXPECTED_RESOLUTION_ENTRY = payload_resolution_metadata(PUBLISHED_AGENT_PAYLOAD)[
    RESOLUTION_METADATA_KEY
]


class TestResolutionProvenanceIsUniform:
    """Every session this executor opens names the agent-definition source the same way.

    Provenance existed in two shapes: the analysis step recorded the canonical
    ``agent_definition_resolution`` entry and the verification and sub-agent-spawn
    steps recorded nothing, so for two of the three step types that execute an agent a
    persisted run could not answer whether it ran published content.
    """

    def _patched_loader(self, executor: StepExecutor):
        return patch.object(
            executor,
            "_load_agent_for_step",
            new_callable=AsyncMock,
            return_value=(PUBLISHED_AGENT_PAYLOAD, "rt-1", "deep"),
        )

    @pytest.mark.asyncio
    async def test_the_analysis_step_records_the_resolution(self):
        scheduler = make_scheduler()
        ex = StepExecutor(scheduler)
        step = make_step(step_type="analysis")

        with self._patched_loader(ex):
            await ex._exec_analysis(
                step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
            )

        metadata = scheduler._run_agent_for_task.call_args[1]["session_metadata"]
        assert metadata[RESOLUTION_METADATA_KEY] == EXPECTED_RESOLUTION_ENTRY

    @pytest.mark.asyncio
    async def test_the_verification_step_records_the_same_entry(self):
        scheduler = make_scheduler()
        ex = StepExecutor(scheduler)
        step = make_step(step_type="verification", max_fix_attempts=2)

        with self._patched_loader(ex):
            await ex._exec_verification(
                step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
            )

        metadata = scheduler._run_agent_for_task.call_args[1]["session_metadata"]
        assert metadata[RESOLUTION_METADATA_KEY] == EXPECTED_RESOLUTION_ENTRY

    @pytest.mark.asyncio
    async def test_a_spawned_sub_session_records_the_same_entry(self):
        items = [{"key": "T-1"}, {"key": "T-2"}]
        step = make_step(
            step_type="sub_agent_spawn",
            context_fields_json=json.dumps(["steps.1.output.new_items"]),
        )
        step.context_fields = ["steps.1.output.new_items"]
        upstream = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"new_items": items},
        )
        context = {"task_name": "T", "steps": {"1": upstream}}

        async def fake_run_agent(**kwargs):
            yield SimpleNamespace(role="assistant", content="done", tool_results=None)

        ex = StepExecutor(make_scheduler())
        with (
            self._patched_loader(ex),
            patch("app.scheduler.execution.step_executor.async_session_factory") as factory,
            patch("app.scheduler.execution.step_executor.run_agent", side_effect=fake_run_agent),
        ):
            setup_db = MagicMock()
            setup_db.add = MagicMock()
            setup_db.commit = AsyncMock()
            setup_db.__aenter__ = AsyncMock(return_value=setup_db)
            setup_db.__aexit__ = AsyncMock(return_value=False)
            factory.return_value = setup_db

            result = await ex._exec_sub_agent_spawn(
                step, context, AsyncMock(), make_task(), make_task_run()
            )

        assert result.output["spawned"] == len(items)
        created = [call.args[0] for call in setup_db.add.call_args_list]
        assert len(created) == len(items)
        for sub_session in created:
            assert sub_session.metadata_[RESOLUTION_METADATA_KEY] == EXPECTED_RESOLUTION_ENTRY

    @pytest.mark.asyncio
    async def test_no_agent_definition_records_no_resolution_entry(self):
        """The entry names a source; with no definition there is no source to name."""
        scheduler = make_scheduler()
        ex = StepExecutor(scheduler)
        step = make_step(step_type="verification")

        with patch.object(
            ex, "_load_agent_for_step", new_callable=AsyncMock, return_value=(None, None, None)
        ):
            await ex._exec_verification(
                step, {"task_name": "T", "steps": {}}, AsyncMock(), make_task(), make_task_run()
            )

        metadata = scheduler._run_agent_for_task.call_args[1]["session_metadata"]
        assert RESOLUTION_METADATA_KEY not in metadata
