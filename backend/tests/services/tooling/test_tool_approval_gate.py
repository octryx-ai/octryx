"""Contract tests for central approval enforcement in tool dispatch."""

import pytest
from sqlalchemy import select

from app.models import Approval
from app.services.approval.resolution_service import resolve_approval_request
from app.services.tool_approval.gate import enforce_tool_approval
from app.services.tool_approval.rules import tool_approval_requirement
from app.tools.context import ToolContext

WRITE_TOOL = "create_jira_ticket"


def _context(project_config: dict, db=None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["member"],
        session_id="session-1",
        project_config=project_config,
        db=db,
    )


def test_no_policy_requires_nothing() -> None:
    requirement = tool_approval_requirement(WRITE_TOOL, {})
    assert requirement.required is False
    assert requirement.matched_rule == "no_policy"


def test_risk_rule_requires_approval_for_write_tool() -> None:
    requirement = tool_approval_requirement(
        WRITE_TOOL,
        {"approval_policy": {"require_for_risks": ["write"]}},
    )
    assert requirement.required is True
    assert requirement.matched_rule == "require_for_risks"


def test_risk_rule_ignores_read_tool() -> None:
    requirement = tool_approval_requirement(
        "search_jira_tickets",
        {"approval_policy": {"require_for_risks": ["write", "admin"]}},
    )
    assert requirement.required is False
    assert requirement.matched_rule == "no_match"


def test_tool_rule_requires_approval_by_name() -> None:
    requirement = tool_approval_requirement(
        "knowledge_search",
        {"approval_policy": {"require_for_tools": ["knowledge_search"]}},
    )
    assert requirement.required is True
    assert requirement.matched_rule == "require_for_tools"


def test_exempt_wins_over_other_rules() -> None:
    from app.services.tool_approval.policy import set_platform_default

    workspace = {"approval_policy": {"require_for_risks": ["write"], "require_for_tools": [WRITE_TOOL],
                                     "exempt_tools": [WRITE_TOOL]}}
    assert tool_approval_requirement(WRITE_TOOL, workspace).required is True, "a Workspace can only add"
    set_platform_default({"require_for_risks": ["write"], "require_for_tools": [], "exempt_tools": [WRITE_TOOL]})
    try:
        requirement = tool_approval_requirement(WRITE_TOOL, {})
    finally:
        set_platform_default({})
    assert requirement.required is False
    assert requirement.matched_rule == "exempt_tools"


@pytest.mark.asyncio
async def test_enforce_returns_none_when_not_required() -> None:
    result = await enforce_tool_approval(WRITE_TOOL, {}, _context({}))
    assert result is None


@pytest.mark.asyncio
async def test_enforce_denies_without_verifiable_context() -> None:
    result = await enforce_tool_approval(
        WRITE_TOOL,
        {},
        _context({"approval_policy": {"require_for_risks": ["write"]}}, db=None),
    )
    assert result is not None
    assert result["approval_status"] == "unverifiable"
    assert result["blocked_by"] == "tool_approval_gate"


@pytest.mark.asyncio
async def test_enforce_creates_pending_approval_and_resumes_after_grant(db) -> None:
    from app.models import Session as AgentSession
    from app.models import User

    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="approval-gate-session", user_id=user.id, agent_type="chat", status="active")
    db.add(session)
    await db.flush()

    context = ToolContext(
        user_id=user.id,
        project_ids=[],
        roles=["member"],
        session_id=session.id,
        project_config={"approval_policy": {"require_for_risks": ["write"]}},
        db=db,
    )
    params = {"summary": "Ticket body"}

    blocked = await enforce_tool_approval(WRITE_TOOL, params, context)
    assert blocked is not None
    assert blocked["approval_required"] is True
    assert blocked["approval_status"] == "pending"
    approval_id = blocked["approval_id"]
    approval = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one()
    assert approval.status == "pending"

    blocked_again = await enforce_tool_approval(WRITE_TOOL, params, context)
    assert blocked_again is not None
    assert blocked_again["approval_id"] == approval_id

    await resolve_approval_request(db, approval_id=approval_id, resolved_by=user.id, status="approved")

    assert await enforce_tool_approval(WRITE_TOOL, params, context) is None
    blocked_after_consume = await enforce_tool_approval(WRITE_TOOL, params, context)
    assert blocked_after_consume is not None
    assert blocked_after_consume["approval_id"] != approval_id
