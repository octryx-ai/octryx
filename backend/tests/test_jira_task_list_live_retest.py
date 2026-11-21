"""Contract (re-test additions): C-1 in Knowledge, and L-a..L-e of the Jira task list.

Against the Server/DC handler (``jira_task_list_support``, which offers "Start Progress -> In Progress"):

- C-1 (Knowledge): a Jira connector filter with unbalanced parentheses or quotes is refused at configure, and
  the issue and release queries confine any stored filter inside the project clause;
- L-a: the preview checks the transitions Jira offers for the issue: the target status it would reach, or
  ``will_mutate_jira`` false with the offers when Jira does not offer the mapped one;
- L-b: after a write-back the item carries Jira's resulting status and the applied labels;
- L-c: a refused apply (409) is a ``transition_refused`` state event and an audit row;
- L-d: an intake ``status_state_mapping`` onto an unknown state is a coded 422;
- L-e: the dry-run sample shows the target state, the mapping source and the assignee's name.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog, WorkItem
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.jira import build_jql
from app.services.knowledge.sources.sync.jira_releases import release_jql
from tests.jira_intake_support import create_jira_intake, run_jira_intake, update_jira_intake
from tests.jira_task_list_support import DcJira, dc_config, dc_issue, use_transport, workspace_jira
from tests.test_jira_task_list_governance import _confined

API = "/api/v1/secure-work"
BREAKOUT = "project = BRD) OR (project = BRD"


def test_c1_knowledge_refuses_and_confines_a_breakout_filter():
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], jql=BREAKOUT)
    assert validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], jql='summary ~ "a (b"').scope["jql"]
    issues = build_jql(("OPS",), BREAKOUT).removesuffix(" ORDER BY created ASC, key ASC")
    assert _confined(issues, 'project in ("OPS")'), issues
    release = release_jql("OPS", "20002", BREAKOUT).removesuffix(" ORDER BY key ASC")
    assert _confined(release, 'project = "OPS" AND fixVersion = 20002'), release


async def _workflow(client, headers, project_id, mapping):
    response = await client.post(f"{API}/workflows", headers=headers, json={
        "name": f"flow-{uuid.uuid4().hex[:6]}", "project_id": project_id, "sync_policy": {"sync_mode": "execute"},
        "mappings": {"development": {**mapping, "sync_back": True}}})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _item(db, project_id, key) -> str:
    item = WorkItem(project_id=project_id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                    source_key=key, title=key, work_state="intake", sync_state="imported", source_status="Open")
    db.add(item)
    await db.commit()
    return item.id


async def _preview(client, headers, workflow_id, item_id) -> dict:
    dry = await client.post(f"{API}/workflows/{workflow_id}/dry-run-transition", headers=headers,
                            json={"work_item_id": item_id, "to_state": "development"})
    assert dry.status_code == 200, dry.text
    return dry.json()["preview"]["jira_sync_preview"]


async def test_la_lb_the_preview_knows_what_jira_offers_and_the_item_keeps_the_result(client, auth_headers, db, monkeypatch):
    jira = DcJira([])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    item_id = await _item(db, project_id, "OCX-1")

    offered = await _workflow(client, auth_headers, project_id, {"source_status": "In Progress", "labels": ["octryx-dev"]})
    preview = await _preview(client, auth_headers, offered, item_id)
    assert (preview["will_mutate_jira"], preview["transition_available"], preview["target_status"]) == (
        True, True, "In Progress")
    applied = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers, json={
        "workflow_id": offered, "to_state": "development", "effects_hash": preview["effects_hash"]})
    assert applied.status_code == 200, applied.text
    item = await db.get(WorkItem, item_id)
    await db.refresh(item)
    assert item.source_status == "In Progress" and "octryx-dev" in item.labels_json, "L-b: stored right away"

    missing = await _workflow(client, auth_headers, project_id, {"source_transition": "QA Sign-off"})
    other_id = await _item(db, project_id, "OCX-2")
    preview = await _preview(client, auth_headers, missing, other_id)
    assert (preview["will_mutate_jira"], preview["transition_available"], preview["effects"]) == (False, False, [])
    assert preview["offered_transitions"] == [{"name": "Start Progress", "to": "In Progress"}]


async def test_lc_a_refused_apply_is_on_the_timeline(client, auth_headers, db, monkeypatch):
    use_transport(monkeypatch, DcJira([]).transport())
    project_id = await workspace_jira(db, dc_config(None))
    workflow_id = await _workflow(client, auth_headers, project_id, {"source_transition": "QA Sign-off"})
    item_id = await _item(db, project_id, "OCX-3")
    preview = await _preview(client, auth_headers, workflow_id, item_id)
    refused = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers, json={
        "workflow_id": workflow_id, "to_state": "development", "effects_hash": preview["effects_hash"]})
    assert refused.status_code == 409 and "Jira offers" in str(refused.json()["detail"])
    stale = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers, json={
        "workflow_id": workflow_id, "to_state": "development", "effects_hash": "0" * 64})
    assert stale.status_code == 409

    events = (await client.get(f"{API}/work-items/{item_id}/state-events", headers=auth_headers)).json()["items"]
    refusals = [event for event in events if event["source"] == "transition_refused"]
    assert [event["jira_sync_preview"]["refusal"]["code"] for event in refusals] == ["preview_stale", "refused"]
    item = await db.get(WorkItem, item_id)
    await db.refresh(item)
    assert item.work_state == "intake", "a refusal changes nothing else"
    audits = (await db.execute(select(AuditLog).where(
        AuditLog.action == "secure_work.transition_refused", AuditLog.resource_id == item_id))).scalars().all()
    assert len(audits) == 2


async def test_ld_le_status_mapping_targets_and_the_dry_run_sample(client, auth_headers, db, monkeypatch):
    use_transport(monkeypatch, DcJira([dc_issue("OCX-1")]).transport())
    project_id = await workspace_jira(db, dc_config(None))
    with pytest.raises(HTTPException) as refused:
        await create_jira_intake(db, {
            "name": "bad", "project_id": project_id, "filters": {"project_keys": ["OCX"]},
            "sync_options": {"status_state_mapping": {"Open": "nowhere"}}})
    assert refused.value.status_code == 422 and refused.value.detail["code"] == "workflow_state_unknown"
    assert "nowhere" in refused.value.detail["message"]
    await db.rollback()

    created = await create_jira_intake(db, {
        "name": "ok", "project_id": project_id, "filters": {"project_keys": ["OCX"]},
        "sync_options": {"status_state_mapping": {"Open": "Ready For Plan"}}})
    with pytest.raises(HTTPException) as updated:
        await update_jira_intake(db, created["id"],
                                 {"sync_options": {"status_state_mapping": {"Open": "elsewhere"}}})
    assert updated.value.status_code == 422
    await db.rollback()

    run = await run_jira_intake(db, created["id"], dry_run=True)
    sample = run["items"][0]
    assert (sample["work_state"], sample["mapping_source"], sample["assignee_display"]) == (
        "ready_for_plan", "configured", "Jane Doe")
