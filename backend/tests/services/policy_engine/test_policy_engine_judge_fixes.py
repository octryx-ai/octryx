"""Policy engine regression tests."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import AuditLog, PolicyDecisionLog, Project, Session, SystemConfig
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.policy_engine import decision_log, principals
from app.services.policy_engine import runtime as runtime_module
from app.services.policy_engine import shadow as shadow_module
from app.services.policy_engine.enforce import SHADOW_SINCE_CONFIG_KEY
from app.services.policy_engine.engine import PolicySetInvalidError
from app.services.policy_engine.gateway_point import gateway_query
from app.services.policy_engine.runtime import (
    AUDIT_CUSTOM_SET_INVALID,
    MODE_ENFORCE,
    current_runtime,
    refresh_policy_runtime,
)
from app.services.policy_engine.shadow import (
    LegacyDecision,
    PolicyComparison,
    custom_fallback_counters,
    decision_counters,
    reset_shadow_state,
    shadow_decision,
)
from app.services.policy_engine.shadow_record import _entry
from app.time_utils import utc_now
from tests.policy_engine_support import BASE, bearer, make_user, publish, use_custom_policies

FORBID = '@id("no-rollout-restart")\nforbid (principal, action == Action::"run_command", resource)\n' \
         'when { resource.prefixes.contains("kubectl rollout restart") };\n'
_LOOPBACK = "http://localhost:8090,http://127.0.0.1:8090"


async def _session(db) -> Session:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={"data_policy": {"classification": "internal"}})
    db.add(project)
    user_id = await make_user(db, admin=False)
    session = Session(id=str(uuid.uuid4()), user_id=user_id, project_id=project.id, agent_type="external_agent",
                      status="active", metadata_={"client": "octryx-claude", "profile": "governed"})
    db.add(session)
    await db.commit()
    return session


def _bash(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


class _OwnSession:
    def __init__(self) -> None:
        self.poisoned = False

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


@pytest.mark.asyncio
async def test_a_failing_principal_lookup_never_breaks_the_callers_commit(db, monkeypatch):
    session = await _session(db)
    own = _OwnSession()
    received = []

    async def failing_lookup(lookup_db, _user_id):
        received.append(lookup_db)
        if lookup_db is db:
            # What a failed statement does to a PostgreSQL transaction: the session is unusable until rollback.
            db.add(SystemConfig(key=None, value="x"))
            await db.flush()
        raise RuntimeError("relation user_roles does not exist")

    monkeypatch.setattr(principals, "user_roles_and_groups", failing_lookup)
    monkeypatch.setattr("app.db.core.async_session_factory", own)
    use_custom_policies(FORBID)
    answer = await decide_tool_check(db, session=session, session_key="k",
                                     policy=build_policy(BASELINE_POLICY, source="baseline"),
                                     hook_input=_bash("ls"))
    assert answer["decision"] == "allow"
    assert received == [own]
    db.add(SystemConfig(key=f"judge.{uuid.uuid4().hex[:8]}", value="committed"))
    await db.commit()
    assert decision_counters()["gateway_tool_check"]["match"] == 1


@pytest.mark.asyncio
async def test_a_principal_session_that_cannot_open_yields_the_user_without_roles(monkeypatch):
    def broken():
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr("app.db.core.async_session_factory", broken)
    principal, records = await principals.load_principal_isolated("u-1", session_id="s-1")
    assert principal.id == "s-1"
    assert records[0]["uid"] == {"type": "User", "id": "u-1"} and records[0]["parents"] == []


def _record() -> dict:
    return {
        "created_at": utc_now(), "point": "seat", "action": "use_seat", "outcome": "custom_policy", "mode": "shadow",
        "workspace_id": "w", "principal": "User::u", "resource": "Workspace::w", "decision": "deny",
        "legacy_decision": "allow", "determining": ["c"], "errors": [], "schema_version": "x", "latency_us": 1,
    }


@pytest.mark.asyncio
async def test_dropped_records_block_enforce_until_a_new_shadow_window(client, db, monkeypatch):
    admin = await make_user(db, admin=True)
    monkeypatch.setattr(decision_log, "_BUFFER", deque(maxlen=3))

    async def put(mode: str):
        return await client.put(f"{BASE}/mode", json={"mode": mode}, headers=bearer(admin))

    await client.put(f"{BASE}/settings", json={"enforce_window_hours": 1}, headers=bearer(admin))
    assert (await put("shadow")).status_code == 200
    since = await db.get(SystemConfig, SHADOW_SINCE_CONFIG_KEY)
    since.value = (utc_now() - timedelta(hours=2)).isoformat()
    await db.commit()
    for _ in range(5):
        decision_log.record_decision(_record())
    assert decision_log.dropped_records() == 2

    refused = await put("enforce")
    assert refused.status_code == 409
    assert refused.json()["detail"]["reasons"] == ["decision_log_records_dropped"]
    marker = (await db.execute(select(PolicyDecisionLog).where(PolicyDecisionLog.outcome == "dropped"))).scalar_one()
    assert marker.resource == "2 decision records dropped" and marker.errors == ["decision_log_records_dropped"]
    # The marker survives a restart (the in-process counter does not).
    decision_log.reset_dropped_records()
    status = (await client.get(f"{BASE}/status", headers=bearer(admin))).json()["enforce"]
    assert status["reasons"] == ["decision_log_records_dropped"] and status["dropped_records"] == 1

    assert (await put("off")).status_code == 200
    for _ in range(4):
        decision_log.record_decision(_record())
    assert decision_log.dropped_records() == 1
    assert (await put("shadow")).status_code == 200
    assert decision_log.dropped_records() == 0
    reasons = (await client.get(f"{BASE}/status", headers=bearer(admin))).json()["enforce"]["reasons"]
    assert reasons == ["window_not_elapsed"]


@pytest.mark.asyncio
async def test_the_published_set_is_retired_only_through_a_reviewed_empty_draft(client, db):
    version = await publish(client, db, FORBID)
    admin = await make_user(db, admin=True)
    refused = await client.post(f"{BASE}/policy-sets/{version}/retire", headers=bearer(admin))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "policy_set_retire_requires_review"
    assert current_runtime().custom_version == version

    empty = await publish(client, db, "")
    states = {item["version"]: item["state"]
              for item in (await client.get(f"{BASE}/policy-sets", headers=bearer(admin))).json()["items"]}
    assert states == {version: "retired", empty: "published"}
    assert current_runtime().custom_version == empty and current_runtime().custom_ids == frozenset()


def test_the_gateway_record_stores_the_tool_the_program_and_an_argument_hash_only():
    policy = build_policy(BASELINE_POLICY, source="baseline")
    principal = principals.principal_entities("u")
    secret = "PGPASSWORD=hunter2 psql -h db.internal -U alice && curl -H 'X-Token: s3cr3t' https://x/alice"
    query = gateway_query(workspace_id="ws", gateway=policy, hook_input=_bash(secret), principal=principal[0],
                          principal_records=principal[1])
    assert "s3cr3t" in query.resource  # the in-memory question keeps it (test bench)
    entry = _entry(query, LegacyDecision(True), PolicyComparison("mismatch", False), current_runtime(), None)
    assert entry["resource"].startswith("Bash psql | curl args sha256:")
    for leaked in ("hunter2", "alice", "s3cr3t", "db.internal", "https://"):
        assert leaked not in entry["resource"]
    other = gateway_query(workspace_id="ws", gateway=policy, hook_input=_bash(secret + " -v"), principal=principal[0],
                          principal_records=principal[1])
    assert other.log_resource != query.log_resource  # the hash correlates calls without revealing them

    read = gateway_query(workspace_id="ws", gateway=policy, principal=principal[0], principal_records=principal[1],
                         hook_input={"tool_name": "Read", "tool_input": {"file_path": "/home/alice/.aws/credentials"},
                                     "cwd": "/repo"})
    stored = _entry(read, LegacyDecision(True), PolicyComparison("mismatch", False), current_runtime(), None)
    assert stored["resource"].startswith("Read args sha256:") and "alice" not in stored["resource"]


@pytest.mark.asyncio
async def test_an_unparseable_published_set_is_alerted_audited_once_and_shown(client, db, monkeypatch):
    version = await publish(client, db, FORBID)
    admin = await make_user(db, admin=True)

    def no_longer_parses(_text):
        raise PolicySetInvalidError("schema", ("unknown attribute",))

    monkeypatch.setattr(runtime_module, "compile_policy_set", no_longer_parses)
    runtime = await refresh_policy_runtime(db)
    assert runtime.custom_invalid and runtime.custom_version == version
    await refresh_policy_runtime(db)
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_CUSTOM_SET_INVALID))).scalars().all()
    assert len(audits) == 1 and audits[0].details["fallback"] == "shadow" and audits[0].details["version"] == version

    runtime_module.set_policy_runtime(runtime_module.replace(current_runtime(), mode=MODE_ENFORCE, loaded_at=1e18,
                                                             custom_text="forbid (principal, action, resource"))
    comparison = shadow_decision("seat", LegacyDecision(True), lambda: _seat_query())
    assert comparison.custom_fallback and comparison.cedar_allowed is True and comparison.errors == ()
    assert shadow_module.enforced_denial(True, comparison) is None
    status = (await client.get(f"{BASE}/status", headers=bearer(admin))).json()
    assert status["custom"]["valid"] is False and status["custom"]["fallback"] == "shadow"
    assert status["custom_fallbacks"] == {"seat": 1}
    assert "custom_set_invalid" in status["enforce"]["reasons"]
    reset_shadow_state()
    assert custom_fallback_counters() == {}


def _seat_query():
    from app.services.data_classification.policy_rules import default_rules
    from app.services.policy_engine.points import seat_query

    return seat_query(workspace_id="ws", level="internal", rules=default_rules("internal"),
                      raw_policy={"seat_mode": "allowed"})


def test_startup_refuses_the_single_admin_declaration_outside_a_machine_local_stack():
    secure = {
        "jwt_secret": "policy-set-test-jwt-secret-0123456789",
        "encryption_key": "policy-set-test-encryption-key-0123",
        "admin_default_password": "policy-set-Test-Pw-12345",
        "admin_email": "admin@policy-set.test",
        "database_url": "postgresql+asyncpg://octryx:unused@postgres:5432/octryx",
        "force_secure_auth_cookies": True,
        "debug": False,
        "four_eyes_dev_self_approval": True,
    }
    with pytest.raises(ValidationError) as refused:
        Settings(**secure, runtime_profile="local", cors_allowed_origins="https://octryx.example.com")
    assert "self-approval exception is development-only" in str(refused.value)
    with pytest.raises(ValidationError):
        Settings(**secure, runtime_profile="production", cors_allowed_origins=_LOOPBACK)
    assert Settings(**secure, runtime_profile="staging", cors_allowed_origins=_LOOPBACK).four_eyes_dev_self_approval
    assert "policy_set_single_admin" not in Settings.model_fields


@pytest.mark.asyncio
async def test_the_publish_gate_rechecks_the_environment_of_the_single_admin_declaration(client, db, monkeypatch):
    from tests.policy_engine_support import approve

    author = await make_user(db, admin=True)
    monkeypatch.setattr(get_settings(), "four_eyes_dev_self_approval", True)
    monkeypatch.setattr(get_settings(), "cors_allowed_origins", "https://octryx.example.com")
    version = (await client.post(f"{BASE}/policy-sets", json={"policies": FORBID},
                                 headers=bearer(author))).json()["version"]
    approval_id = (await client.post(f"{BASE}/policy-sets/{version}/submit",
                                     headers=bearer(author))).json()["governance_approval_id"]
    await approve(db, approval_id, author)
    response = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                 json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "policy_set_self_approval"


def test_a_failure_while_recording_never_escapes_the_shadow_evaluation(monkeypatch):
    use_custom_policies('@id("no-seat")\nforbid (principal, action == Action::"use_seat", resource);')

    def broken_record(_entry):
        raise RuntimeError("buffer broken")

    monkeypatch.setattr(shadow_module, "record_decision", broken_record)
    comparison = shadow_decision("seat", LegacyDecision(True), lambda: _seat_query())
    assert comparison.outcome == "error" and comparison.cedar_allowed is None
    assert comparison.errors == ("RuntimeError",)
    assert shadow_module.enforced_denial(True, comparison) is None
    reset_shadow_state()
