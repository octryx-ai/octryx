"""A workflow a pull request starts (its Start box says ``started_by: pull_request``) is not offered where a person
starts a run for a Work item: the start dialog, the routing of a Work item type and the app all read the startable
list (the rule lives in the definition, not in a list of keys)."""

from __future__ import annotations

import copy

from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.run_start import startable_workflows_for
from app.services.workflow_runs.start_trigger import started_by
from tests.phased_workflow_fixtures import phased_definition, publish_phased


def _started_by(value: str) -> dict:
    definition = phased_definition()
    definition["nodes"][0] = {**definition["nodes"][0], "config": {"started_by": value}}
    return definition


async def test_a_flow_whose_start_box_names_a_pull_request_is_not_startable_for_a_work_item(db):
    own = await publish_phased(db, phased_definition())
    by_pull_request = await publish_phased(db, _started_by("pull_request"))
    by_work_item = await publish_phased(db, _started_by("work_item"))
    keys = {item["key"] for item in await startable_workflows_for(db, project_id=None)}
    assert own in keys and by_work_item in keys
    assert by_pull_request not in keys  # its key is nothing special: the definition says it
    from app.services.workflow_routing.model_catalog import build_model_workflow_catalog

    offered = {entry["workflow_key"] for entry in await build_model_workflow_catalog(db)}
    assert own in offered and by_pull_request not in offered  # nor offered to the model in a chat


async def test_the_shipped_pr_workflows_say_so_and_every_other_shipped_workflow_starts_from_a_work_item(db):
    from app.services.workflow_runs.seeding import phased_seeds, seed_phased_workflows
    from tests.phased_workflow_fixtures import admin_user

    seeds = {seed["key"]: started_by(seed["definition"]) for seed in phased_seeds()}
    assert {key for key, value in seeds.items() if value == "pull_request"} == {
        "pr-review-bot", "pr-review-explain", "pr-fix"}
    await seed_phased_workflows(db, admin_user=await admin_user(db))
    keys = {item["key"] for item in await startable_workflows_for(db, project_id=None)}
    assert not keys & {"pr-review-bot", "pr-review-explain", "pr-fix"}
    assert {"bug-fix-reproduction", "epic-delivery", "spec-writing"} <= keys


def test_an_unknown_start_trigger_is_a_validation_error_and_reads_as_a_work_item():
    definition = _started_by("webhook")
    report = validate_flow_definition(copy.deepcopy(definition))
    assert not report["valid"]
    assert [error["code"] for error in report["errors"]] == ["start_trigger_invalid"]
    assert started_by(definition) == "work_item" and started_by(phased_definition()) == "work_item"
    assert validate_flow_definition(_started_by("pull_request"))["valid"]
