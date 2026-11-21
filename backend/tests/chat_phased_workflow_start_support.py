"""Shared helpers for the test_chat_phased_workflow_start_* modules."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
import app.services.control_plane_service as control_plane_module
from app.models import Approval, CodeRepository, Project, User, UserProject, WorkflowRun, WorkItem
from app.models import Session as ChatSession
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

# A realistic request.
IDEA = ("Lege in Jira-Projekt CHEF ein Epic 'Hello Kitchen' an, lass die Spezifikation schreiben, in genau 2 Stories "
        "schneiden und danach umsetzen.")


class _ProposalProvider:
    def __init__(self, workflow_key: str) -> None:
        self.content = json.dumps({"workflow_key": workflow_key, "confidence": "high", "requested": True,
                                   "reason": "An idea to specify, split and build."})
        self.calls = 0

    def __call__(self, **_kwargs):
        return self

    async def chat(self, *, messages, model, temperature, max_tokens):
        self.calls += 1
        return {"content": self.content, "usage": {"prompt_tokens": 40, "completion_tokens": 12}, "model": model}


@pytest.fixture
def fakes(monkeypatch):
    """The proposal provider, the turn model (records whether a turn reached it), ``start_run`` (records) and the
    Jira tool (``state["jira"]``: its answer; every call is checked against the real write-plan gate)."""
    state = {"model_calls": 0, "started": [], "jira_calls": [], "jira_reads": [], "issues": {},
             "jira": {"ticket_id": "CHEF-7", "id": "10007", "status": "success"}}

    def install(proposal_key: str = "spec-writing") -> dict:
        async def fake_runtimes(_db, runtime_target_id=None, **_kwargs):
            return [{"provider_name": "fake", "model": "fake-model"}]

        async def model(*, runtimes, messages, tools, **_kwargs):
            state["model_calls"] += 1
            return {"model": "fake-model", "content": "plain answer", "tool_calls": None,
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}, runtimes[0]

        async def fake_start_run(db, *, user, workflow_key, project_id=None, work_item_id=None, session=None,
                                 runtime_target=None, repository=None, **_kwargs):
            from app.services.workflow_runs.records import WorkflowRunError

            if state.get("refuse_run"):
                raise WorkflowRunError("server_build_not_allowed", state.pop("refuse_run"), 409)
            run = WorkflowRun(id=str(uuid.uuid4()), project_id=project_id, workflow_kind="phased",
                              workflow_key=workflow_key, title=workflow_key, work_item_id=work_item_id,
                              requested_by=user.id, status="running")
            db.add(run)
            await db.flush()
            if state.get("commit_inside"):
                await db.commit()  # what a platform action's tool does (``circuit_breaker`` records its health)
                await db.execute(select(WorkflowRun.id).where(WorkflowRun.id == run.id))  # and the next step reads
            state["started"].append({"workflow_key": workflow_key, "work_item_id": work_item_id,
                                     "session_id": session.id, "runtime_target": runtime_target,
                                     "repository": repository})
            return run

        async def fake_tool(tool_name, params, context):
            from app.services.run_capability.chat_write_plan import plan_decision

            if tool_name == "get_jira_ticket":  # a read: free, recorded apart from the writes
                state["jira_reads"].append(params["ticket_id"])
                issue = state["issues"].get(params["ticket_id"])
                if issue and state.get("fenced"):  # what the real dispatch hands back (live reads fenced)
                    from app.services.content_security.knowledge_fence import fence_knowledge_result

                    return fence_knowledge_result("get_jira_ticket", dict(issue))
                return dict(issue) if issue else {"error": f"Issue {params['ticket_id']} does not exist"}
            from app.services.run_capability.chat_writes import chat_connector_writes_enabled

            # The card's Allow is the request's write plan: the gate admits exactly this write, nobody is asked.
            assert chat_connector_writes_enabled(context)
            assert await plan_decision(tool_name, params, context) is None
            state["jira_calls"].append((tool_name, dict(params)))
            return dict(state["jira"])

        state["proposal"] = _ProposalProvider(proposal_key)
        monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", fake_tool)
        monkeypatch.setattr(control_plane_module, "resolve_control_plane_runtimes", fake_runtimes)
        monkeypatch.setattr(providers_module, "get_provider", state["proposal"])
        monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
        monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", model)
        monkeypatch.setattr("app.services.workflow_runs.records.start_run", fake_start_run)
        return state

    return install


KITCHEN_HELPER_SETUP = {"test_commands": [".venv/bin/python -m pytest -v"], "pr_target_branch": "main"}


async def _workspace(db, *, both_coding: bool = False) -> str:
    """A Workspace with two repository records registered from the knowledge snapshot,
    octryx/kitchen-helper (Bitbucket Cloud, with its coding setup) and SHOP/demo-shop (Bitbucket Server)."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"phased-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(UserProject(user_id=admin.id, project_id=project.id, role="owner"))
    for key, remote, name, setup in (
            ("bitbucket-octryx-kitchen-helper", "https://bitbucket.org/octryx/kitchen-helper", "octryx/kitchen-helper", KITCHEN_HELPER_SETUP),
            ("bitbucket-shop-demo-shop", "https://scm.example.test/bitbucket/projects/SHOP/repos/demo-shop",
             "bitbucket/projects/SHOP/repos/demo-shop", KITCHEN_HELPER_SETUP if both_coding else None)):
        source = KnowledgeSourceConnector(project_id=project.id, connector_key=key, kind="git_repository",
                                          scope={"fetch_mode": "remote_git", "remote": remote, "ref": "main"})
        db.add(source)
        await db.flush()
        config = {"central_source": {"mode": "knowledge_snapshot", "connector_id": source.id},
                  **({"coding_setup": setup} if setup else {})}
        db.add(CodeRepository(project_id=project.id, name=name, repo_root=f"/central-repositories/{source.id}",
                              provider="knowledge_snapshot", config_json=config, is_active=True))
    await db.commit()
    return project.id


async def _settle(session_id: str) -> None:
    for _ in range(3):
        task = CHAT_RUN_TASKS.get(session_id)
        if task is None:
            return
        await asyncio.wait_for(asyncio.shield(task), timeout=60)
        await asyncio.sleep(0)


async def _send(client, auth_headers, *, project_id: str, prompt: str = IDEA, workflow_key: str = "") -> str:
    body = {"prompt": prompt, "project_id": project_id, "session_id": ""}
    if workflow_key:
        body["workflow_key"] = workflow_key
    response = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    session_id = response.json()["selectedSession"]["id"]
    await _settle(session_id)
    return session_id


async def _record(db, session_id: str) -> dict:
    db.expire_all()
    session = await db.get(ChatSession, session_id)
    return session.metadata_[ROUTING_RESOLUTION_KEY]["workflow_proposal"]


async def _approval(db, session_id: str) -> Approval:
    [approval] = (await db.execute(select(Approval).where(Approval.session_id == session_id))).scalars().all()
    return approval


async def _answer(client, auth_headers, session_id: str, proposal_id: str, decision: str, **extra):
    response = await client.post(f"/chat/api/sessions/{session_id}/workflow-proposal",
                                 json={"proposal_id": proposal_id, "decision": decision, **extra},
                                 headers=auth_headers)
    await _settle(session_id)
    return response


async def _items(db, project_id: str) -> list[WorkItem]:
    db.expire_all()
    return list((await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all())
