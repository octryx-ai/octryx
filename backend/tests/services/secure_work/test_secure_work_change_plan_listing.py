"""Cross-item Change Plan list and scoped Work Item detail, with the router on its own app and role and
workspace checks against the database."""

from __future__ import annotations

import pytest

from app.services.secure_work.serializers import serialize_work_item
from app.services.secure_work.work_item_close import close_preview
from tests.services.secure_work.secure_work_change_plan_listing_support import (  # noqa: F401
    URL,
    _admin,
    _item,
    _plan,
    _project,
    _user,
    plan_api,
)


async def _two_workspaces(db):
    admin = await _admin(db)
    project_a = await _project(db, "Plans A")
    project_b = await _project(db, "Plans B")
    item_a = await _item(db, "OCX-1", project_a.id)
    item_a2 = await _item(db, "OCX-2", project_a.id)
    item_b = await _item(db, "OPS-1", project_b.id)
    item_none = await _item(db, "WEB-1", None)
    plans = {
        "a_v1_approved": await _plan(db, item_a, admin, version=1, status="approved", minutes=1,
                                     evidence={"plan_type": "coding_change"}, acceptance_criteria=["a", "b"]),
        "a_v2_ready": await _plan(db, item_a, admin, version=2, status="ready_for_review", minutes=5,
                                  change_units=[{"id": "u1"}, {"id": "u2"}, {"id": "u3"}]),
        "a2_v1_superseded": await _plan(db, item_a2, admin, version=1, status="superseded", minutes=2),
        "a2_v2_clarify": await _plan(db, item_a2, admin, version=2, status="needs_clarification", minutes=6,
                                     open_questions=["Which tenant?"]),
        "a2_v3_draft": await _plan(db, item_a2, admin, version=3, status="draft", minutes=7),
        "b_v1_ready": await _plan(db, item_b, admin, version=1, status="ready_for_review", minutes=8),
        "none_v1_rejected": await _plan(db, item_none, admin, version=1, status="rejected", minutes=9),
    }
    return {"admin": admin, "a": project_a, "b": project_b, "item_a": item_a, "item_b": item_b,
            "item_none": item_none, "plans": plans}


@pytest.mark.asyncio
async def test_empty_list_has_no_rows_and_zero_counts(db, plan_api):  # noqa: F811
    client, state = plan_api
    state["user"] = await _admin(db)
    response = await client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == [] and body["next_cursor"] is None
    assert body["status_counts"] == {
        "approved": 0, "draft": 0, "needs_clarification": 0, "ready_for_review": 0, "rejected": 0,
    }


@pytest.mark.asyncio
async def test_all_versions_listed_superseded_hidden_by_default_and_review_queue_is_backend_owned(db, plan_api):  # noqa: F811
    client, state = plan_api
    data = await _two_workspaces(db)
    plans = data["plans"]
    state["user"] = data["admin"]

    body = (await client.get(URL)).json()
    ids = [row["id"] for row in body["items"]]
    expected_order = ["none_v1_rejected", "b_v1_ready", "a2_v3_draft", "a2_v2_clarify", "a_v2_ready", "a_v1_approved"]
    assert ids == [plans[key].id for key in expected_order], "updated_at desc; superseded hidden"
    # An approved v1 and an open v2 of the same item are both rows with their own versions.
    item_a_rows = {row["version"]: row["status"] for row in body["items"] if row["work_item_id"] == data["item_a"].id}
    assert item_a_rows == {1: "approved", 2: "ready_for_review"}
    assert body["status_counts"] == {
        "approved": 1, "draft": 1, "needs_clarification": 1, "ready_for_review": 2, "rejected": 1,
    }

    with_history = (await client.get(URL, params={"include_superseded": "true"})).json()
    assert plans["a2_v1_superseded"].id in [row["id"] for row in with_history["items"]]
    assert with_history["status_counts"]["superseded"] == 1

    # The queue is persisted ready_for_review only; counts stay the pre-filter scope counts.
    queue = (await client.get(URL, params={"queue": "review"})).json()
    assert [row["id"] for row in queue["items"]] == [plans["b_v1_ready"].id, plans["a_v2_ready"].id]
    assert queue["status_counts"] == body["status_counts"]

    explicit = (await client.get(URL, params={"status": "superseded"})).json()
    assert [row["id"] for row in explicit["items"]] == [plans["a2_v1_superseded"].id]


@pytest.mark.asyncio
async def test_summary_fields_are_useful_and_carry_no_evidence_blobs(db, plan_api):  # noqa: F811
    client, state = plan_api
    data = await _two_workspaces(db)
    state["user"] = data["admin"]
    rows = {row["id"]: row for row in (await client.get(URL)).json()["items"]}
    approved = rows[data["plans"]["a_v1_approved"].id]
    assert approved["plan_type"] == "coding_change"
    assert approved["acceptance_criteria_count"] == 2
    assert approved["created_by_name"] == (data["admin"].display_name or data["admin"].username)
    assert approved["work_item"] == {
        "id": data["item_a"].id, "source_key": "OCX-1", "title": "Item OCX-1", "project_id": data["a"].id,
        "work_state": "planning", "source_url": "https://jira.example.test/browse/OCX-1",
    }
    ready = rows[data["plans"]["a_v2_ready"].id]
    assert ready["plan_type"] is None, "deterministic plans have no type; never guessed"
    assert ready["change_unit_count"] == 3
    assert rows[data["plans"]["a2_v2_clarify"].id]["open_questions_count"] == 1
    assert rows[data["plans"]["a2_v3_draft"].id]["status"] == "draft", "dormant status shown verbatim"
    for forbidden in ("evidence", "change_units", "open_questions", "jira_sync_preview", "understood_request"):
        assert forbidden not in approved


@pytest.mark.asyncio
async def test_workspace_scope_for_members_null_workspace_and_roles(db, plan_api):  # noqa: F811
    client, state = plan_api
    data = await _two_workspaces(db)
    plans = data["plans"]

    state["user"] = await _user(db, "plan-member-a", projects=(data["a"].id,))
    body = (await client.get(URL, params={"include_superseded": "true"})).json()
    visible = {row["id"] for row in body["items"]}
    assert visible == {plans[key].id for key in ("a_v1_approved", "a_v2_ready", "a2_v1_superseded", "a2_v2_clarify", "a2_v3_draft")}
    assert body["status_counts"] == {
        "approved": 1, "draft": 1, "needs_clarification": 1, "ready_for_review": 1, "rejected": 0, "superseded": 1,
    }, "counts never include foreign or workspace-less plans"
    assert (await client.get(URL, params={"project_id": data["b"].id})).status_code == 403
    assert (await client.get(URL, params={"project_id": data["a"].id})).status_code == 200
    foreign_item = (await client.get(URL, params={"work_item_id": data["item_b"].id})).json()
    assert foreign_item["items"] == []

    state["user"] = await _user(db, "plan-operator-none")
    nothing = (await client.get(URL)).json()
    assert nothing["items"] == [] and set(nothing["status_counts"].values()) == {0}

    # A member without the Work role reads its own Workspace's plans (a team leader shows the team its work);
    # writing stays with the Work role. Without any membership there is nothing to read: 403.
    state["user"] = await _user(db, "plan-viewer", roles=(), projects=(data["a"].id,))
    viewed = {row["id"] for row in (await client.get(URL, params={"include_superseded": "true"})).json()["items"]}
    assert viewed == visible, "a member reads exactly its Workspace's plans"
    state["user"] = await _user(db, "plan-outsider", roles=())
    assert (await client.get(URL)).status_code == 403, "no Workspace and no Work role: nothing to read"

    state["user"] = data["admin"]
    admin_ids = {row["id"] for row in (await client.get(URL)).json()["items"]}
    assert plans["none_v1_rejected"].id in admin_ids and plans["b_v1_ready"].id in admin_ids


@pytest.mark.asyncio
async def test_work_item_detail_is_full_and_scoped(db, plan_api):  # noqa: F811
    client, state = plan_api
    data = await _two_workspaces(db)

    state["user"] = data["admin"]
    response = await client.get(f"/api/v1/secure-work/work-items/{data['item_none'].id}")
    assert response.status_code == 200
    # The full Work Item, not a summary, plus what Close would do.
    assert response.json() == {**serialize_work_item(data["item_none"]), **await close_preview(db, data["item_none"])}
    assert set(response.json()) - set(serialize_work_item(data["item_none"])) == {"close_mode", "write_back_reason"}
    assert (await client.get("/api/v1/secure-work/work-items/missing-id")).status_code == 404

    state["user"] = await _user(db, "detail-member-a", projects=(data["a"].id,))
    own = await client.get(f"/api/v1/secure-work/work-items/{data['item_a'].id}")
    assert own.status_code == 200 and own.json()["description"] == "Full description of OCX-1"
    # Another Workspace's item answers like a missing one; an item without a Workspace is admin-only.
    assert (await client.get(f"/api/v1/secure-work/work-items/{data['item_b'].id}")).status_code == 404
    assert (await client.get(f"/api/v1/secure-work/work-items/{data['item_none'].id}")).status_code == 403

    # A member without the Work role reads its Workspace's items, never another Workspace's.
    state["user"] = await _user(db, "detail-viewer", roles=(), projects=(data["a"].id,))
    assert (await client.get(f"/api/v1/secure-work/work-items/{data['item_a'].id}")).status_code == 200
    assert (await client.get(f"/api/v1/secure-work/work-items/{data['item_b'].id}")).status_code == 404
