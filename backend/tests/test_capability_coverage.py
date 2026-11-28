"""Every tool-dispatching path carries an explicit run capability."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.tools.registry as registry_module
from app.tools.capability_requirements import tool_required_capability
from app.tools.context import ToolContext
from app.tools.workflow_tools import StartWorkflowTool
from tests.scripted_pool_support import scripted_turns  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_turns")

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
WRITE_TOOL = "write_workspace_file"


def _context(state: dict | None, **extra) -> ToolContext:
    return ToolContext(
        user_id="u1", project_ids=[], roles=[], session_id="s1", project_config={}, run_capability=state, **extra
    )


def _state(capability_class: str | None, source: str = "test") -> dict:
    return {"class": capability_class, "enforced": True, "source": source, "escalation_decision": None}


@pytest.fixture
def dispatched(monkeypatch):
    calls: list[str] = []

    async def fake_dispatch(tool_name, params, context):
        calls.append(tool_name)
        return {"ok": True}

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", fake_dispatch)
    return calls










async def test_start_workflow_only_proposes_and_never_starts_a_registry_family():
    # The code-registry contract families are no workflows; start_workflow never starts anything.
    tool = StartWorkflowTool()
    params = {"reason": "the user asked for it"}
    for workflow_id in ("generic_document", "coding_change_tdd", "knowledge_request"):
        refused = await tool.execute({**params, "workflow_id": workflow_id}, _context(_state("read_only")))
        assert (refused["status"], refused["reason"]) == ("needs_clarification", "unknown_key")


def test_every_tool_context_in_the_app_carries_a_run_capability_and_workspace_select_is_deliver():
    missing = []
    for path in APP_ROOT.rglob("*.py"):
        if path.name == "context.py" and path.parent.name == "tools":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ToolContext":
                if "run_capability" not in {keyword.arg for keyword in node.keywords}:
                    missing.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert missing == []
    # Terraform ``workspace new`` creates state in the remote backend: an external write.
    assert tool_required_capability("workspace_select") == "deliver"
