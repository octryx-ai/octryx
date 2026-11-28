"""Policy engine: test bench, saved test cases, and the acceptance policy end to end (validate, four-eyes publish,
test bench, enforce in the governed client's tool check with the policy id in the refusal)."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.models import PolicyDecisionLog, Project, Session
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.policy_engine.decision_log import flush_decision_log
from app.services.policy_engine.runtime import current_runtime, set_policy_runtime
from app.services.policy_engine.shadow import reset_shadow_state
from app.services.policy_engine.test_bench import policy_source_text
from tests.policy_engine_support import BASE, ROLLOUT_POLICY, approve, bearer, grant_role, make_user, publish

pytestmark = pytest.mark.without_baseline_runtime

PROD = "kubectl --context prod rollout restart deploy/api"
NON_PROD = "kubectl --context nonprod rollout restart deploy/api"


async def _workspace(db, level: str | None = "internal", **config) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={"model_policy": {"allowed_aliases": ["octryx-sonnet"]},
                              **({"data_policy": {"classification": level}} if level else {}), **config})
    db.add(project)
    await db.commit()
    return project.id


async def _bench(client, admin: str, body: dict) -> dict:
    response = await client.post(f"{BASE}/test-bench", json=body, headers=bearer(admin))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_entities_list_real_workspaces_users_tools_and_actions(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db, "confidential")
    body = (await client.get(f"{BASE}/entities", headers=bearer(admin))).json()
    assert {"id": workspace, "classification": "confidential"}.items() <= next(
        item for item in body["workspaces"] if item["id"] == workspace).items()
    assert admin in {user["id"] for user in body["users"]} and "run_kubectl" in body["tools"]
    assert "run_command" in body["actions"] and body["data_policy_classes"][0] == "public"


@pytest.mark.asyncio
@pytest.mark.parametrize(("level", "action", "resource", "decision", "policy"), [
    ("confidential", "use_seat", {}, "deny", "classification:confidential:seat-not-allowed"),
    ("internal", "call_model", {"alias": "octryx-sonnet"}, "allow", "workspace:{ws}:model-granted"),
    ("internal", "call_model", {"alias": "octryx-other"}, "deny", None),
    ("restricted", "use_reranker", {"data_policy_class": "internal"}, "deny", "platform:remote-model-class-insufficient"),
    ("internal", "call_tool", {"tool": "run_kubectl", "params": {"args": "apply -f x"}}, "allow", "platform:tool-permit"),
    ("internal", "run_command", {"command": "kubectl get pods"}, "deny", "workspace:{ws}:tool-rule:kubectl-requires-context"),
    ("internal", "read_path", {"path": "/repo/.env", "tool": "Read"}, "deny", "workspace:{ws}:tool-rule:no-env-files"),
])
async def test_the_bench_answers_like_the_existing_check_and_names_the_policy(client, db, level, action, resource,
                                                                             decision, policy):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db, level, agent_gateway_policy={"seat_mode": "allowed"})
    answer = await _bench(client, admin, {"workspace_id": workspace, "user_id": admin, "action": action,
                                          "resource": resource})
    assert answer["decision"] == decision and answer["legacy"]["decision"] == decision
    ids = [item["id"] for item in answer["determining"]]
    if policy:
        expected = policy.format(ws=workspace)
        assert expected in ids
        assert next(item for item in answer["determining"] if item["id"] == expected)["text"].startswith(
            f'@id("{expected}")')
    else:
        assert ids == []
    assert answer["policy_source"] == "no custom policies published"


@pytest.mark.asyncio
async def test_bench_refusals(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db)
    for body, code in [({"action": "nope", "workspace_id": workspace}, "policy_bench_request_invalid"),
                       ({"action": "use_seat", "workspace_id": "missing"}, "project_not_found"),
                       ({"action": "run_command", "workspace_id": workspace, "resource": {}},
                        "policy_bench_request_invalid")]:
        response = await client.post(f"{BASE}/test-bench", json=body, headers=bearer(admin))
        assert response.json()["detail"]["code"] == code, body
    no_draft = await client.post(f"{BASE}/test-bench", json={"action": "use_seat", "workspace_id": workspace,
                                                             "source": "draft"}, headers=bearer(admin))
    assert no_draft.status_code == 409 and no_draft.json()["detail"]["code"] == "policy_bench_no_draft"
    bad = await client.post(f"{BASE}/test-bench", json={"action": "use_seat", "workspace_id": workspace,
                                                        "policies": "permit (principal, action, resource);"},
                            headers=bearer(admin))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "policy_set_invalid"
    member = await make_user(db, admin=False)
    assert (await client.post(f"{BASE}/test-bench", json={}, headers=bearer(member))).status_code == 403


def test_policy_source_text_skips_semicolons_in_strings():
    text = '@id("a")\nforbid (principal, action, resource) when { resource.line == "x; y\\" ;" };\n@id("b") forbid (principal, action, resource);'
    assert policy_source_text(text, "a").endswith('"x; y\\" ;" };')
    assert policy_source_text(text, "b") == '@id("b") forbid (principal, action, resource);'
    assert policy_source_text(text, "c") == ""


@pytest.mark.asyncio
async def test_wp_acceptance_rollout_policy_validates_publishes_benches_and_enforces(client, db):
    admin = await make_user(db, admin=True)
    sre, other = await make_user(db, admin=False), await make_user(db, admin=False)
    await grant_role(db, sre, "sre")
    workspace = await _workspace(db)

    check = (await client.post(f"{BASE}/validate", json={"policies": ROLLOUT_POLICY}, headers=bearer(admin))).json()
    assert check == {"valid": True, "policy_ids": ["rollout-restart-non-prod-only"], "digest": check["digest"]}
    version = await publish(client, db, ROLLOUT_POLICY)
    assert current_runtime().custom_version == version

    async def bench(user_id: str, command: str) -> dict:
        return await _bench(client, admin, {"workspace_id": workspace, "user_id": user_id, "action": "run_command",
                                            "resource": {"command": command}})

    denied = await bench(sre, PROD)
    assert denied["decision"] == "deny" and denied["legacy"] == {"decision": "allow", "reason": "no_rule_matched"}
    assert [item["id"] for item in denied["determining"]] == ["rollout-restart-non-prod-only"]
    assert denied["determining"][0]["source"] == "custom" and denied["policy_source"] == f"published version {version}"
    assert (await bench(sre, NON_PROD))["decision"] == "allow"
    assert (await bench(sre, "kubectl rollout restart deploy/api --context=nonprod"))["decision"] == "allow"
    assert (await bench(other, PROD))["decision"] == "allow"

    set_policy_runtime(replace(current_runtime(), mode="enforce"))
    session = Session(id=str(uuid.uuid4()), user_id=sre, project_id=workspace, agent_type="external_agent",
                      status="active", metadata_={"client": "octryx-claude"})
    db.add(session)
    await db.commit()
    policy = build_policy(BASELINE_POLICY, source="baseline")
    answer = await decide_tool_check(db, session=session, session_key="k", policy=policy,
                                     hook_input={"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": PROD}, "cwd": "/repo"})
    assert answer["decision"] == "deny" and answer["reason"] == "cedar_policy_denied"
    assert answer["rule_id"] == "rollout-restart-non-prod-only"
    assert "rollout-restart-non-prod-only" in answer["message"]
    await flush_decision_log(db)
    record = (await db.execute(select(PolicyDecisionLog).where(PolicyDecisionLog.point == "gateway_tool_check"))).scalar_one()
    assert record.id in answer["message"] and record.mode == "enforce" and record.outcome == "custom_policy"
    shown = (await client.get(f"{BASE}/decisions/{record.id}", headers=bearer(admin))).json()
    assert shown["determining_policies"] == ["rollout-restart-non-prod-only"]
    passes = await decide_tool_check(db, session=session, session_key="k", policy=policy,
                                     hook_input={"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": NON_PROD}, "cwd": "/repo"})
    assert passes["reason"] != "cedar_policy_denied"
    reset_shadow_state()


@pytest.mark.asyncio
async def test_saved_cases_run_on_save_and_block_publishing(client, db):
    admin = await make_user(db, admin=True)
    sre = await make_user(db, admin=False)
    await grant_role(db, sre, "sre")
    workspace = await _workspace(db)
    case = {"name": "sre restart in prod is blocked", "expected": "deny",
            "request": {"workspace_id": workspace, "user_id": sre, "action": "run_command",
                        "resource": {"command": PROD}}}
    created = await client.post(f"{BASE}/tests", json=case, headers=bearer(admin))
    assert created.status_code == 201
    invalid = await client.post(f"{BASE}/tests", json={**case, "expected": "maybe"}, headers=bearer(admin))
    assert invalid.status_code == 422 and invalid.json()["detail"]["path"] == "expected"
    assert (await client.post(f"{BASE}/tests/run", json={}, headers=bearer(admin))).json()["ok"] is False

    good = (await client.post(f"{BASE}/policy-sets", json={"policies": ROLLOUT_POLICY}, headers=bearer(admin))).json()
    assert good["test_report"]["ok"] is True and good["test_report"]["results"][0]["actual"] == "deny"
    await publish(client, db, ROLLOUT_POLICY)
    assert (await client.post(f"{BASE}/tests/run", json={}, headers=bearer(admin))).json()["ok"] is True

    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    empty = (await client.post(f"{BASE}/policy-sets", json={"policies": ""}, headers=bearer(author))).json()
    assert empty["test_report"]["ok"] is False and empty["test_report"]["failed"] == 1
    approval_id = (await client.post(f"{BASE}/policy-sets/{empty['version']}/submit",
                                     headers=bearer(author))).json()["governance_approval_id"]
    await approve(db, approval_id, reviewer)
    blocked = await client.post(f"{BASE}/policy-sets/{empty['version']}/publish",
                                json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "policy_set_tests_failed"
    assert blocked.json()["detail"]["test_report"]["results"][0]["actual"] == "allow"
    listing = (await client.get(f"{BASE}/tests", headers=bearer(admin))).json()
    assert listing["count"] == 1
    deleted = await client.delete(f"{BASE}/tests/{listing['items'][0]['id']}", headers=bearer(admin))
    assert deleted.status_code == 200
    assert (await client.delete(f"{BASE}/tests/{listing['items'][0]['id']}", headers=bearer(admin))).status_code == 404


@pytest.mark.asyncio
async def test_the_bench_evaluates_every_point_for_the_user_like_the_live_check(client, db):
    admin = await make_user(db, admin=True)
    sre = await make_user(db, admin=False)
    await grant_role(db, sre, "sre")
    workspace = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    candidate = '@id("no-seat-for-sre")\nforbid (principal in Role::"sre", action == Action::"use_seat", resource);\n'
    answer = await _bench(client, admin, {"workspace_id": workspace, "user_id": sre, "action": "use_seat",
                                          "policies": candidate})
    assert answer["decision"] == "deny" and answer["principal"] == f"User::{sre}"
    assert [item["id"] for item in answer["determining"]] == ["no-seat-for-sre"]
    assert answer["notes"] == [] and answer["policy_source"] == "candidate text"
    command = await _bench(client, admin, {"workspace_id": workspace, "user_id": sre, "action": "run_command",
                                           "resource": {"command": "ls"}})
    assert command["notes"] == [] and command["principal"] == f"User::{sre}"


@pytest.mark.asyncio
async def test_re_saving_a_draft_reruns_the_saved_cases(client, db):
    admin = await make_user(db, admin=True)
    sre = await make_user(db, admin=False)
    await grant_role(db, sre, "sre")
    workspace = await _workspace(db)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": ""}, headers=bearer(admin))).json()
    assert draft["test_report"]["total"] == 0
    await client.post(f"{BASE}/tests", headers=bearer(admin), json={
        "name": "blocked", "expected": "deny",
        "request": {"workspace_id": workspace, "user_id": sre, "action": "run_command", "resource": {"command": PROD}}})
    saved = (await client.put(f"{BASE}/policy-sets/{draft['version']}", json={"policies": ROLLOUT_POLICY},
                              headers={**bearer(admin), "If-Match": draft["digest"]})).json()
    assert saved["test_report"]["total"] == 1 and saved["test_report"]["ok"] is True


@pytest.mark.asyncio
async def test_the_bench_works_without_a_bound_prompt_set_like_a_live_admin_request(client, db):
    from app.services.prompt_catalog import prompt_set_scope

    admin = await make_user(db, admin=True)
    workspace = await _workspace(db)
    with prompt_set_scope(None):
        response = await client.post(f"{BASE}/test-bench", headers=bearer(admin), json={
            "workspace_id": workspace, "action": "run_command", "resource": {"command": "kubectl get pods"}})
    assert response.status_code == 200, response.text
    assert response.json()["legacy"]["decision"] == "deny"
