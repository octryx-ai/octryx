"""Contract tests for the agent gateway client control plane (octryx-claude hooks)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import KnowledgeChunk, Message, Project, Session, ToolCall, UsageEvent, User
from app.models.security.oauth_provider import OAuthGrant
from app.services.admin.project.admin_project_config_service import merge_project_config
from app.services.agent_gateway.command_match import command_segments, segment_has_argument, segment_matches
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.agent_gateway.identity import resolve_gateway_identity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.oauth_provider import mint_access_token
from app.time_utils import utc_now

BASE = "/api/v1/agent-gateway"


def _matches(command: str, prefix: list[str]) -> bool:
    return any(segment_matches(segment, prefix) for segment in command_segments(command) or [])


@pytest.mark.parametrize(
    ("command", "prefix", "expected"),
    [
        ("git push origin main", ["git", "push", "origin", "main"], True),
        ("cd repo && git status; git push origin main", ["git", "push", "origin", "main"], True),
        ("ls | grep x || git push origin main", ["git", "push", "origin", "main"], True),
        ("FOO=1 BAR='a b' /usr/bin/git push origin main", ["git", "push", "origin", "main"], True),
        ("echo git push origin main", ["git", "push", "origin", "main"], False),
        ("git push origin main-feature", ["git", "push", "origin", "main"], False),
        ("bash -c 'git push origin main'", ["git", "push", "origin", "main"], True),
        ('echo "$(git push origin main)"', ["git", "push", "origin", "main"], True),
        ("cd backend && DEBUG=true /x/.venv/bin/python -m pytest tests/a.py -q", ["python", "-m", "pytest"], True),
        ("python -m pip install pytest", ["python", "-m", "pytest"], False),
    ],
)
def test_command_prefix_matching_is_structural(command, prefix, expected):
    assert _matches(command, prefix) is expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kubectl get pods", False),
        ("kubectl --context=dev get pods", True),
        ("kubectl get pods --context dev", True),
        ("echo --context && kubectl get pods", False),
    ],
)
def test_requires_argument_is_checked_in_the_matching_segment(command, expected):
    segment = next(s for s in command_segments(command) if segment_matches(s, ["kubectl"]))
    assert segment_has_argument(segment, "--context") is expected


def test_unbalanced_command_is_unparseable_but_heredoc_bodies_are_data():
    assert command_segments("echo 'unbalanced") is None
    segments = command_segments("cat > notes.md <<'EOF'\ndon't stop\nEOF\ngit push --force")
    assert segments == [("cat",), ("git", "push", "--force")]


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _workspace(db, *, policy: dict | None = None) -> Project:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    config = dict(project.config or {})
    config.pop("agent_gateway_policy", None)
    if policy is not None:
        config["agent_gateway_policy"] = policy
    project.config = config
    await db.commit()
    return project


async def _gateway(db, project: Project) -> tuple[dict[str, str], Session]:
    admin = await _admin(db)
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_gw_{uuid.uuid4().hex[:6]}", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id,
        client_id=grant.client_id,
        grant_id=grant.id,
        scopes=[SCOPE_MODEL_INVOKE],
        resource=GATEWAY_AUDIENCE,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Octryx-Session": str(uuid.uuid4()),
        "X-Octryx-Workspace": project.id,
    }
    identity = await resolve_gateway_identity(db, {key.lower(): value for key, value in headers.items()})
    session = await get_or_create_gateway_session(db, identity)
    await db.commit()
    return headers, session


def _pre_tool_use(tool_name: str, tool_input: dict) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "claude-local",
        "cwd": "/work/repo",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": f"toolu_{uuid.uuid4().hex[:8]}",
    }


@pytest.mark.asyncio
async def test_policy_validation_rejects_an_unknown_rule_kind(db, auth_user):
    project = await _workspace(db)
    with pytest.raises(HTTPException) as excinfo:
        await merge_project_config(
            db,
            project_id=project.id,
            patch={"agent_gateway_policy": {"tool_rules": [{"id": "x", "kind": "regex_denied", "pattern": "rm"}]}},
            actor_user_id=auth_user.id,
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "agent_gateway_policy.tool_rules[0].kind: unknown_rule_kind"


@pytest.mark.asyncio
async def test_client_policy_without_workspace_policy_is_the_explicit_baseline(client, db):
    headers, _ = await _gateway(db, await _workspace(db))
    response = await client.get(f"{BASE}/client-policy", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["policy_source"] == "baseline"
    assert "Read(~/.aws/**)" in payload["permissions"]["deny"]
    assert payload["verification"]["state"] == "needs_configuration"


@pytest.mark.asyncio
async def test_tool_check_denial_is_recorded_and_allow_is_not(client, db):
    headers, session = await _gateway(db, await _workspace(db))

    denied = await client.post(
        f"{BASE}/sessions/tool-check",
        headers=headers,
        json=_pre_tool_use("Bash", {"command": "AWS_PROFILE=x kubectl get pods"}),
    )
    allowed = await client.post(
        f"{BASE}/sessions/tool-check",
        headers=headers,
        json=_pre_tool_use("Bash", {"command": "kubectl --context=dev get pods"}),
    )
    env_read = await client.post(
        f"{BASE}/sessions/tool-check", headers=headers, json=_pre_tool_use("Read", {"file_path": "backend/.env"})
    )

    assert denied.json()["decision"] == "deny"
    assert denied.json()["rule_id"] == "kubectl-requires-context"
    assert allowed.json() == {
        "decision": "allow",
        "state": "allowed",
        "reason": "no_rule_matched",
        "rule_id": None,
        "message": "",
        "policy_source": "baseline",
    }
    assert env_read.json()["rule_id"] == "no-env-files"
    rows = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert sorted(row.parameters["rule_id"] for row in rows) == ["kubectl-requires-context", "no-env-files"]
    assert {row.status for row in rows} == {"denied_by_policy"}
    assert {row.parameters["source"] for row in rows} == {"client_hook"}


@pytest.mark.asyncio
async def test_tool_check_without_session_denies_as_misconfigured(client, db):
    headers, _ = await _gateway(db, await _workspace(db))
    headers["X-Octryx-Session"] = str(uuid.uuid4())
    response = await client.post(
        f"{BASE}/sessions/tool-check", headers=headers, json=_pre_tool_use("Bash", {"command": "ls"})
    )
    assert response.json()["decision"] == "deny"
    assert (response.json()["state"], response.json()["reason"]) == ("needs_configuration", "session_not_found")


VERIFYING_POLICY = {
    "verification": {
        "test_command_prefixes": [["pytest"], ["python", "-m", "pytest"]],
        "change_tools": ["Edit", "Write", "MultiEdit", "NotebookEdit"],
    },
    "tool_rules": [],
}


def _gateway_row(session: Session, tool: str, *, at, is_error: bool | None, command: str = "") -> ToolCall:
    parameters = {"source": "model_gateway", "tool_use_id": uuid.uuid4().hex, "block_index": 0, "input": {}}
    if command:
        parameters["command"] = command
    status = "requested" if is_error is None else ("error" if is_error else "success")
    result = None if is_error is None else {"is_error": is_error, "excerpt": ""}
    return ToolCall(
        session_id=session.id, tool_name=tool, parameters=parameters, result=result, status=status, created_at=at
    )


@pytest.mark.asyncio
async def test_verification_states_follow_the_last_change_and_the_last_test(client, db):
    headers, session = await _gateway(db, await _workspace(db, policy=VERIFYING_POLICY))
    stop = {"hook_event_name": "Stop", "stop_hook_active": False}
    start = utc_now()

    async def verify() -> dict:
        response = await client.post(f"{BASE}/sessions/verification", headers=headers, json=stop)
        assert response.status_code == 200
        return response.json()

    db.add(_gateway_row(session, "Read", at=start, is_error=False))
    await db.commit()
    assert (await verify())["state"] == "not_applicable"

    db.add(_gateway_row(session, "Edit", at=start + timedelta(seconds=1), is_error=False))
    await db.commit()
    blocked = await verify()
    assert (blocked["state"], blocked["reason"]) == ("blocked", "no_test_after_last_change")
    assert blocked["detail"].startswith("Octryx gate:")
    assert blocked["memory_capture"] == "turn_continues"

    failed_test = _gateway_row(
        session, "Bash", at=start + timedelta(seconds=2), is_error=True, command="cd b && pytest tests/x.py"
    )
    # Execution evidence from the PostToolUseFailure hook: the test ran and failed.
    failed_test.parameters = {**failed_test.parameters, "executed": {"outcome": "failed", "source": "client_hook"}}
    db.add(failed_test)
    await db.commit()
    failed = await verify()
    assert (failed["state"], failed["reason"]) == ("blocked", "last_test_failed")

    db.add(
        _gateway_row(
            session, "Bash", at=start + timedelta(seconds=3), is_error=False, command="python -m pytest tests/x.py"
        )
    )
    await db.commit()
    passed = await verify()
    assert (passed["state"], passed["last_change_tool"]) == ("passed", "Edit")
    assert passed["last_test_command"] == "python -m pytest tests/x.py"
    assert passed["memory_capture"] == "disabled"

    db.add(_gateway_row(session, "Write", at=start + timedelta(seconds=4), is_error=False))
    await db.commit()
    assert (await verify())["reason"] == "no_test_after_last_change"


@pytest.mark.asyncio
async def test_finalize_completes_the_session_without_touching_the_gateway_record(client, db):
    headers, session = await _gateway(db, await _workspace(db))
    admin = await _admin(db)
    db.add(
        UsageEvent(session_id=session.id, user_id=admin.id, provider="litellm", model="claude-sonnet-4-5", tokens_in=10)
    )
    db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="fix the sync"))
    db.add(_gateway_row(session, "Edit", at=utc_now(), is_error=False))
    await db.commit()

    response = await client.post(
        f"{BASE}/sessions/finalize",
        headers=headers,
        json={
            "summary": "Fixed the sync.",
            "transcript_digest": ("[USER] fix the sync api_key=sk-li" + "ve-1234567890abcdef\n\n[ASSISTANT] Fixed it."),
            "workspace_ref": "/work/repo",
            "claude_session_id": "claude-local",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert (payload["state"], payload["external_session_id"]) == ("finalized", session.id)
    await db.refresh(session)
    assert session.status == "completed" and session.ended_at is not None
    for model in (UsageEvent, Message, ToolCall):
        count = len((await db.execute(select(model).where(model.session_id == session.id))).scalars().all())
        assert count == 1, model.__name__
    # The digest feeds the knowledge graph (redacted); the retired KnowledgeMap copy is gone.
    assert "knowledge_entry_id" not in payload
    chunks = (
        await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_ref == f"agent-session:{session.id}"))
    ).scalars().all()
    assert chunks and all(("sk-li" + "ve-1234567890abcdef") not in chunk.text for chunk in chunks)
