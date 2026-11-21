"""Contract (B-5, B-6): the write-back preview tells the truth, and workflows have a lifecycle.

Through the real secure-work routes against the Server/DC handler and the Cloud stub (``jira_task_list_support``):

- B-5: in execute mode with ``sync_back`` the preview says ``will_mutate_jira`` and lists the exact effects
  (status, rendered comment, labels); applying writes exactly those, labels included (v2 on DC, v3 on Cloud);
  a dry-run workflow writes nothing and lists no effect;
- B-6: a workflow can be updated, deactivated and activated again; a mapping or a transition naming an unknown
  state is a coded 422, also when an update removes a state a stored mapping still writes for.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import WorkItem
from tests.jira_task_list_support import DcJira, cloud_config, cloud_transport, dc_config, use_transport, workspace_jira

API = "/api/v1/secure-work"
MAPPING = {"development": {"source_transition": "Start Progress", "comment_template": "{source_key} moved to {to_state}",
                           "labels": ["octryx-dev"], "sync_back": True}}


async def _workflow(client, headers, project_id: str, *, mode: str, mappings: dict | None = None):
    return await client.post(f"{API}/workflows", headers=headers, json={
        "name": f"flow-{uuid.uuid4().hex[:6]}", "project_id": project_id,
        "mappings": MAPPING if mappings is None else mappings, "sync_policy": {"sync_mode": mode}})


async def _item(db, project_id: str, key: str) -> str:
    item = WorkItem(project_id=project_id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                    source_key=key, title=key, work_state="intake", sync_state="imported")
    db.add(item)
    await db.commit()
    return item.id


@pytest.mark.parametrize("flavour", ["dc", "cloud"])
async def test_b5_the_preview_lists_exactly_what_the_apply_writes(client, auth_headers, db, monkeypatch, flavour):
    seen: list[dict] = []
    if flavour == "dc":
        jira = DcJira([])
        use_transport(monkeypatch, jira.transport())
        project_id = await workspace_jira(db, dc_config(None))
        key, requests = "OCX-1", jira.requests
    else:
        use_transport(monkeypatch, cloud_transport(seen))
        project_id = await workspace_jira(db, cloud_config(None))
        key, requests = "OPS-1", seen
    workflow = (await _workflow(client, auth_headers, project_id, mode="execute")).json()
    item_id = await _item(db, project_id, key)

    dry = await client.post(f"{API}/workflows/{workflow['id']}/dry-run-transition", headers=auth_headers,
                            json={"work_item_id": item_id, "to_state": "development"})
    preview = dry.json()["preview"]["jira_sync_preview"]
    assert preview["will_mutate_jira"] is True
    # C-7: the target status is resolved read-only from the issue's transitions and bound by the hash.
    assert preview["effects"] == [
        {"kind": "status", "value": "In Progress", "transition": "Start Progress", "target_status": "In Progress"},
        {"kind": "comment", "value": f"{key} moved to development"},
        {"kind": "labels", "value": ["octryx-dev"]},
    ]
    assert preview["target_status_resolved"] is True and len(preview["effects_hash"]) == 64
    applied = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers,
                                json={"workflow_id": workflow["id"], "to_state": "development",
                                      "effects_hash": preview["effects_hash"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["preview"]["jira_sync_preview"]["execution"]["labels_applied"] == ["octryx-dev"]
    version = "2" if flavour == "dc" else "3"
    updates = [r for r in requests if r["method"] == "PUT" and r["path"] == f"/rest/api/{version}/issue/{key}"]
    assert updates and updates[0]["body"]["update"] == {"labels": [{"add": "octryx-dev"}]}
    assert any(r["method"] == "POST" and r["path"].endswith("/transitions") for r in requests)


async def test_b5_a_dry_run_workflow_promises_no_jira_write(client, auth_headers, db, monkeypatch):
    jira = DcJira([])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    workflow = (await _workflow(client, auth_headers, project_id, mode="dry_run_only")).json()
    item_id = await _item(db, project_id, "OCX-2")
    dry = await client.post(f"{API}/workflows/{workflow['id']}/dry-run-transition", headers=auth_headers,
                            json={"work_item_id": item_id, "to_state": "development"})
    preview = dry.json()["preview"]["jira_sync_preview"]
    assert (preview["will_mutate_jira"], preview["effects"]) == (False, [])
    applied = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers,
                                json={"workflow_id": workflow["id"], "to_state": "development",
                                      "effects_hash": preview["effects_hash"]})
    assert applied.status_code == 200 and jira.requests == []


async def test_b6_update_deactivate_activate_and_coded_unknown_states(client, auth_headers, db):
    project_id = await workspace_jira(db, dc_config(None))
    unknown = await _workflow(client, auth_headers, project_id, mode="dry_run_only",
                              mappings={"in_progresss": {"labels": ["x"]}})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "workflow_state_unknown"
    assert "in_progresss" in unknown.json()["detail"]["message"] and "development" in unknown.json()["detail"]["states"]

    workflow = (await _workflow(client, auth_headers, project_id, mode="dry_run_only")).json()
    route = f"{API}/workflows/{workflow['id']}"
    updated = await client.put(route, headers=auth_headers, json={"name": "Standard flow", "description": "edited",
                                                                  "sync_policy": {"sync_mode": "execute"}})
    assert updated.status_code == 200, updated.text
    assert (updated.json()["name"], updated.json()["sync_policy"]["sync_mode"]) == ("Standard flow", "execute")
    assert updated.json()["mappings"]["development"]["labels"] == ["octryx-dev"], "untouched mappings stay"

    removing = await client.put(route, headers=auth_headers, json={"states": ["intake", "done"]})
    assert removing.status_code == 422 and "development" in removing.json()["detail"]["message"]
    bad_mapping = await client.put(route, headers=auth_headers, json={"mappings": {"nowhere": {"sync_back": True}}})
    assert bad_mapping.status_code == 422 and bad_mapping.json()["detail"]["code"] == "workflow_state_unknown"

    item_id = await _item(db, project_id, "OCX-3")
    transition = await client.post(f"{API}/work-items/{item_id}/transition", headers=auth_headers,
                                   json={"workflow_id": workflow["id"], "to_state": "nowhere"})
    assert transition.status_code == 422 and transition.json()["detail"]["code"] == "workflow_state_unknown"

    off = await client.post(f"{route}/deactivate", headers=auth_headers)
    assert off.status_code == 200 and off.json()["is_active"] is False
    listed = (await client.get(f"{API}/workflows?project_id={project_id}", headers=auth_headers)).json()["items"]
    assert workflow["id"] not in {row["id"] for row in listed}
    on = await client.post(f"{route}/activate", headers=auth_headers)
    assert on.status_code == 200 and on.json()["is_active"] is True
