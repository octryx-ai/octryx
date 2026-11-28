"""Step deduplication, field resolution, template rendering and prompt building in the StepExecutor."""

from __future__ import annotations

from app.scheduler.execution.step_executor import StepExecutor, StepResult
from tests.step_executor_support import make_scheduler, make_step, make_task


class TestDeduplication:
    def _make_executor(self) -> StepExecutor:
        return StepExecutor(make_scheduler())

    def test_all_new_items_pass_through(self):
        ex = self._make_executor()
        task = make_task(config={})
        items = [
            {"key": "TICKET-1", "updated": "2026-01-01"},
            {"key": "TICKET-2", "updated": "2026-01-02"},
        ]
        new_items, state_update = ex._deduplicate_items(items, task)
        assert len(new_items) == 2
        assert state_update == {"TICKET-1": "2026-01-01", "TICKET-2": "2026-01-02"}

    def test_known_items_filtered_out(self):
        ex = self._make_executor()
        task = make_task(config={"_items_state": {"TICKET-1": "2026-01-01"}})
        items = [
            {"key": "TICKET-1", "updated": "2026-01-01"},
            {"key": "TICKET-2", "updated": "2026-01-02"},
        ]
        new_items, state_update = ex._deduplicate_items(items, task)
        assert len(new_items) == 1
        assert new_items[0]["key"] == "TICKET-2"
        assert "TICKET-1" not in state_update

    def test_updated_timestamp_passes_through(self):
        ex = self._make_executor()
        task = make_task(config={"_items_state": {"TICKET-1": "2026-01-01"}})
        items = [{"key": "TICKET-1", "updated": "2026-02-01"}]
        new_items, state_update = ex._deduplicate_items(items, task)
        assert len(new_items) == 1
        assert state_update["TICKET-1"] == "2026-02-01"

    def test_empty_input_returns_empty(self):
        ex = self._make_executor()
        task = make_task(config={})
        new_items, state_update = ex._deduplicate_items([], task)
        assert new_items == []
        assert state_update == {}


class TestFieldResolution:
    def _ex(self) -> StepExecutor:
        return StepExecutor(make_scheduler())

    def test_simple_key(self):
        ex = self._ex()
        assert ex._resolve_field("task_name", {"task_name": "Otto"}) == "Otto"

    def test_nested_dot_path(self):
        ex = self._ex()
        context = {
            "steps": {
                "1": StepResult(
                    step_id="x",
                    position=1,
                    name="s",
                    step_type="analysis",
                    status="success",
                    output={"results": [1, 2, 3]},
                )
            }
        }
        val = ex._resolve_field("steps.1.output.results", context)
        assert val == [1, 2, 3]

    def test_missing_path_returns_none(self):
        ex = self._ex()
        assert ex._resolve_field("steps.99.output.foo", {"steps": {}}) is None

    def test_step_result_attribute(self):
        ex = self._ex()
        sr = StepResult(step_id="x", position=2, name="s", step_type="analysis", status="success", output={"k": "v"})
        context = {"steps": {"2": sr}}
        assert ex._resolve_field("steps.2.status", context) == "success"

    def test_list_index_resolution(self):
        ex = self._ex()
        items = [{"key": "ACME-412", "summary": "Fix X"}]
        sr = StepResult(
            step_id="x",
            position=1,
            name="fetch",
            step_type="connector_fetch",
            status="success",
            output={"new_items": items},
        )
        context = {"steps": {"1": sr}}
        assert ex._resolve_field("steps.1.output.new_items.0.key", context) == "ACME-412"

    def test_list_index_out_of_bounds_returns_none(self):
        ex = self._ex()
        sr = StepResult(
            step_id="x",
            position=1,
            name="fetch",
            step_type="connector_fetch",
            status="success",
            output={"items": [{"k": "v"}]},
        )
        context = {"steps": {"1": sr}}
        assert ex._resolve_field("steps.1.output.items.5.k", context) is None


class TestTemplateRendering:
    def _ex(self) -> StepExecutor:
        return StepExecutor(make_scheduler())

    def test_renders_placeholder(self):
        ex = self._ex()
        sr = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"ticket_id": "JIRA-42"},
        )
        context = {"steps": {"1": sr}}
        result = ex._render_template_str("Process ticket {{steps.1.output.ticket_id}}", context)
        assert result == "Process ticket JIRA-42"

    def test_unknown_placeholder_kept(self):
        ex = self._ex()
        result = ex._render_template_str("Hello {{missing.field}}", {})
        assert "{{missing.field}}" in result

    def test_render_params_dict(self):
        ex = self._ex()
        sr = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"jql": "project=OCX"},
        )
        context = {"steps": {"1": sr}}
        params = {"query": "{{steps.1.output.jql}}", "limit": 10}
        rendered = ex._render_template_params(params, context)
        assert rendered["query"] == "project=OCX"
        assert rendered["limit"] == 10

    def test_render_params_preserves_exact_reference_types(self):
        ex = self._ex()
        sr = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"changed_silver_ids": ["silver-1", "silver-2"]},
        )
        context = {"steps": {"1": sr}}
        params = {
            "silver_ids": "{{steps.1.output.changed_silver_ids}}",
            "nested": {"ids": "{{steps.1.output.changed_silver_ids}}"},
        }
        rendered = ex._render_template_params(params, context)
        assert rendered["silver_ids"] == ["silver-1", "silver-2"]
        assert rendered["nested"]["ids"] == ["silver-1", "silver-2"]


class TestPromptBuilding:
    def _ex(self) -> StepExecutor:
        return StepExecutor(make_scheduler())

    def test_basic_prompt_contains_step_name(self):
        ex = self._ex()
        step = make_step(name="Analysiere", instructions="Read the ticket.")
        prompt = ex._build_step_prompt(step, {"task_name": "Otto", "steps": {}})
        assert "Analysiere" in prompt
        assert "Read the ticket." in prompt
        assert "Otto" in prompt

    def test_context_fields_injected(self):
        ex = self._ex()
        sr = StepResult(
            step_id="x",
            position=1,
            name="s",
            step_type="connector_fetch",
            status="success",
            output={"ticket_id": "JIRA-1"},
        )
        context = {"task_name": "T", "steps": {"1": sr}}
        step = make_step(
            position=2,
            context_fields_json='["steps.1.output.ticket_id"]',
        )
        step.context_fields = ["steps.1.output.ticket_id"]
        prompt = ex._build_step_prompt(step, context)
        assert "JIRA-1" in prompt

    def test_item_appended_when_provided(self):
        ex = self._ex()
        step = make_step()
        prompt = ex._build_step_prompt(step, {"task_name": "T", "steps": {}}, item={"key": "JIRA-5"})
        assert "JIRA-5" in prompt
