"""Contract: references, pipeline config choice, global rows, masks, epic, userinfo.

Setting: an operator is a member of Workspace A only; Workspace B holds the foreign rows; one global row per
family exists. Through the real secure-work routers on an ASGI app, no network:

- every reference to a family row a handler reads (``config_id``, ``provider_config_id``, ``repository_profile_id``
  also nested in a change unit, ``pipeline_trace_id``) the caller may not see answers exactly like an id that names
  nothing (the same 404, ``services/secure_work/related_rows.py``); a row the caller sees must be global or of the
  item's Workspace, else 403;
- the item's pipeline view and the default pipeline choose only the item's Workspace's or global configs;
- each family's list shows own and global rows, global rows ``read_only``; secrets are masked for
  non-admins; global rows stay admin-only to change; an update seeds the stored ``project_id``;
- the ``change_unit_id`` body check, and Knowledge requesting ``project``;
- the intake masks a foreign ``epic_key``; userinfo hidden by whitespace or control characters.
"""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    UserProject,
    WorkCodingPipelineRun,
    WorkItem,
)
from app.services.tool_config.url_userinfo import carries_userinfo
from tests.egress_support import public_source_dns  # noqa: F401 - the fixture, used by name
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import DcJira, dc_config, dc_issue, use_transport, workspace_jira
from tests.secure_work_families_support import FAMILIES, world  # noqa: F401 - fixture

API = "/api/v1/secure-work"
# Coding policies, technology baselines and CI/CD providers have no routes (their rows stay for the world fixture).
ROUTED = [slug for slug in FAMILIES if slug not in ("coding-policies", "technology-baselines", "cicd-providers")]
# Repository profiles are read only (listed, never written).
READ_ONLY = ("repository-profiles",)


@pytest.mark.parametrize("slug", ROUTED)
async def test_c8f_each_family_lists_own_and_global_rows_and_seeds_project_on_update(world, slug):
    api, rows = world["api"], world["rows"][slug]
    listed = {row["name"]: row for row in (await api.get(f"{API}/{slug}")).json()["items"]}
    assert f"secret-{slug}" not in listed
    assert listed[f"own-{slug}"]["read_only"] is False and listed[f"global-{slug}"]["read_only"] is True
    if slug in READ_ONLY:
        return  # Read only (repository records in Settings)
    route = f"{API}/{slug}/{{}}".format(rows["global"].id)
    assert (await api.put(route, json={"name": "x"})).status_code == 403, "global rows stay admin-only to change"
    own = rows["a"]
    update = {"name": f"own-{slug}"}
    updated = await api.put(f"{API}/{slug}/{own.id}", json=update)
    assert updated.status_code == 200, updated.text
    assert updated.json()["project_id"] == world["a"], "an update never silently clears project_id"


@pytest.mark.parametrize(("key", "where"), [
    ("config_id", "pipeline-start"),
    ("provider_config_id", "trace"),
    ("provider_config_id", "finding"),
    ("repository_profile_id", "change-units-plan"),
    ("repository_profile_id", "trace"),
    ("pipeline_trace_id", "finding"),
    ("cicd_pipeline_trace_id", "finding"),
])
async def test_c8d_a_reference_to_another_workspaces_row_answers_like_a_missing_one(world, key, where):
    api, rows, item = world["api"], world["rows"], world["item_a"]
    foreign = {
        "config_id": rows["coding-pipelines"]["b"].id,
        "provider_config_id": rows["cicd-providers"]["b"].id,
        "repository_profile_id": rows["repository-profiles"]["b"].id,
        "pipeline_trace_id": world["trace_b"],
        "cicd_pipeline_trace_id": world["trace_b"],
        "cicd_build_id": world["build_b"],
    }[key]
    calls = {
        "pipeline-start": lambda body: api.post(f"{API}/work-items/{item}/coding-pipeline/start", json=body),
        "trace": lambda body: api.post(f"{API}/work-items/{item}/cicd-pipeline-traces", json=body),
        "finding": lambda body: api.post(f"{API}/work-items/{item}/cicd-findings", json={**body, "title": "x"}),
        "change-units-plan": lambda body: api.post(f"{API}/work-items/{item}/change-units/plan",
                                                   json={"units": [{**body, "repository_name": "r"}]}),
    }
    answers = [await calls[where]({key: value}) for value in (foreign, str(uuid.uuid4()))]
    assert answers[0].status_code == answers[1].status_code == 404, (key, where, answers[0].text)
    assert answers[0].json() == answers[1].json(), (key, where)


async def test_c8d_global_and_own_references_are_allowed_and_rows_stay_consistent_for_admins(world):
    api, rows, state, item = world["api"], world["rows"], world["state"], world["item_a"]
    route = f"{API}/work-items/{item}/change-units/plan"
    for ref in ("a", "global"):
        planned = await api.post(route, json={"units": [{"repository_profile_id": rows["repository-profiles"][ref].id}]})
        assert planned.status_code == 200, planned.text
    state["user"] = world["admin"]  # consistency holds for a platform admin too
    mixed = await api.post(route, json={"units": [{"repository_profile_id": rows["repository-profiles"]["b"].id}]})
    assert mixed.status_code == 403


async def test_c8d_item_bound_references_follow_the_item_even_for_a_member_of_both(world, db):
    """A reference is bound to the item's Workspace (not just the caller's), through the route and in the pipeline
    service on its own."""
    from fastapi import HTTPException

    from app.services.secure_work.coding.pipeline_config_choice import resolve_item_pipeline_config

    api, rows, item = world["api"], world["rows"], world["item_a"]
    db.add(UserProject(user_id=world["state"]["user"].id, project_id=world["b"], role="admin"))
    await db.commit()
    trace = await api.post(f"{API}/work-items/{item}/cicd-pipeline-traces",
                           json={"provider_config_id": rows["cicd-providers"]["b"].id})
    assert trace.status_code == 403
    viewer = world["state"]["user"]
    with pytest.raises(HTTPException) as refused:
        await resolve_item_pipeline_config(db, viewer, rows["coding-pipelines"]["b"].id, await db.get(WorkItem, item))
    assert refused.value.status_code == 403
    item_row = await db.get(WorkItem, item)
    assert (await resolve_item_pipeline_config(db, viewer, rows["coding-pipelines"]["global"].id, item_row)).id
    assert (await resolve_item_pipeline_config(db, viewer, None, item_row)).name == "own-coding-pipelines", \
        "own before global"


@pytest.mark.usefixtures("public_source_dns")  # the egress policy resolves the host: never real DNS
async def test_c8e_c8g_pipeline_choice_change_unit_and_knowledge_project_field(world, db):
    api, item = world["api"], world["item_a"]
    view = (await api.get(f"{API}/work-items/{item}/coding-pipeline")).json()
    names = {config["name"] for config in view["available_configs"]}
    assert names == {"own-coding-pipelines", "global-coding-pipelines"}
    db.add(WorkCodingPipelineRun(work_item_id=item, started_by=world["admin"].id))
    await db.commit()
    view = (await api.get(f"{API}/work-items/{item}/coding-pipeline")).json()
    assert view["run"] and {config["name"] for config in view["available_configs"]} == names
    started = await api.post(f"{API}/work-items/{item}/coding-pipeline/start", json={})
    assert started.status_code in (200, 422) and "secret-coding-pipelines" not in started.text

    from app.services.knowledge.sources.sync.jira import JiraConnector
    from tests.test_jira_cloud_source_sync import _connection
    from tests.test_jira_cloud_source_sync import _transport as cloud_transport

    seen: list[dict] = []
    await JiraConnector(_connection(), project_keys=("OPS",), transport=cloud_transport(seen)).list_items(None, limit=3)
    assert "project" in seen[-1]["body"]["fields"]


async def test_c1e_the_intake_masks_a_foreign_epic(client, auth_headers, db, monkeypatch):
    issue = dc_issue("OCX-1")
    issue["fields"]["customfield_10008"] = "SEC-1"
    use_transport(monkeypatch, DcJira([issue]).transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    intake = (await create_jira_intake(db, {
        "name": "epic", "project_id": project_id, "filters": {"project_keys": ["OCX"]}}))["id"]
    await run_jira_intake(db, intake)
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-1"))).scalar_one()
    assert item.epic_key is None


@pytest.mark.parametrize("url", ["ht\ttps://svc:pw-in-url@jira.example.test",
                                 "https:\t//svc:pw-in-url@jira.example.test", "https: //svc:pw-in-url@jira.example.test"])
def test_a1b_userinfo_hidden_by_whitespace_or_control_characters_counts_too(url):
    assert carries_userinfo(url)


@pytest.mark.parametrize("value", ["https://u:p\u200b@h.test", "https://u:p\uff20h.test",
                                   "ht\u200btps://u:p@h.test", "https:\u200b//u:p@h.test"])
def test_a1b_format_characters_and_full_width_at_signs_count_too(value):
    assert carries_userinfo(value)
    assert not carries_userinfo("https://h.test/path@x")
