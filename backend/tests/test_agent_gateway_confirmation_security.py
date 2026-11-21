"""A workflow confirmation cannot be forged or replayed by the session's own tools.

- the hook key is set once per session;
- a confirmation proof must carry the launcher's HMAC. A forged MAC, a missing proof, a stale
  timestamp or a reused nonce is denied, and no ticket is issued;
- a ticket is single use, bound to its approval and to Claude Code's tool_use id, and expires;
- ``workflow_confirm`` approves only over the native MCP channel with the hook-issued ticket. The
  REST tool endpoint is ``mcp_channel_required``;
- code-owned self-protection denies Bash and file tools that reach for the launcher's credentials
  or the platform's control endpoints (the curl pattern).
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, ToolCall
from app.services.agent_gateway.confirmation import (
    TOOL_CALL_STATUS_CONFIRMATION_ASKED,
    ask_for_confirmation,
    redeem_confirmation_ticket,
)
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.self_protection import self_protection_decision
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_workflow_tools import mcp_workflow_confirm, mcp_workflow_select
from tests.agent_gateway_hook_support import STATE_ROOT, confirm_hook_input, new_hook_key, register
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import phased_definition, publish_phased

SCOPES = ("knowledge:read", "workflow:read", "workflow:execute", "sessions:read")


async def _setup(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    from app.models.runtime.secure_work import WorkItem

    workflow_key = await publish_phased(db, phased_definition())
    db.add(WorkItem(source_type="jira", source_instance="t", source_key="PAY-51", title="x", project_id=workspace_id))
    await db.flush()
    session_key = str(uuid.uuid4())
    user = await fetch_user(db, member_id)
    identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=session_key, work_item_key="")
    gateway = await get_or_create_gateway_session(db, identity)
    caller = McpCaller(user_id=member_id, grant_id="mcp", scopes=SCOPES, workspace_header=workspace_id,
                       session_key=session_key, tool_use_id="toolu_confirm_1")
    pending = await mcp_workflow_select(db, caller=caller, user=user, workspace_id=workspace_id,
                                        arguments={"workflow_key": workflow_key, "work_item": "PAY-51"})
    assert pending["state"] == "needs_confirmation"
    key = new_hook_key()
    assert await register(db, gateway, key) is None
    await db.commit()
    return workspace_id, user, gateway, session_key, caller, pending["approval_id"], key


async def _tickets(db, session_id: str) -> list[ToolCall]:
    rows = await db.execute(
        select(ToolCall).where(ToolCall.session_id == session_id, ToolCall.status == TOOL_CALL_STATUS_CONFIRMATION_ASKED)
    )
    return list(rows.scalars().all())


async def test_the_hook_key_is_set_once(db):
    _, _, gateway, _, _, _, _ = await _setup(db)
    assert await register(db, gateway, new_hook_key()) == "hook_key_already_registered"


async def test_forged_missing_stale_and_replayed_proofs_mint_no_ticket(db):
    _, _, gateway, session_key, _, approval_id, key = await _setup(db)

    async def ask(hook_input):
        return await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input)

    forged = confirm_hook_input(new_hook_key(), session_key=session_key, approval_id=approval_id)
    assert (await ask(forged))["reason"] == "confirmation_proof_invalid"
    missing = {**forged}
    missing.pop("confirmation_proof")
    assert (await ask(missing))["reason"] == "confirmation_proof_missing"
    stale = confirm_hook_input(key, session_key=session_key, approval_id=approval_id, ts=int(time.time()) - 3600)
    assert (await ask(stale))["reason"] == "confirmation_proof_expired"
    other_session = confirm_hook_input(key, session_key=str(uuid.uuid4()), approval_id=approval_id)
    assert (await ask(other_session))["reason"] == "confirmation_proof_invalid"
    # A proof for one approval cannot be re-pointed at another: the MAC covers the approval id.
    tampered = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    tampered["tool_input"] = {"approval_id": str(uuid.uuid4())}
    assert (await ask(tampered))["reason"] == "confirmation_proof_invalid"
    assert await _tickets(db, gateway.id) == []

    genuine = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    assert (await ask(genuine))["decision"] == "ask"
    replay = await ask(genuine)
    assert (replay["decision"], replay["reason"]) == ("deny", "confirmation_proof_replayed")
    assert len(await _tickets(db, gateway.id)) == 1


async def test_a_ticket_is_single_use_and_bound_to_approval_and_tool_use(db):
    _, _, gateway, session_key, _, approval_id, key = await _setup(db)
    hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    ticket = (await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input))[
        "confirmation_ticket"
    ]

    async def redeem(**overrides):
        values = {"approval_id": approval_id, "ticket": ticket, "tool_use_id": hook_input["tool_use_id"], **overrides}
        return await redeem_confirmation_ticket(db, session=gateway, **values)

    assert await redeem(ticket="forged-ticket-value") is False
    assert await redeem(approval_id=str(uuid.uuid4())) is False
    assert await redeem(tool_use_id="toolu_other") is False
    assert await redeem() is True
    assert await redeem() is False  # replay of a consumed ticket


async def test_workflow_confirm_needs_the_mcp_channel_and_the_hook_ticket(db):
    workspace_id, user, gateway, session_key, caller, approval_id, key = await _setup(db)
    hook_input = confirm_hook_input(key, session_key=session_key, approval_id=approval_id)
    ticket = (await ask_for_confirmation(db, session=gateway, session_key=session_key, hook_input=hook_input))[
        "confirmation_ticket"
    ]

    async def confirm(caller_, **arguments):
        return await mcp_workflow_confirm(
            db, caller=caller_, user=user, workspace_id=workspace_id, arguments={"approval_id": approval_id, **arguments}
        )

    rest = McpCaller(user_id=caller.user_id, grant_id=caller.grant_id, scopes=caller.scopes,
                     workspace_header=workspace_id, session_key=session_key, tool_use_id=caller.tool_use_id,
                     transport="http")
    assert (await confirm(rest, confirmation_ticket=ticket))["reason"] == "mcp_channel_required"
    without_ticket = await confirm(caller)
    assert (without_ticket["state"], without_ticket["reason"]) == ("needs_confirmation", "confirm_in_platform")
    other_call = McpCaller(user_id=caller.user_id, grant_id=caller.grant_id, scopes=caller.scopes,
                           workspace_header=workspace_id, session_key=session_key, tool_use_id="toolu_other")
    assert (await confirm(other_call, confirmation_ticket=ticket))["state"] == "needs_confirmation"
    assert (await confirm(caller, confirmation_ticket=ticket))["state"] == "selected"
    assert (await db.get(Approval, approval_id)).status == "approved"


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Bash", {"command": "curl -s -X POST http://localhost:8090/api/v1/agent-gateway/sessions/tool-check -d @x"}),
        ("Bash", {"command": "curl http://127.0.0.1:8090/api/v1/mcp/knowledge/tools/workflow_confirm"}),
        ("Bash", {"command": "TOKEN=$(octryx-claude api-key-helper) && echo $TOKEN"}),
        ("Bash", {"command": "cd /tmp; /opt/kit/bin/octryx-claude mcp-headers"}),
        ("Bash", {"command": "echo '{}' | python -m octryx_claude hook pre-tool-use"}),
        ("Bash", {"command": f"cat {STATE_ROOT}/credentials.json"}),
        ("Read", {"file_path": f"{STATE_ROOT}/credentials.json"}),
        ("Bash", {"command": "curl -d grant_type=refresh_token https://octryx.example.test/oauth/token"}),
    ],
)
def test_self_protection_denies_the_curl_and_launcher_patterns(tool, tool_input):
    decision = self_protection_decision({"tool_name": tool, "tool_input": tool_input}, state_root=STATE_ROOT)
    assert decision is not None and decision.reason == "platform_credentials_protected"


def test_self_protection_leaves_ordinary_commands_alone():
    for command in ("curl -s https://pypi.org/simple/", "git status", "mvn -q test"):
        assert self_protection_decision({"tool_name": "Bash", "tool_input": {"command": command}}) is None


def test_self_protection_lets_only_the_l10n_merge_build_step_of_the_launcher_through():
    """The platform's code style tells the agent to run `octryx-claude l10n-merge`, so this rule must not deny
    it. That subcommand holds no token and reads no state."""
    merge = "octryx-claude l10n-merge arb 'lib/features/*/l10n/*.arb' lib/l10n/app_{locale}.arb"
    for command in (merge, f"cd app && {merge}", f"/opt/kit/bin/{merge} 2>&1 | tail -5"):
        assert self_protection_decision({"tool_name": "Bash", "tool_input": {"command": command}},
                                        state_root=STATE_ROOT) is None, command
    for command in (
        f"{merge} && octryx-claude api-key-helper",
        "octryx-claude mcp-headers l10n-merge",
        "python -m octryx_claude l10n-merge arb a b",
        f"octryx-claude l10n-merge arb {STATE_ROOT}/x lib/l10n/x.arb",
        "OCTRYX_CLAUDE_HOME=/x octryx-claude l10n-merge arb a b",
    ):
        decision = self_protection_decision({"tool_name": "Bash", "tool_input": {"command": command}},
                                            state_root=STATE_ROOT)
        assert decision is not None and decision.reason == "platform_credentials_protected", command
