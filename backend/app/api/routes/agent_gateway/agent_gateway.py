"""Agent gateway client control plane: the endpoints the octryx-claude hooks call."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.agent_board.handoff_trigger import safe_handoff_now
from ....services.agent_gateway.contract import GATEWAY_CLIENT, STATE_ALLOWED, STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ....services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ....services.agent_gateway.policy import load_workspace_policy
from ....services.agent_gateway.presence import session_key_hash
from ....services.agent_gateway.seat_policy import workspace_seat_decision
from ....services.agent_gateway.session_activity import ACTIVITY_APPROVAL, ACTIVITY_WORKING, note_activity
from ....services.agent_gateway.tool_check import DECISION_DENY
from ....services.agent_gateway.tool_decision import decide_tool_check
from ....services.agent_gateway.tool_execution import STATE_RECORDED, record_tool_execution
from ....services.content_routing.client_conversation import note_conversation, route_answer
from ....services.content_routing.client_tool_results import launcher_tool_result
from ....services.model_gateway.inbound.model_routes import launcher_picker
from ....services.policy_engine.principals import load_principal_isolated
from ....services.policy_engine.request_principal import load_seat_principal
from ....services.prompt_catalog import prompt_set_scope
from ....services.prompt_catalog.out_of_turn import prompt_set_for
from ....services.skill_catalog.usage import record_tool_check
from ....services.workflow_runs.octryx.hooks import session_contract
from . import (
    agent_gateway_budget,
    agent_gateway_engine,
    agent_gateway_handoff,
    agent_gateway_heartbeat,
    agent_gateway_mobile,
    agent_gateway_pet,
    agent_gateway_presence,
    agent_gateway_session_reports,
    agent_gateway_skills,
    agent_gateway_transcripts,
)
from ._agent_gateway_http import (
    REASON_HOOK_EVENT_UNSUPPORTED,
    REASON_POLICY_INVALID,
    _bounded_json,
    _from_refusal,
    _identity_and_session,
    _refusal,
)

router = APIRouter(prefix="/api/v1/agent-gateway", tags=["agent-gateway"])
router.include_router(agent_gateway_presence.router)
router.include_router(agent_gateway_handoff.router)
router.include_router(agent_gateway_skills.router)
router.include_router(agent_gateway_budget.router)
router.include_router(agent_gateway_engine.router)
router.include_router(agent_gateway_pet.router)
router.include_router(agent_gateway_mobile.router)
router.include_router(agent_gateway_heartbeat.router)
router.include_router(agent_gateway_transcripts.router)

# Explicit body limits. A PreToolUse input carries the tool input (a Write carries the whole file).
MAX_TOOL_CHECK_BODY_BYTES = 2 * 1024 * 1024
# A PostToolUse input carries the Bash output; only the event, tool name and id are read.
MAX_TOOL_EXECUTED_BODY_BYTES = 2 * 1024 * 1024
_TOOL_CHECK_EVENTS = frozenset({"PreToolUse"})
_DENY_MESSAGE = "Octryx could not govern this tool call ({reason}). Restart the session through octryx-claude."


def _tool_deny(state: str, reason: str, status: int) -> JSONResponse:
    return _refusal(
        state,
        reason,
        status,
        decision=DECISION_DENY,
        rule_id=None,
        message=_DENY_MESSAGE.format(reason=reason),
    )


async def workspace_system_test_commands(db: AsyncSession, workspace_id: str | None) -> list[str]:
    from ....services.workflow_runs.octryx.system_tests import declared_system_test_commands

    return await declared_system_test_commands(db, workspace_id)


async def _permissive_only(db: AsyncSession) -> bool:
    from ....services.agent_gateway.local_models import permissive_only

    return await permissive_only(db)


async def _codex_seat(db: AsyncSession, identity: Any) -> dict[str, Any]:
    from ....services.agent_gateway.engine_keys import ENGINE_CODEX, REASON_ENGINE_NOT_ALLOWED
    from ....services.agent_gateway.engine_policy import effective_engine

    decision = await workspace_seat_decision(db, identity.workspace_id, principal=await load_seat_principal(
        identity.user.id, session_id=f"launch:{session_key_hash(identity.session_key)}", client=GATEWAY_CLIENT),
        codex=True)
    reason = decision.reason or None
    if decision.allowed and ENGINE_CODEX not in (await effective_engine(
            db, user_id=identity.user.id, workspace_id=identity.workspace_id)).allowed:
        reason = REASON_ENGINE_NOT_ALLOWED
    return {"codex_seat_mode": decision.seat_mode, "allowed": reason is None, "reason": reason}


@router.get("/client-policy")
async def client_policy(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    loaded = await load_workspace_policy(db, identity.workspace_id)
    if loaded.policy is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, loaded.reason, 409, policy_source=loaded.source)
    policy = loaded.policy
    # The seat question is asked for this user and this launcher (by its key's hash, never the key).
    seat = await workspace_seat_decision(db, identity.workspace_id, principal=await load_seat_principal(
        identity.user.id, session_id=f"launch:{session_key_hash(identity.session_key)}", client=GATEWAY_CLIENT))
    codex_seat = await _codex_seat(db, identity)
    return {
        "state": STATE_ALLOWED,
        # Whether ``octryx-claude --profile seat`` may start here, with the fixed reason when not.
        "seat": {"seat_mode": seat.seat_mode, "reason": seat.reason or None},
        # Whether ``octryx codex --profile seat`` (the person's own ChatGPT login) may start here.
        "codex_seat": codex_seat,
        # Local model licences the launcher may use (``local_models``; default only permissive ones).
        "local_models": {"permissive_only": await _permissive_only(db)},
        "policy_source": policy.source,
        "workspace_id": identity.workspace_id,
        "permissions": {"deny": list(policy.deny_permissions), "ask": list(policy.ask_permissions),
                        "allow": list(policy.allow_permissions),
                        # Bypass mode like plain Claude Code, unless the Workspace switches it off;
                        # the platform's PreToolUse check and the deny rules still run in bypass mode.
                        "bypass_permissions": str(policy.raw.get("bypass_permissions") or "allowed")},
        "verification": {
            "state": "configured" if policy.verification is not None else STATE_NEEDS_CONFIGURATION,
        },
        "tool_rules": len(policy.tool_rules),
        # Workspace data the launcher writes into Claude Code's sandbox network settings.
        "sandbox": {"allowed_domains": list(policy.sandbox_allowed_domains),
                    # Allow by default: ``open`` reaches any external domain (the platform host
                    # stays denied; uploads and secret reads stay hard rules); ``allowlist`` only the list above.
                    "network": _sandbox_network(policy.raw),
                    # The repositories' declared system test commands run outside the sandbox (``system_tests``).
                    "unsandboxed_commands": await workspace_system_test_commands(db, identity.workspace_id)},
        # The /model picker rows per profile; the launcher writes them into its ``modelPicker``.
        "models": await launcher_picker(db, identity, seat),
        # with the Workspace's switch on, the launcher uploads the full transcript (default off).
        "session_transcripts": {"enabled": (policy.raw.get("session_transcripts") or {}).get("enabled") is True},
    }


@router.post("/sessions/tool-check")
async def tool_check(request: Request, db: AsyncSession = Depends(get_db)):
    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _tool_deny(resolved.state, resolved.reason, resolved.http_status)
    identity, session = resolved
    body = await _bounded_json(request, MAX_TOOL_CHECK_BODY_BYTES)
    if isinstance(body, tuple):
        return _tool_deny(STATE_DENIED, *body)
    if body.get("hook_event_name") not in _TOOL_CHECK_EVENTS:
        return _tool_deny(STATE_NEEDS_CONFIGURATION, REASON_HOOK_EVENT_UNSUPPORTED, 400)
    loaded = await load_workspace_policy(db, identity.workspace_id)
    if loaded.policy is None:
        return _tool_deny(STATE_NEEDS_CONFIGURATION, loaded.reason or REASON_POLICY_INVALID, 409)
    # Gateway refusal texts are catalog data, resolved at the identity's Workspace (no turn is bound).
    with prompt_set_scope(await prompt_set_for(db, workspace_id=identity.workspace_id)):
        # The helper leaves the commit to this route, so its records share one transaction with the updates below.
        answer = await decide_tool_check(
            db, session=session, session_key=identity.session_key, policy=loaded.policy, hook_input=body,
            grant_id=identity.grant_id,
        )
    await record_tool_check(db, hook_input=body, answer=answer, user_id=identity.user.id,
                            project_id=identity.workspace_id, session_id=session.id)  # Skill calls only
    trigger = await safe_handoff_now(db, session_key=identity.session_key)
    await note_activity(db, identity.session_key,  # Octryx Mobile: the phone shows what the session does
                        ACTIVITY_APPROVAL if answer.get("decision") == "ask" else ACTIVITY_WORKING)
    await db.commit()
    return {**answer, "policy_source": loaded.source, **trigger}


@router.post("/sessions/tool-executed")
async def tool_executed(request: Request, db: AsyncSession = Depends(get_db)):
    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_TOOL_EXECUTED_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    record = await record_tool_execution(db, session=session, hook_input=body)
    if record.state != STATE_RECORDED:
        return _refusal(record.state, record.reason, record.http_status)
    # The finished tool's output through the tool-result check (counts and policy back, never stored).
    principal = await load_principal_isolated(session.user_id, session_id=session.id, metadata=session.metadata_)
    content = await launcher_tool_result(body, workspace_id=identity.workspace_id, session_id=session.id,
                                         principal=principal)
    route = await route_answer(db, session.id, note_conversation(session, body))  # the terminal notice
    trigger = await safe_handoff_now(db, session_key=identity.session_key)
    contract = await session_contract(db, session)  # A run-bound session sees its current phase
    from ....services.workflow_checks.test_brief import hook_brief

    test_brief = await hook_brief(db, identity.workspace_id, body)  # a long test run, cut for the agent
    await note_activity(db, identity.session_key, ACTIVITY_WORKING)
    await db.commit()
    return {**record.to_payload(), **trigger, **({"content": content} if content else {}), **route,
            **({"workflow_run": contract} if contract else {}), **({"test_brief": test_brief} if test_brief else {})}


def _sandbox_network(raw: dict[str, Any]) -> str:
    from ....services.devices.device_runs_keys import device_runs_section, tool_defaults

    return str(tool_defaults(device_runs_section(raw or {}))["network"])


# Included after the routes above so the registration order stays the same.
router.include_router(agent_gateway_session_reports.router)
