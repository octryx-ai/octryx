"""A field condition is validated, routes on the run's work item, fails a run without one visibly, and the catalog lists the work item fields and the newest test run's result."""

from __future__ import annotations

import uuid

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.work_item_fields import work_item_fields
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_designer_d2b2_support import _codes, _edge, _outcome

pytestmark = pytest.mark.usefixtures("scripted_pool")


def field_definition(*, field: str = "type", operator: str = "is", value=None, edges: list[dict] | None = None):
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "cond", "type": "decision", "config": {"check": "field", "field": field,
                                                                "operator": operator,
                                                                "value": "Bug" if value is None else value}},
                  _outcome("yes_end", "done"), _outcome("no_end", "blocked")],
        "edges": edges if edges is not None else [
            _edge("e0", "start", "cond"), _edge("y", "cond", "yes_end", "yes"), _edge("n", "cond", "no_end", "no")],
    }


async def _item(db, workspace_id: str, **fields) -> WorkItem:
    item = WorkItem(project_id=workspace_id, source_type="jira", source_instance="test",
                    source_key=f"D2-{uuid.uuid4().hex[:6]}", title="Checkout fails", **fields)
    db.add(item)
    await db.flush()
    return item


# --- 3. field conditions ------------------------------------------------------------------------------------------

def test_a_field_condition_is_validated():
    assert validate_flow_definition(field_definition())["valid"] is True
    assert "decision_field" in _codes(field_definition(field="mood"))
    assert "decision_operator" in _codes(field_definition(operator="greater_than"))
    assert "decision_operator" in _codes(field_definition(field="labels", operator="is"))
    assert "decision_value" in _codes(field_definition(value=""))
    assert "decision_value" in _codes(field_definition(field="test_result", value="green"))
    one_route = field_definition(edges=[_edge("e0", "start", "cond"), _edge("y", "cond", "yes_end", "yes")])
    assert "decision_unrouted" in _codes(one_route)
    with_otherwise = field_definition(edges=[_edge("e0", "start", "cond"), _edge("y", "cond", "yes_end", "yes"),
                                             _edge("n", "cond", "no_end", "otherwise")])
    assert "unknown_route" in _codes(with_otherwise)


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "operator", "value", "expected"), [
    ("type", "is", "bug", "done"),  # text compares ignore case
    ("type", "is_not", "Bug", "blocked"),
    ("labels", "contains", "Regression", "done"),
    ("labels", "contains", "ui", "blocked"),
    ("assignee", "contains", "ANNA@", "done"),
    ("priority", "is", "High", "blocked"),
])
async def test_a_field_condition_routes_on_the_work_item(db, field, operator, value, expected):
    admin = await admin_user(db)
    workspace_id = await seed_workspace(db)
    item = await _item(db, workspace_id, issue_type="Bug", priority="Low", labels_json=["regression"],
                       assignee="anna@example.com")
    key = await publish_phased(db, field_definition(field=field, operator=operator, value=value))
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, work_item_id=item.id)
    assert (run.status, run.outcome) == ("completed", expected)
    assert run.context["results"]["cond"] == ("yes" if expected == "done" else "no")


@pytest.mark.asyncio
async def test_a_field_condition_without_a_work_item_fails_the_run_visibly(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, field_definition()),
                          project_id=workspace_id)
    assert run.status == "failed" and "has no work item" in run.last_error


@pytest.mark.asyncio
async def test_the_test_result_reads_the_runs_newest_test_run(db):
    from app.services.workflow_runs.work_item_fields import FIELDS_BY_KEY, compare, field_value

    class Run:
        context = {"tests": {"runs": [{"all_green": False}, {"all_green": True}]}}

    field = FIELDS_BY_KEY["test_result"]
    assert field_value(field, Run(), None) == "passed"
    assert compare(field, "is", "passed", "passed") and not compare(field, "is", None, "passed")


@pytest.mark.asyncio
async def test_work_item_fields_for_the_catalog(db):
    workspace_id = await seed_workspace(db)
    await _item(db, workspace_id, issue_type="Bug", priority="High", source_status="In Progress")
    await _item(db, workspace_id, issue_type="Story")
    fields = {entry["key"]: entry for entry in await work_item_fields(db, project_id=workspace_id)}
    assert set(fields) == {"type", "priority", "status", "labels", "components", "assignee", "test_result"}
    assert fields["type"] == {"key": "type", "label": "Type", "kind": "enum", "values": ["Bug", "Story"]}
    assert fields["status"]["values"] == ["In Progress"]
    assert fields["labels"]["kind"] == "list" and "values" not in fields["labels"]
    assert fields["test_result"]["values"] == ["passed", "failed"]
    # Without data (or a session) an enum offers no values: the designer takes free text.
    assert "values" not in {entry["key"]: entry for entry in await work_item_fields()}["type"]
