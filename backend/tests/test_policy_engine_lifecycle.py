"""Policy UX: the review in the lifecycle drawer and the impact examples."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json
from tests.policy_engine_support import BASE, approve, bearer, grant_role, make_user, publish


async def _workspace(db, level: str | None = "internal", order: str = "5") -> str:
    """``order`` leads the name: the examples take the first matching Workspace by name."""
    project = Project(id=str(uuid.uuid4()), name=f"a-{order}-{level}-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"data_policy": {"classification": level}} if level else {})
    db.add(project)
    await db.commit()
    return project.id


# --- G11 --------------------------------------------------------------------------------------------------------

SEAT = '@id("seat")\nforbid (principal, action == Action::"use_seat", resource);\n'


@pytest.mark.asyncio
async def test_the_review_names_requester_candidates_and_who_may_approve(client, db):
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": SEAT, "note": "seat"}, headers=bearer(author))).json()
    version = draft["version"]
    assert (await client.get(f"{BASE}/policy-sets/{version}", headers=bearer(author))).json()["review"] is None
    approval_id = (await client.post(f"{BASE}/policy-sets/{version}/submit", headers=bearer(author))).json()[
        "governance_approval_id"]

    mine = (await client.get(f"{BASE}/policy-sets/{version}", headers=bearer(author))).json()["review"]
    assert mine["approval_id"] == approval_id and mine["status"] == "pending"
    assert mine["requested_by"]["id"] == author and mine["author"]["id"] == author and mine["submitter"]["id"] == author
    candidates = {item["id"] for item in mine["approver_candidates"]}
    assert reviewer in candidates and author not in candidates
    assert mine["viewer"] == {"is_author": True, "is_submitter": True, "can_approve": False}
    assert "other than the author and the submitter" in mine["rule"]
    theirs = (await client.get(f"{BASE}/policy-sets/{version}", headers=bearer(reviewer))).json()["review"]
    assert theirs["viewer"] == {"is_author": False, "is_submitter": False, "can_approve": True}

    await approve(db, approval_id, reviewer)
    decided = (await client.get(f"{BASE}/policy-sets/{version}", headers=bearer(reviewer))).json()["review"]
    assert decided["status"] == "approved" and decided["decided_by"]["id"] == reviewer
    assert decided["viewer"]["can_approve"] is False, "nothing left to approve"
    published = await client.post(f"{BASE}/policy-sets/{version}/publish", json={"governance_approval_id": approval_id},
                                  headers=bearer(author))
    assert published.status_code == 200
    listed = next(item for item in (await client.get(f"{BASE}/policy-sets", headers=bearer(author))).json()["items"]
                  if item["version"] == version)
    assert listed["reviewer"] == reviewer and listed["reviewer_name"] and listed["author_name"]


# --- G12 --------------------------------------------------------------------------------------------------------


async def _impact(client, admin, model, original_id=None):
    response = await client.post(f"{BASE}/test-bench/generate", json={"model": model, "original_id": original_id},
                                 headers=bearer(admin))
    assert response.status_code == 200, response.text
    return response.json()


def _by_kind(body):
    return [(item["kind"], item["request"]["action"], item["answer"]["by_this_policy"], item["answer"]["as_expected"])
            for item in body["examples"]]


@pytest.mark.asyncio
async def test_connection_examples_block_on_the_connection_and_leave_another_one_alone(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db)
    model = {"id": "jira-prod-read-only", "actions": ["write_connector"], "what": {"families": ["jira"]},
             "where": {"workspaces": [workspace], "connections": ["c-prod"]}}
    body = await _impact(client, admin, model)
    assert body["workspace"]["id"] == workspace
    assert _by_kind(body) == [("block", "write_connector", True, True), ("control", "write_connector", False, True)]
    blocked, control = body["examples"]
    assert blocked["request"]["resource"]["connections"] == ["c-prod"] and blocked["answer"]["decision"] == "deny"
    assert blocked["expected"] == "deny" and control["expected"] == "allow"
    assert control["request"]["resource"]["connections"] == ["policy-example-other-connection"]
    assert body["policy_source"] == "this policy alone" and body["cases"]["total"] == 0


@pytest.mark.asyncio
async def test_command_path_and_model_examples(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db)
    command = {"id": "restarts", "actions": ["run_command"], "where": {"workspaces": [workspace]},
               "what": {"programs": ["kubectl"], "arguments": ["rollout", "restart"]},
               "conditions": {"unless_option_values": ["--context=nonprod"]}}
    body = await _impact(client, admin, command)
    assert [item["request"]["resource"]["command"] for item in body["examples"]] == [
        "kubectl rollout restart", "kubectl rollout restart --context=nonprod"]
    assert _by_kind(body) == [("block", "run_command", True, True), ("control", "run_command", False, True)]

    paths = {"id": "secrets", "actions": ["read_path", "write_path"], "where": {"workspaces": [workspace]},
             "what": {"paths": ["*.env", "*.pem"]}}
    body = await _impact(client, admin, paths)
    assert [item["request"]["resource"]["path"] for item in body["examples"]] == ["/workspace/example.env",
                                                                                "/workspace/README.md"]
    assert all(item["answer"]["as_expected"] for item in body["examples"])

    models = {"id": "approved-only", "actions": ["call_model"], "where": {"workspaces": [workspace]},
              "what": {"models": ["approved-model"], "model_mode": "except"}}
    body = await _impact(client, admin, models)
    assert [(item["kind"], item["request"]["resource"]["alias"]) for item in body["examples"]] == [
        ("block", "example-model"), ("control", "approved-model")]
    assert body["examples"][0]["answer"]["by_this_policy"] is True
    assert body["examples"][1]["answer"]["by_this_policy"] is False


@pytest.mark.asyncio
async def test_who_examples_use_a_member_and_skip_admins_when_excepted(client, db):
    admin = await make_user(db, admin=True)
    member, admin_member = await make_user(db, admin=False), await make_user(db, admin=True)
    role = f"ops-{uuid.uuid4().hex[:6]}"
    await grant_role(db, member, role)
    await grant_role(db, admin_member, role)
    workspace = await _workspace(db)
    model = {"id": "ops-no-rm", "actions": ["run_command"], "who": {"mode": "roles", "items": [role],
                                                                     "except_admins": True},
             "where": {"workspaces": [workspace]}, "what": {"programs": ["rm"]}}
    body = await _impact(client, admin, model)
    assert body["user_id"] == member and body["notes"] == []
    assert body["examples"][0]["request"]["user_id"] == member and body["examples"][0]["answer"]["by_this_policy"]
    lonely = {**model, "who": {"mode": "roles", "items": ["nobody-has-this-role"]}}
    assert (await _impact(client, admin, lonely))["notes"] == [
        "Nobody matches the who-part yet; the examples run without a user."]
    admins_only = f"admins-{uuid.uuid4().hex[:6]}"
    await grant_role(db, admin_member, admins_only)
    excepted = await _impact(client, admin, {**model, "who": {"mode": "roles", "items": [admins_only],
                                                             "except_admins": True}})
    assert excepted["user_id"] is None, "an excepted platform admin is never the blocked example"


@pytest.mark.asyncio
async def test_no_matching_workspace_means_no_examples_and_says_why(client, db):
    admin = await make_user(db, admin=True)
    model = {"id": "x", "actions": ["use_seat"], "where": {"workspaces": ["no-such-workspace"]}}
    body = await _impact(client, admin, model)
    assert body["examples"] == [] and body["notes"] == ["No active Workspace matches the where-part, so there is "
                                                        "nothing to ask."]


@pytest.mark.asyncio
async def test_the_candidate_replaces_the_edited_policy_and_runs_the_saved_cases(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db)
    old, _ = model_from_json({"id": "old-id", "actions": ["run_command"], "what": {"programs": ["rm"]}})
    await publish(client, db, render(old) + "\n")
    case = {"name": "rm stays allowed", "expected": "allow",
            "request": {"workspace_id": workspace, "action": "run_command", "resource": {"command": "rm x"}}}
    assert (await client.post(f"{BASE}/tests", json=case, headers=bearer(admin))).status_code == 201
    edited = {"id": "new-id", "actions": ["run_command"], "where": {"workspaces": [workspace]}, "what": {"programs": ["rm"]}}
    body = await _impact(client, admin, edited, original_id="old-id")
    assert body["policy_source"].endswith("with this policy")
    assert body["cases"]["failed"] == 1 and body["cases"]["results"][0]["determining"] == ["new-id"]
    assert all("old-id" not in item["answer"]["determining"] for item in body["examples"])
    refused = await client.post(f"{BASE}/test-bench/generate", json={"model": {"id": "x", "actions": []}},
                                headers=bearer(admin))
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "policy_builder_model_invalid"


@pytest.mark.asyncio
async def test_the_example_workspace_satisfies_the_classification(client, db):
    admin = await make_user(db, admin=True)
    await _workspace(db, "internal", order="0")
    confidential = await _workspace(db, "confidential", order="1")
    await _workspace(db, None, order="2")
    body = await _impact(client, admin, {"id": "conf", "actions": ["use_seat"],
                                         "where": {"classification_at_least": "confidential"}})
    assert body["workspace"]["id"] == confidential
    unresolved = await _impact(client, admin, {"id": "un", "actions": ["use_seat"], "where": {"unclassified": True}})
    assert unresolved["workspace"]["classification"] is None
    exact = await _impact(client, admin, {"id": "is", "actions": ["use_seat"],
                                          "where": {"classification_is": ["confidential"]}})
    assert exact["workspace"]["classification"] == "confidential"
