"""Contract (C-1..C-7): the Jira task list never leaves its Workspace's governance."""

# ruff: noqa: F811  (the shared ``scoped_api`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project, WorkItem
from app.services.secure_work.jira.jira_scope import restrict_jql
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_helpers_jql import _inject_project_restriction
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import (  # noqa: F401 - scoped_api is a fixture
    DcJira,
    _operator,
    dc_config,
    dc_issue,
    scoped_api,
    use_transport,
    workspace_jira,
)

API = "/api/v1/secure-work"
MAPPING = {"development": {"source_transition": "Start Progress", "labels": ["octryx-work"], "sync_back": True}}


def _confined(out: str, clause: str) -> bool:
    tail = out[len(clause) + len(" AND "):]
    depth, quote = 0, None
    for index, char in enumerate(tail):
        if quote:
            quote = None if char == quote else quote
            continue
        if char in "\"'":
            quote = char
        depth += {"(": 1, ")": -1}.get(char, 0) if not quote else 0
        if depth == 0:
            rest = tail[index + 1:].strip()
            return not rest or (rest.upper().startswith("ORDER BY") and not any(c in rest for c in "()"))
    return False


@pytest.mark.parametrize("jql", [
    "project = OCX) OR (project = OPS",
    'summary ~ "a ) OR (b" OR project = OPS',
    "summary ~ 'x) OR (y' ORDER BY created",
    'project = OCX ORDER BY created DESC',
    "(project = OCX ORDER BY created) OR project = OPS",
])
def test_c1_custom_jql_never_leaves_the_project_clause(jql):
    for out, clause in ((restrict_jql(jql, frozenset({"OCX"})), "project in (OCX)"),
                        (_inject_project_restriction(jql, ["OCX"]), 'project in ("OCX")')):
        assert out.startswith(f"{clause} AND (") and _confined(out, clause), out
    assert '"order by"' in restrict_jql('summary ~ "order by" AND project = OCX', frozenset({"OCX"}))


async def test_c1_an_unbalanced_jql_is_never_sent(client, auth_headers, db, monkeypatch):
    jira = DcJira([dc_issue("OCX-1")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    created = await create_jira_intake(db, {
        "name": "inj", "project_id": project_id, "filters": {"jql": "project = OCX) OR (project = OPS"}})
    run = await run_jira_intake(db, created["id"], dry_run=True)
    assert run["sync_run"]["status"] == "blocked"
    assert run["sync_run"]["summary"]["block_reason"] == "jql_unbalanced"
    assert not [request for request in jira.requests if request["path"].endswith("/search")]

    context = ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1",
                          project_config=dc_config(["OCX"]), capability_type="change", agent_mode_key="change",
                          workspace_root="/tmp")
    result = await SearchJiraTickets().execute({"jql": "project = OCX) OR (project = OPS"}, context)
    assert result["code"] == "jql_unbalanced" and len(jira.requests) == 0


async def test_c2_an_issue_key_decides_its_project(client, auth_headers, db, monkeypatch):
    use_transport(monkeypatch, DcJira([]).transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    # A JQL filter (not project_keys), so only the allowlist check decides.
    created = await create_jira_intake(db, {
        "name": "push", "project_id": project_id, "filters": {"jql": "updated > -1d"}})
    unkeyed = {**dc_issue("OCX-6", project="OCX"), "key": "not-an-issue-key"}
    await run_jira_intake(db, created["id"], {"issues": [
        dc_issue("OPS-9", project="OCX"), dc_issue("OCX-8", project="OPS"), unkeyed, dc_issue("OCX-7")]})
    keys = {row.source_key for row in (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars()}
    assert keys == {"OCX-7"}
    stored = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-7"))).scalar_one()
    assert "comment" not in stored.source_fields_json["raw"]["fields"], "C-6: the raw comment container is not kept"
    assert stored.source_fields_json["comments"], "the bounded comments stay"


async def _workflow(client, headers, project_id, *, mappings=None):
    response = await client.post(f"{API}/workflows", headers=headers, json={
        "name": f"flow-{uuid.uuid4().hex[:6]}", "project_id": project_id, "sync_policy": {"sync_mode": "execute"},
        "mappings": MAPPING if mappings is None else mappings})
    assert response.status_code == 200, response.text
    return response.json()


async def _item(db, project_id, key) -> str:
    item = WorkItem(project_id=project_id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                    source_key=key, title=key, work_state="intake", sync_state="imported")
    db.add(item)
    await db.commit()
    return item.id


async def _preview(client, headers, workflow_id, item_id) -> dict:
    dry = await client.post(f"{API}/workflows/{workflow_id}/dry-run-transition", headers=headers,
                            json={"work_item_id": item_id, "to_state": "development"})
    return dry


async def _apply(client, headers, workflow_id, item_id, effects_hash):
    return await client.post(f"{API}/work-items/{item_id}/transition", headers=headers, json={
        "workflow_id": workflow_id, "to_state": "development", "effects_hash": effects_hash})


async def test_c2_no_jira_request_for_an_issue_outside_the_allowlist(client, auth_headers, db, monkeypatch):
    jira = DcJira([])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    workflow = await _workflow(client, auth_headers, project_id)
    outside = await _item(db, project_id, "OPS-9")
    preview = (await _preview(client, auth_headers, workflow["id"], outside)).json()["preview"]["jira_sync_preview"]
    refused = await _apply(client, auth_headers, workflow["id"], outside, preview["effects_hash"])
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "scope_not_allowed"
    assert jira.requests == [], "not even the read-only transition lookup"

    inside = await _item(db, project_id, "OCX-1")
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.project_id == project_id, BuiltInToolConfig.tool_name == "jira"))).scalar_one()
    entry.config = {**entry.config, "jira_allowed_projects": ["BRD"]}
    await db.commit()
    preview = (await _preview(client, auth_headers, workflow["id"], inside)).json()["preview"]["jira_sync_preview"]
    refused = await _apply(client, auth_headers, workflow["id"], inside, preview["effects_hash"])
    assert refused.status_code == 409 and jira.requests == []


async def test_c3_c5_c7_inactive_workflows_normalized_keys_and_bound_previews(client, auth_headers, db, monkeypatch):
    jira = DcJira([])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    cased = await _workflow(client, auth_headers, project_id,
                            mappings={"Development": {"source_transition": "Start Progress", "sync_back": True}})
    assert cased["mappings"]["development"]["sync_back"] is True, "C-5: normalized, never dropped"

    workflow = await _workflow(client, auth_headers, project_id)
    item_id = await _item(db, project_id, "OCX-2")
    preview = (await _preview(client, auth_headers, workflow["id"], item_id)).json()["preview"]["jira_sync_preview"]
    for stale in (None, "0" * 64):
        refused = await _apply(client, auth_headers, workflow["id"], item_id, stale)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "preview_stale"
    await client.put(f"{API}/workflows/{workflow['id']}", headers=auth_headers, json={
        "mappings": {"development": {"source_transition": "Start Progress", "labels": ["other"], "sync_back": True}}})
    stale = await _apply(client, auth_headers, workflow["id"], item_id, preview["effects_hash"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "preview_stale"
    assert not [r for r in jira.requests if r["method"] in ("POST", "PUT")], "nothing written for a stale preview"

    fresh = (await _preview(client, auth_headers, workflow["id"], item_id)).json()["preview"]["jira_sync_preview"]
    # Any change of the workflow (even one that keeps the effects) makes the confirmed preview stale.
    await client.put(f"{API}/workflows/{workflow['id']}", headers=auth_headers, json={"description": "renamed"})
    renamed = await _apply(client, auth_headers, workflow["id"], item_id, fresh["effects_hash"])
    assert renamed.status_code == 409 and renamed.json()["detail"]["code"] == "preview_stale"
    fresh = (await _preview(client, auth_headers, workflow["id"], item_id)).json()["preview"]["jira_sync_preview"]
    assert (await _apply(client, auth_headers, workflow["id"], item_id, fresh["effects_hash"])).status_code == 200

    await client.post(f"{API}/workflows/{workflow['id']}/deactivate", headers=auth_headers)
    assert (await _preview(client, auth_headers, workflow["id"], item_id)).status_code == 409
    inactive = await _apply(client, auth_headers, workflow["id"], item_id, fresh["effects_hash"])
    assert inactive.status_code == 409 and inactive.json()["detail"]["code"] == "workflow_inactive"


class _LabelsRefused(DcJira):
    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            self.requests.append({"method": "PUT", "path": request.url.path})
            return httpx.Response(400, json={"errorMessages": ["labels refused"]})
        return super().handler(request)


async def test_c6_labels_come_after_the_transition_and_never_undo_it(client, auth_headers, db, monkeypatch):
    jira = _LabelsRefused([])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    workflow = await _workflow(client, auth_headers, project_id)
    item_id = await _item(db, project_id, "OCX-3")
    preview = (await _preview(client, auth_headers, workflow["id"], item_id)).json()["preview"]["jira_sync_preview"]
    applied = await _apply(client, auth_headers, workflow["id"], item_id, preview["effects_hash"])
    assert applied.status_code == 200 and applied.json()["work_state"] == "development"
    execution = applied.json()["preview"]["jira_sync_preview"]["execution"]
    assert (execution["labels_applied"], execution["labels_failed"]) == ([], True)
    writes = [r["method"] + " " + r["path"].rsplit("/", 1)[-1] for r in jira.requests if r["method"] in ("POST", "PUT")]
    assert writes == ["POST transitions", "PUT OCX-3"], "labels only after the transition"


async def test_c4_an_operator_outside_the_workspace_is_refused(scoped_api, client, auth_headers, db, monkeypatch):
    api, state = scoped_api
    use_transport(monkeypatch, DcJira([]).transport())
    project_id = await workspace_jira(db, dc_config(None))
    workflow = await _workflow(client, auth_headers, project_id)
    item_id = await _item(db, project_id, "OCX-4")
    state["user"] = await _operator(db)
    route = f"{API}/workflows/{workflow['id']}"
    # Another Workspace's workflow answers like a missing one.
    assert (await api.put(route, json={"sync_policy": {"sync_mode": "dry_run_only"}})).status_code == 404
    assert (await api.post(f"{route}/deactivate")).status_code == 404
    assert (await api.post(f"{route}/activate")).status_code == 404
    assert (await api.get(f"{API}/workflows?project_id={project_id}")).status_code == 403
    listed = (await api.get(f"{API}/workflows")).json()["items"]
    assert workflow["id"] not in {row["id"] for row in listed}
    assert (await api.post(f"{API}/workflows", json={"name": "x", "project_id": project_id})).status_code == 403
    assert (await api.post(f"{API}/workflows", json={"name": "global"})).status_code == 403
    dry = await api.post(f"{route}/dry-run-transition", json={"work_item_id": item_id, "to_state": "development"})
    assert dry.status_code == 404

    other = Project(name=f"other-{uuid.uuid4().hex[:6]}")
    db.add(other)
    await db.commit()
    foreign = await _workflow(client, auth_headers, other.id)
    mismatch = await _preview(client, auth_headers, foreign["id"], item_id)
    assert mismatch.status_code == 409 and mismatch.json()["detail"]["code"] == "workflow_project_mismatch"
