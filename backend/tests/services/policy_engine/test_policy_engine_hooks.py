"""The shadow hooks at the real enforcement points, and "shadow never changes a live decision"."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import PolicyDecisionLog, Project, Session
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY, classification_tool_decision
from app.services.knowledge.embedding.port import EmbeddingError
from app.services.knowledge.embedding.selection import admit_space, embedding_config_from_environment
from app.services.model_gateway.data_policy.classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    WorkspaceDataClassification,
)
from app.services.model_gateway.litellm.project_admission import build_project_model_admission
from app.services.policy_engine import engine as engine_module
from app.services.policy_engine import runtime as runtime_module
from app.services.policy_engine.decision_log import pending_records
from app.services.policy_engine.runtime import (
    PolicyRuntime,
    current_runtime,
    maintain_policy_runtime,
    set_policy_runtime,
)
from app.services.policy_engine.shadow import custom_fallback_counters, decision_counters, reset_shadow_state
from app.services.project import get_project_config
from tests.policy_engine_support import make_user, use_custom_policies

REMOTE_SPACE = "bedrock_titan2_1024_v1"
KUBECTL_FORBID = ('@id("no-kubectl-reads")\nforbid (principal, action == Action::"read_connector", '
                  'resource in ConnectorFamily::"kubernetes");\n'
                  '@id("secrets-only-in-non-prod")\nforbid (principal, action == Action::"run_command", resource)\n'
                  'when { resource.prefixes.contains("kubectl get secrets") && '
                  '!resource.argument_values.contains("--context=nonprod") };\n')


async def _workspace(db, level: str | None = "internal", **config) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={**({"data_policy": {"classification": level}} if level else {}), **config})
    db.add(project)
    await db.commit()
    return project.id


async def _session(db, workspace_id: str) -> Session:
    user_id = await make_user(db, admin=False)
    session = Session(id=str(uuid.uuid4()), user_id=user_id, project_id=workspace_id, agent_type="external_agent",
                      status="active", metadata_={"client": "octryx-claude", "profile": "governed"})
    db.add(session)
    await db.commit()
    return session


class _SharedFactory:
    def __init__(self, db) -> None:
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return None


def _matches(point: str) -> int:
    counters = decision_counters().get(point, {})
    assert {key: value for key, value in counters.items() if value and key != "match"} == {}
    return counters.get("match", 0)


def _bash(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


@pytest.mark.asyncio
async def test_every_enforcement_point_is_shadowed(db, monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", REMOTE_SPACE)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    workspace_id = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    assert (await workspace_seat_decision(db, workspace_id)).allowed
    try:
        await admit_space(db, project_id=workspace_id, space=embedding_config_from_environment().space)
    except EmbeddingError:
        pass
    config = await get_project_config(workspace_id, db)
    assert config[CLASSIFICATION_TOOL_POLICY_KEY]["workspace_id"] == workspace_id
    assert classification_tool_decision("get_pod_logs", config).allowed
    admission = build_project_model_admission(
        project_id=workspace_id, project_config={"model_policy": {"allowed_aliases": ["octryx-a"]}}, source="test",
        data_classification=WorkspaceDataClassification("internal", CLASSIFICATION_SOURCE_PROJECT_CONFIG, ""),
    )
    assert admission.decide("octryx-a").allowed
    session = await _session(db, workspace_id)
    policy = build_policy(BASELINE_POLICY, source="baseline")
    answer = await decide_tool_check(db, session=session, session_key="k", policy=policy,
                                     hook_input=_bash("kubectl get pods"))
    assert answer["rule_id"] == "kubectl-requires-context"
    for point in ("seat", "remote_model", "tool_admission", "model_admission", "gateway_tool_check"):
        assert _matches(point) >= 1, point


@pytest.mark.asyncio
async def test_a_custom_forbid_is_recorded_but_never_changes_the_live_decision(db, monkeypatch):
    monkeypatch.setattr("app.db.core.async_session_factory", _SharedFactory(db))
    workspace_id = await _workspace(db)
    use_custom_policies(KUBECTL_FORBID)
    config = await get_project_config(workspace_id, db)
    assert classification_tool_decision("get_pod_logs", config).allowed
    session = await _session(db, workspace_id)
    policy = build_policy(BASELINE_POLICY, source="baseline")
    answer = await decide_tool_check(db, session=session, session_key="k", policy=policy,
                                     hook_input=_bash("kubectl get secrets --context prod"))
    assert answer["decision"] == "allow"
    allowed = await decide_tool_check(db, session=session, session_key="k", policy=policy,
                                      hook_input=_bash("kubectl get secrets --context nonprod"))
    assert allowed["decision"] == "allow"
    counters = decision_counters()
    assert counters["tool_admission"]["custom_policy"] == 1
    assert counters["gateway_tool_check"] == {"match": 1, "mismatch": 0, "custom_policy": 1, "error": 0}
    await maintain_policy_runtime()
    assert pending_records() == 0
    rows = (await db.execute(select(PolicyDecisionLog).order_by(PolicyDecisionLog.point))).scalars().all()
    gateway = next(row for row in rows if row.point == "gateway_tool_check")
    assert gateway.determining == ["secrets-only-in-non-prod"] and gateway.decision == "deny"
    assert gateway.legacy_decision == "allow" and gateway.outcome == "custom_policy"
    assert gateway.principal == f"AgentSession::{session.id}" and gateway.custom_version == 1
    assert gateway.resource.startswith("Bash kubectl args sha256:") and "secrets" not in gateway.resource


@pytest.mark.asyncio
async def test_an_engine_failure_never_changes_the_live_decision(db, monkeypatch):
    workspace_id = await _workspace(db)
    config = await get_project_config(workspace_id, db)

    def broken(*_args, **_kwargs):
        raise RuntimeError("engine down")

    monkeypatch.setattr("app.services.policy_engine.shadow.evaluate", broken)
    assert classification_tool_decision("run_kubectl", config, {"args": "get pods"}).allowed
    session = await _session(db, workspace_id)
    answer = await decide_tool_check(db, session=session, session_key="k",
                                     policy=build_policy(BASELINE_POLICY, source="baseline"),
                                     hook_input=_bash("git push origin main"))
    assert answer["decision"] == "deny" and answer["rule_id"] == "no-push-to-main"
    assert decision_counters()["tool_admission"]["error"] == 1
    assert decision_counters()["gateway_tool_check"]["error"] == 1
    reset_shadow_state()


@pytest.mark.asyncio
async def test_an_invalid_published_set_is_not_applied_and_the_baseline_still_decides(db):
    workspace_id = await _workspace(db)
    config = await get_project_config(workspace_id, db)
    set_policy_runtime(PolicyRuntime(custom_text="not cedar", custom_digest="sha256:x", custom_version=3,
                                     custom_invalid=True, loaded_at=1e18))
    assert classification_tool_decision("list_jira_issues", config).allowed
    assert decision_counters()["tool_admission"]["match"] == 1
    assert custom_fallback_counters() == {"tool_admission": 1}
    assert pending_records() == 0
    reset_shadow_state()


@pytest.mark.asyncio
async def test_off_mode_evaluates_nothing(db):
    workspace_id = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    set_policy_runtime(PolicyRuntime(mode="off", loaded_at=1e18))
    await workspace_seat_decision(db, workspace_id)
    config = await get_project_config(workspace_id, db)
    classification_tool_decision("run_kubectl", config)
    assert decision_counters() == {}


@pytest.mark.asyncio
async def test_the_runtime_reloads_from_its_own_session_and_survives_a_failure(db, monkeypatch):
    from app.models import SystemConfig

    db.add(SystemConfig(key="policy_engine.mode", value="off"))
    await db.commit()

    monkeypatch.setattr("app.db.core.async_session_factory", _SharedFactory(db))
    await maintain_policy_runtime(force=True)
    assert current_runtime().mode == "off"

    async def broken(_session):
        raise RuntimeError("db down")

    monkeypatch.setattr(runtime_module, "refresh_policy_runtime", broken)
    await maintain_policy_runtime(force=True)
    assert current_runtime().mode == "off"


def test_engine_rejects_an_unparseable_set():
    with pytest.raises(engine_module.PolicySetInvalidError):
        engine_module.compile_policy_set("forbid (principal, action, resource")


def test_forbid_wins_over_every_permit_and_names_itself():
    principal = engine_module.EntityRef("User", "u")
    resource = engine_module.EntityRef("Tool", "t")
    request = engine_module.CedarRequest(principal, "call_tool", resource, {
        "workspace": {"__entity": {"type": "Workspace", "id": "w"}}, "reads_logs": False, "writes": False, "connections": []})
    entities = [
        {"uid": {"type": "User", "id": "u"}, "attrs": {"platform_admin": True}, "parents": []},
        {"uid": {"type": "Workspace", "id": "w"}, "attrs": {"seat_mode": "allowed", "requires_governed_routing": False},
         "parents": []},
        {"uid": {"type": "Tool", "id": "t"}, "attrs": {"name": "t"}, "parents": []},
    ]
    permits = ('@id("p1") permit (principal, action, resource);\n'
               '@id("p2") permit (principal, action == Action::"call_tool", resource);\n')
    allowed = engine_module.evaluate(engine_module.compile_policy_set(permits), [request], entities)
    assert allowed.allowed and set(allowed.determining) == {"p1", "p2"}
    denied = engine_module.evaluate(
        engine_module.compile_policy_set(permits + '@id("f") forbid (principal, action, resource == Tool::"t");'),
        [request], entities)
    assert (denied.allowed, denied.determining) == (False, ("f",))
    erroring = engine_module.evaluate(
        engine_module.compile_policy_set(permits + '@id("e") forbid (principal, action, resource) when { resource.nope };'),
        [request], entities)
    assert not erroring.allowed and erroring.errors


def test_a_custom_forbid_does_not_hide_a_baseline_disagreement():
    from app.services.policy_engine.entities import principal_entities, tool_entity, workspace_entity
    from app.services.policy_engine.points import PointQuery
    from app.services.policy_engine.shadow import LegacyDecision, shadow_decision

    use_custom_policies('@id("no-t")\nforbid (principal, action == Action::"call_tool", resource == Tool::"t");\n')
    principal, records = principal_entities("u")
    workspace, workspace_record = workspace_entity("w")
    tool, tool_record = tool_entity("t", None)
    request = engine_module.CedarRequest(principal, "call_tool", tool, {
        "workspace": {"__entity": workspace.to_json()}, "reads_logs": False, "writes": False, "connections": []})
    no_permit = PointQuery("tool_admission", "call_tool", "w", principal, "Tool::t", "", (request,),
                           (*records, workspace_record, tool_record))
    comparison = shadow_decision("tool_admission", LegacyDecision(True), lambda: no_permit)
    assert comparison.outcome == "mismatch" and comparison.determining == ("no-t",)
    reset_shadow_state()
