"""The same turn with different wording gets the same tool surface and context sections.

The prompts below switched the keyword planner's plan on the base: tools on or off,
tier, route, prompt variant, history window and budget all followed the wording. Through the real
``prepare_agent_run`` every one of them now gets the plan of its explicit inputs, and a plain
chat turn keeps its tools regardless of wording.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.context.context_planner import build_context_section_decisions
from app.agent.core.context.run_context import prepare_agent_run
from app.agent.engine.messages._engine_message_helpers import _exclude_tool_definitions, _filter_tool_definitions
from app.models import Message, Project, Session, User
from app.services.governed_default_tool_sets import governed_default_tool_set
from tests.connection_support import connect

# Prompts whose wording must not switch the base plan (negative-control probes).
PROMPTS = [
    "ping",
    "Write a haiku about autumn.",
    "Check the latest Jira ticket for acme-orders and summarize it.",
    "Create a daily summary from Jira, Bitbucket and Confluence for today.",
    "Continue from the failure and keep working",
    "Führe python3 manage.py migrate aus",
    "Use the Cloudflare MCP server and list available MCP tools.",
    "Erstelle mir eine presentation für den einsatz von LLM im Unternehmen.",
    "Erkläre mir report-builder.",
    "Use read-only AWS evidence only: call AWS STS get-caller-identity and answer with the AWS account id.",
    "Richte mir einen Slack channel fuer acme-orders ein und setze den Output vom Task Nightly Summary darauf.",
    "Why is the pod in namespace payments crashlooping?",
]


async def _prepared_turn(db, tmp_path: Path, project: Project, admin: User, prompt: str):
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis")
    db.add(session)
    await db.flush()
    db.add_all(
        [
            Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Earlier question about deploys."),
            Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="Earlier deploy answer."),
        ]
    )
    await db.commit()
    return await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message=prompt,
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=_filter_tool_definitions,
        exclude_tool_definitions=_exclude_tool_definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )


def _turn_facts(prepared) -> dict[str, Any]:
    plan = prepared.context_plan
    return {
        "tool_surface_source": getattr(plan, "tool_surface_source", None),
        "tool_names": sorted(definition["function"]["name"] for definition in prepared.tool_definitions),
        "sections": build_context_section_decisions(plan),
        "tier": plan.tier,
        "route_reason": plan.route_reason,
        "system_prompt_variant": plan.system_prompt_variant,
        "recent_history_limit": plan.recent_history_limit,
        "token_budget": plan.token_budget,
        "tool_allowlist": plan.tool_allowlist,
        "blocked_tools": plan.blocked_tools,
        "history": [message.content for message in prepared.history],
    }


@pytest.mark.asyncio
async def test_wording_does_not_change_the_tool_surface_or_the_context_sections(db, tmp_path: Path) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"w20-parity-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    for tool in ("jira", "bitbucket", "confluence"):  # connections are the runtime source
        await connect(db, tool, project.id)
    await db.commit()

    facts = {prompt: _turn_facts(await _prepared_turn(db, tmp_path, project, admin, prompt)) for prompt in PROMPTS}

    reference = facts[PROMPTS[0]]
    for prompt, turn in facts.items():
        assert turn == reference, prompt
    # A plain chat turn keeps its tools regardless of wording.
    assert reference["tool_surface_source"] == "governed_default"
    # The curated chat set, recorded with its version.
    assert reference["sections"]["tools"]["source"] == (
        f"tool_surface:governed_default:{governed_default_tool_set('diagnosis').key}")
    assert reference["sections"]["tools"]["included"] is True
    assert {"select_workflow", "knowledge_search", "search_jira_tickets"} <= set(reference["tool_names"])
    assert reference["history"] == ["Earlier question about deploys.", "Earlier deploy answer."]


@pytest.mark.asyncio
async def test_a_workspace_policy_offering_no_tools_is_an_explicit_zero_tool_turn(db, tmp_path: Path) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"w20-no-tools-{uuid.uuid4().hex[:6]}",
        config={"tool_policy": {"allowlist": ["no_such_tool"]}},
        is_active=True,
    )
    db.add(project)
    await db.commit()

    prepared = await _prepared_turn(db, tmp_path, project, admin, "Check the latest Jira ticket.")

    assert prepared.context_plan.tool_surface_source == "workspace_policy"
    assert prepared.tool_definitions == []
