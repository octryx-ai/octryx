"""Policy UX: the coding-agent tool check knows the Workspace classification.

A gateway check that builds its Workspace entity from the id only never matches "classification at least …" for
run_command / read_path / write_path. The check resolves the classification like the other points; the baseline's
gateway policies never read it (shadow equality holds).
"""

from __future__ import annotations

import uuid

import pytest

from app.models import Project, Session
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.model_gateway.data_policy.classification import WorkspaceDataClassification
from app.services.policy_engine import catalog
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json
from app.services.policy_engine.gateway_point import gateway_query
from app.services.policy_engine.workspace_facts import (
    clear_workspace_facts_cache,
    load_workspace_classification_isolated,
)
from tests.policy_engine_support import BASE, bearer, make_user, use_custom_policies

CONFIDENTIAL_UP = render(model_from_json({"id": "no-ls-confidential", "actions": ["run_command"],
                                          "what": {"programs": ["ls"]},
                                          "where": {"classification_at_least": "confidential"}})[0])


async def _workspace(db, level: str | None) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={"data_policy": {"classification": level}} if level else {})
    db.add(project)
    await db.commit()
    return project.id


async def _session(db, workspace_id: str) -> Session:
    session = Session(id=str(uuid.uuid4()), user_id=await make_user(db, admin=False), project_id=workspace_id,
                      agent_type="external_agent", status="active", metadata_={"client": "octryx-claude"})
    db.add(session)
    await db.commit()
    return session


def _bash(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


def test_the_gateway_query_carries_the_classification():
    policy = build_policy(BASELINE_POLICY, source="baseline")
    confidential = WorkspaceDataClassification("confidential", "project_config", "")
    query = gateway_query(workspace_id="ws", gateway=policy, hook_input=_bash("ls"), principal=None,
                          principal_records=[], classification=confidential)
    workspace = next(item for item in query.entities if item["uid"]["type"] == "Workspace")
    assert workspace["attrs"]["classification"] == "confidential" and workspace["attrs"]["classification_rank"] == 300
    bare = gateway_query(workspace_id="ws", gateway=policy, hook_input=_bash("ls"), principal=None,
                         principal_records=[])
    attrs = next(item for item in bare.entities if item["uid"]["type"] == "Workspace")["attrs"]
    assert "classification" not in attrs and "classification_rank" not in attrs


def test_the_catalog_offers_classification_blocks_for_coding_agent_actions():
    assert "run_command" in catalog.block_info("where.classification_at_least")["actions"]
    model, issues = model_from_json({"id": "x", "actions": ["read_path"], "what": {"paths": ["*.env"]},
                                     "where": {"classification_is": ["restricted"]}})
    assert model is not None and issues == []


@pytest.mark.asyncio
async def test_a_classification_policy_now_bites_at_the_coding_agent_check(client, db):
    clear_workspace_facts_cache()
    confidential, internal = await _workspace(db, "confidential"), await _workspace(db, "internal")
    use_custom_policies(CONFIDENTIAL_UP, mode="enforce")
    policy = build_policy(BASELINE_POLICY, source="baseline")
    denied = await decide_tool_check(db, session=await _session(db, confidential), session_key="k", policy=policy,
                                     hook_input=_bash("ls -la"))
    assert denied["decision"] == "deny" and denied["rule_id"] == "no-ls-confidential"
    allowed = await decide_tool_check(db, session=await _session(db, internal), session_key="k", policy=policy,
                                      hook_input=_bash("ls -la"))
    assert allowed["decision"] == "allow"


@pytest.mark.asyncio
async def test_the_classification_is_resolved_once_per_workspace_and_unresolved_when_missing(client, db):
    clear_workspace_facts_cache()
    workspace = await _workspace(db, "restricted")
    first = await load_workspace_classification_isolated(workspace)
    assert first.classification == "restricted"
    project = await db.get(Project, workspace)
    project.config = {"data_policy": {"classification": "public"}}
    await db.commit()
    assert (await load_workspace_classification_isolated(workspace)).classification == "restricted", "cached"
    clear_workspace_facts_cache()
    assert (await load_workspace_classification_isolated(workspace)).classification == "public"
    assert not (await load_workspace_classification_isolated("")).resolved
    assert not (await load_workspace_classification_isolated(await _workspace(db, None))).resolved


@pytest.mark.asyncio
async def test_the_bench_answers_coding_agent_questions_with_the_classification(client, db):
    admin = await make_user(db, admin=True)
    workspace = await _workspace(db, "confidential")
    answer = (await client.post(f"{BASE}/test-bench", headers=bearer(admin), json={
        "workspace_id": workspace, "action": "run_command", "resource": {"command": "ls x"},
        "policies": CONFIDENTIAL_UP})).json()
    assert answer["decision"] == "deny" and [item["id"] for item in answer["determining"]] == ["no-ls-confidential"]
