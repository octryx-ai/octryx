from __future__ import annotations

import re
import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.models import (
    AgentDefinition,
    Approval,
    ClarificationQuestion,
    DeviceJob,
    KillSwitchLog,
    Session,
    SessionAccess,
    SessionHandover,
    UserDevice,
)
from app.services.agent_visibility import agent_access
from app.services.attention.handover_items import handover_entries
from app.services.observability.overview_read_model import overview
from app.services.session.handovers import HandoverError, hand_over
from app.time_utils import utc_now
from tests.policy_engine_support import bearer
from tests.project.private_workspace_resource_support import OWNER_MARKER, insert_run, owner_admin_and_resources
from tests.workspace_id_route_inventory import changed, snapshot
from tests.workspace_id_route_support import answer_text, refusal_code

pytestmark = pytest.mark.asyncio

FAMILIES = (
    ("/api/v1/workflow-runs/{run_id}", "run_id", "run_id"),
    ("/api/v1/attention/jobs/{run_id}", "run_id", "run_id"),
    ("/api/v1/approvals/{approval_id}", "approval_id", "approval_id"),
    ("/api/v1/admin/problems/{key", "key", "problem_key"),
    ("/api/v1/secure-work/coding-pipelines/{config_id}", "config_id", "pipeline_config_id"),
    ("/api/v1/connector-watchers/{watcher_id}", "watcher_id", "watcher_id"),
    ("/api/v1/secure-work/workflows/{workflow_id}", "workflow_id", "workflow_id"),
)
LISTS = (
    ("/api/v1/workflow-runs", {}, "run_id"),
    ("/api/v1/attention/jobs", {"scope": "team"}, "run_id"),
    ("/api/v1/approvals", {}, "approval_id"),
    ("/api/v1/approvals/decidable", {}, "approval_id"),
    ("/api/v1/admin/problems", {}, "problem_key"),
    ("/api/v1/secure-work/coding-pipelines", {}, "pipeline_config_id"),
    ("/api/v1/secure-work/repository-profiles", {}, "repository_profile_id"),
    ("/api/v1/connector-watchers", {}, "watcher_id"),
    ("/api/v1/secure-work/workflows", {}, "workflow_id"),
    ("/admin/chat/api/panel/connector-watchers", {}, "watcher_id"),
    ("/admin/chat/api/panel/connector-watcher-events", {}, "watcher_event_id"),
    ("/admin/chat/api/panel/connector-watcher-rules", {}, "watcher_rule_id"),
    ("/admin/chat/api/panel/connector-watcher-rule-decisions", {}, "watcher_decision_id"),
)
REASON = {"reason": "synthetic check"}
BODIES = {
    ("POST", "/api/v1/approvals/{approval_id}/approve"): REASON,
    ("POST", "/api/v1/approvals/{approval_id}/reject"): REASON,
    ("POST", "/api/v1/workflow-runs/{run_id}/actions"): {"action": "abort"},
    ("PATCH", "/api/v1/workflow-runs/{run_id}/spec-studio"): {"title": "synthetic"},
    ("POST", "/api/v1/workflow-runs/{run_id}/emergency-stop"): REASON,
    ("PUT", "/api/v1/connector-watchers/{watcher_id}"): {"name": "renamed"},
    ("PUT", "/api/v1/secure-work/coding-pipelines/{config_id}"): {"name": "renamed"},
    ("PUT", "/api/v1/secure-work/workflows/{workflow_id}"): {"name": "renamed"},
    ("POST", "/api/v1/secure-work/workflows/{workflow_id}/dry-run-transition"): {"work_item_id": "x",
                                                                                 "to_state": "planning"},
}
QUERIES = {("GET", "/api/v1/workflow-runs/{run_id}/spec-studio/corporate-asset"): {"path": "README.md"}}
_PARAM = re.compile(r"\{(\w+)(?::\w+)?\}")
# The ingress of an external system: authorized by the watcher's secret, not by the caller's role.
NOT_ROLE_BOUND = {("POST", "/api/v1/connector-watchers/{watcher_id}/webhook")}


def _routes(prefix: str) -> list[tuple[str, str]]:
    found = sorted({(method, route.path) for route in app.routes if isinstance(route, APIRoute)
                    and route.path.startswith(prefix) for method in route.methods - {"HEAD"}} - NOT_ROLE_BOUND)
    assert found, prefix
    return found


def _url(path: str, param: str, value: str) -> str:
    return _PARAM.sub(lambda match: value if match.group(1) == param else "x", path)


@pytest.mark.parametrize(("prefix", "param", "field"), FAMILIES, ids=[family[0] for family in FAMILIES])
async def test_a_foreign_private_resource_answers_an_admin_like_an_unknown_id(client, db, prefix, param, field):
    owner, admin, resources = await owner_admin_and_resources(db)
    private, unknown = getattr(resources["private"], field), getattr(resources["private"].unknown(), field)
    before = await snapshot(db)
    for method, path in _routes(prefix):
        body = {key: value.format(owner=owner.id) for key, value in BODIES.get((method, path), {}).items()}
        answers = {}
        for value in (private, unknown):
            response = await client.request(method, _url(path, param, value), headers=bearer(admin.id),
                                            params=QUERIES.get((method, path)),
                                            json=body if method != "GET" else None)
            assert OWNER_MARKER not in response.text, (method, path, response.text[:300])
            answers[value == private] = (response.status_code, refusal_code(response),
                                         answer_text(response, private, unknown))
        assert answers[True] == answers[False], (method, path, answers)
        assert answers[True][0] != 422, (method, path, answers)
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], prefix


@pytest.mark.parametrize(("url", "params", "field"), LISTS, ids=[item[0] for item in LISTS])
async def test_admin_lists_leave_out_foreign_private_rows_and_keep_shared_and_own_ones(client, db, url, params,
                                                                                         field):
    _owner, admin, resources = await owner_admin_and_resources(db)
    response = await client.get(url, headers=bearer(admin.id), params=params)
    assert response.status_code == 200, response.text[:300]
    assert getattr(resources["private"], field) not in response.text
    assert resources["private"].workspace_id not in response.text
    for kind in ("shared", "own"):
        assert getattr(resources[kind], field) in response.text, (kind, response.text[:300])


async def test_problem_counts_leave_out_a_foreign_private_workspace(client, db):
    _owner, admin, resources = await owner_admin_and_resources(db)
    answers = set()
    for workspace_id in (resources["private"].workspace_id, resources["private"].unknown().workspace_id):
        answer = await client.get("/api/v1/admin/problems", headers=bearer(admin.id),
                                  params={"workspace_id": workspace_id})
        answers.add((answer.status_code, answer_text(answer, workspace_id)))
    assert len(answers) == 1, answers
    everything = (await client.get("/api/v1/admin/problems", headers=bearer(admin.id))).json()
    intakes = [item for item in everything["problems"] if item["kind"] == "intake"]
    assert everything["counts"]["by_kind"]["intake"] == len(intakes)


async def test_the_owner_and_an_admin_in_shared_and_own_workspaces_still_open_runs_and_approvals(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    cases = [(owner, resources["private"])] + [(admin, resources[kind]) for kind in ("shared", "own")]
    for user, rows in cases:
        for url in (f"/api/v1/workflow-runs/{rows.run_id}", f"/api/v1/attention/jobs/{rows.run_id}",
                    f"/api/v1/approvals/{rows.approval_id}"):
            response = await client.get(url, headers=bearer(user.id))
            assert response.status_code == 200, (url, response.text[:300])


async def test_workspace_members_of_a_foreign_private_workspace_answer_like_an_unknown_one(client, db):
    _owner, admin, resources = await owner_admin_and_resources(db)
    answers = set()
    for workspace_id in (resources["private"].workspace_id, resources["private"].unknown().workspace_id):
        response = await client.get(f"/api/v1/workspaces/{workspace_id}/members", headers=bearer(admin.id))
        answers.add((response.status_code, answer_text(response, workspace_id)))
    assert len(answers) == 1 and next(iter(answers))[0] == 404, answers
    shared = await client.get(f"/api/v1/workspaces/{resources['shared'].workspace_id}/members",
                              headers=bearer(admin.id))
    assert shared.status_code == 200


async def test_the_linked_account_workspace_choice_leaves_out_a_foreign_private_workspace(client, db):
    _owner, admin, resources = await owner_admin_and_resources(db)
    response = await client.get(f"/api/v1/users/{admin.id}/linked-accounts", headers=bearer(admin.id))
    assert response.status_code == 200, response.text[:300]
    listed = {item["id"] for item in response.json()["workspaces"]}
    assert resources["private"].workspace_id not in listed
    assert {resources["shared"].workspace_id, resources["own"].workspace_id} <= listed


async def test_an_admin_neither_sees_nor_edits_an_agent_of_a_foreign_private_workspace(db):
    owner, admin, resources = await owner_admin_and_resources(db)
    agents = {kind: AgentDefinition(owner_id=owner.id if kind == "private" else admin.id,
                                    project_id=resources[kind].workspace_id, name=f"{kind} agent",
                                    agent_type="diagnosis", system_prompt="Summarise.")
              for kind in ("private", "shared", "own")}
    db.add_all(agents.values())
    await db.commit()
    access = await agent_access(db, admin.id)
    for clause in (access.visible_clause(), access.editable_clause()):
        found = set((await db.execute(select(AgentDefinition.id).where(clause))).scalars())
        assert agents["private"].id not in found and {agents["shared"].id, agents["own"].id} <= found
    assert [access.can_edit(agents[kind]) for kind in ("private", "shared", "own")] == [False, True, True]


async def _running_job(db, owner, workspace_id: str) -> DeviceJob:
    device = UserDevice(owner_user_id=owner.id, name="device", name_key=f"dev-{uuid.uuid4().hex[:6]}", os="macos",
                        public_key="k")
    chat = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=workspace_id, origin="chat")
    db.add_all([device, chat])
    await db.flush()
    job = DeviceJob(device_id=device.id, owner_user_id=owner.id, session_id=chat.id, workspace_id=workspace_id,
                    folder=f"/{workspace_id}", profile="seat", status="running", turn_state="accepted")
    db.add(job)
    await db.commit()
    return job


async def test_a_platform_stop_stops_a_foreign_private_job_and_only_counts_it(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    hidden, shared = (await _running_job(db, owner, resources["private"].workspace_id),
                      await _running_job(db, admin, resources["shared"].workspace_id))
    preview = await client.get("/api/v1/admin/operations/emergency-stop/preview", headers=bearer(admin.id))
    assert shared.id in preview.text and hidden.id not in preview.text
    assert resources["private"].workspace_id not in preview.text
    assert "hidden_device_jobs_stopped" not in preview.json()
    stopped = await client.post("/api/v1/admin/operations/emergency-stop", headers=bearer(admin.id),
                                json={"reason": "synthetic platform stop"})
    assert stopped.status_code == 200, stopped.text[:300]
    body = stopped.json()
    assert hidden.id not in stopped.text and resources["private"].workspace_id not in stopped.text
    assert (body["stopped_device_jobs"], body["hidden_device_jobs_stopped"]) == ([shared.id], 1)
    assert (await db.get(DeviceJob, hidden.id)).stop_state == "pending"
    history = await client.get("/api/v1/admin/operations/emergency-stop/history", headers=bearer(admin.id))
    [global_stop] = [row for row in history.json()["stops"] if row["id"] == body["log_id"]]
    assert (global_stop["stopped_device_jobs"], global_stop["hidden_device_jobs_stopped"]) == ([shared.id], 1)
    assert hidden.id not in history.text


async def test_the_stop_history_redacts_an_older_global_log_and_leaves_out_a_private_workspace_log(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    hidden, shared = (await _running_job(db, owner, resources["private"].workspace_id),
                      await _running_job(db, admin, resources["shared"].workspace_id))
    gone = str(uuid.uuid4())
    older = KillSwitchLog(action="pause", target_type="global", user_id=admin.id, reason="older global stop",
                          details={"kind": "emergency_stop",
                                   "paused_runs": [resources["private"].run_id, resources["shared"].run_id, gone],
                                   "stopped_device_jobs": [hidden.id, shared.id, gone]})
    own_stop = KillSwitchLog(action="pause", target_type="project", target_id=resources["private"].workspace_id,
                             project_id=resources["private"].workspace_id, user_id=owner.id,
                             reason=f"{OWNER_MARKER} stop", details={"kind": "emergency_stop"})
    db.add_all([older, own_stop])
    await db.commit()
    history = await client.get("/api/v1/admin/operations/emergency-stop/history", headers=bearer(admin.id))
    assert history.status_code == 200, history.text[:300]
    [row] = [item for item in history.json()["stops"] if item["id"] == older.id]
    assert (row["stopped_device_jobs"], row["hidden_device_jobs_stopped"]) == ([shared.id], 2)
    assert (row["paused_runs"], row["hidden_runs_paused"]) == ([resources["shared"].run_id], 2)
    for hidden_value in (hidden.id, resources["private"].run_id, gone, own_stop.id, OWNER_MARKER):
        assert hidden_value not in history.text, hidden_value


async def test_a_platform_preview_answers_the_same_with_and_without_hidden_jobs(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    path = "/api/v1/admin/operations/emergency-stop/preview"
    before = (await client.get(path, headers=bearer(admin.id))).json()
    hidden = await _running_job(db, owner, resources["private"].workspace_id)
    preview = await client.get(path, headers=bearer(admin.id))
    assert preview.json() == before
    assert hidden.id not in preview.text


async def test_the_overview_waiting_counts_leave_out_a_foreign_private_workspace(db):
    owner, admin, resources = await owner_admin_and_resources(db)
    stale = utc_now() - timedelta(days=2)
    approval = await db.get(Approval, resources["private"].approval_id)
    session = await db.get(Session, approval.session_id)
    session.started_at = session.last_activity_at = stale
    db.add(ClarificationQuestion(session_id=session.id, project_id=resources["private"].workspace_id,
                                 question_id="q-1", question_text=f"{OWNER_MARKER} question", status="open",
                                 requested_by=owner.id, created_at=stale))
    await db.commit()

    async def titles(viewer_id: str) -> list[str]:
        return [item["title"] for item in (await overview(db, checks={}, viewer_id=viewer_id))["attention"]]

    seen_by_admin, seen_by_owner = await titles(admin.id), await titles(owner.id)
    for marker in ("approval(s) wait on sessions", "clarification(s) unanswered"):
        assert any(marker in title for title in seen_by_owner), marker
        assert not any(marker in title for title in seen_by_admin), marker


async def test_a_requester_outside_a_private_workspace_neither_opens_nor_is_offered_its_run(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    own_request = await insert_run(db, resources["private"].workspace_id, admin.id)
    offered = await insert_run(db, resources["private"].workspace_id, owner.id)
    session_id = (await db.get(Approval, resources["private"].approval_id)).session_id
    db.add(SessionHandover(session_id=session_id, run_id=offered, from_user_id=owner.id, to_user_id=admin.id,
                           status="pending"))
    await db.commit()
    for run_id in (own_request, offered):
        known = await client.get(f"/api/v1/workflow-runs/{run_id}", headers=bearer(admin.id))
        unknown = await client.get(f"/api/v1/workflow-runs/{uuid.uuid4()}", headers=bearer(admin.id))
        assert (known.status_code, refusal_code(known)) == (unknown.status_code, refusal_code(unknown)) != (200, "")
    listed = await client.get("/api/v1/workflow-runs", headers=bearer(admin.id))
    jobs = await client.get("/api/v1/attention/jobs", headers=bearer(admin.id))
    assert own_request not in listed.text and own_request not in jobs.text
    assert offered not in {entry["id"] for entry in await handover_entries(db, admin)}
    with pytest.raises(HandoverError) as refused:
        await hand_over(db, user=owner, session_id=session_id, to_user_id=admin.id, reason="synthetic")
    assert refused.value.code == "handover_receiver_invalid"


async def test_an_owner_granted_session_write_lets_an_admin_find_and_decide_its_approval(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    approval = await db.get(Approval, resources["private"].approval_id)
    db.add(SessionAccess(session_id=approval.session_id, user_id=admin.id, access_scope="read_write",
                         granted_by=owner.id))
    await db.commit()
    assert (await client.get(f"/api/v1/approvals/{approval.id}", headers=bearer(admin.id))).status_code == 200
    for url in ("/api/v1/approvals", "/api/v1/approvals/decidable"):
        assert approval.id in (await client.get(url, headers=bearer(admin.id))).text, url
    decided = await client.post(f"/api/v1/approvals/{approval.id}/reject", headers=bearer(admin.id), json=REASON)
    assert decided.status_code == 200, decided.text[:300]
    assert decided.json()["status"] == "rejected"


async def test_a_read_only_grant_shows_no_foreign_private_approval_to_an_admin(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    approval = await db.get(Approval, resources["private"].approval_id)
    db.add(SessionAccess(session_id=approval.session_id, user_id=admin.id, access_scope="read", granted_by=owner.id))
    await db.commit()
    assert (await client.get(f"/api/v1/approvals/{approval.id}", headers=bearer(admin.id))).status_code == 404
    assert approval.id not in (await client.get("/api/v1/approvals", headers=bearer(admin.id))).text


async def test_the_agents_panel_shows_no_foreign_private_workspace_or_its_agent_usage(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    agents = {}
    for kind, user in (("private", owner), ("shared", admin)):
        agents[kind] = AgentDefinition(owner_id=user.id, project_id=resources[kind].workspace_id,
                                       name=f"{kind} agent", agent_type="diagnosis", system_prompt="Summarise.")
        db.add(agents[kind])
        await db.flush()
        db.add(Session(id=str(uuid.uuid4()), user_id=user.id, project_id=resources[kind].workspace_id,
                       origin="chat", metadata_={"agent_definition_id": agents[kind].id}))
    await db.commit()
    meta = await client.get("/admin/chat/api/panel/agents/meta", headers=bearer(admin.id))
    assert meta.status_code == 200, meta.text[:300]
    projects = {item["id"] for item in meta.json()["projects"]}
    assert resources["private"].workspace_id not in projects and resources["shared"].workspace_id in projects
    usage = (await client.get("/admin/chat/api/panel/agents/overview", headers=bearer(admin.id))).json()["usage"]
    assert agents["private"].id not in usage and usage.get(agents["shared"].id) == 1


async def test_the_live_fleet_does_not_count_a_foreign_private_job(client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    job = await _running_job(db, owner, resources["private"].workspace_id)
    live = await client.get("/api/v1/admin/operations/live", headers=bearer(admin.id))
    assert live.status_code == 200, live.text[:300]
    [device] = [item for item in live.json()["devices"] if item["id"] == job.device_id]
    assert device["jobs_running"] == 0
