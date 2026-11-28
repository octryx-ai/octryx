"""One agent-chain step: a sub-session whose runner turn runs the step, with SQLite lock retries."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import AgentChainRun, AgentChainTemplate, Session, User
from ..run_capability.worker_profiles import worker_session_capability_metadata


async def _default_run_agent(*, session_id: str, user_message: str, user_id: str, db: AsyncSession,
                             **_unused: Any) -> AsyncIterator[Any]:
    # The step is a runner turn in its sub-session; its answer is the step's content.
    from ..devices.agent_runtime import runner_turn

    turn = await runner_turn(db, user_id=user_id, prompt=user_message, session_id=session_id)
    yield SimpleNamespace(role="assistant", content=turn.answer)


def _sub_session(
    *,
    template: AgentChainTemplate,
    chain_run: AgentChainRun,
    current_user: User,
    step: dict[str, Any],
    parent_session_id: str | None,
) -> Session:
    return Session(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        project_id=template.project_id,
        agent_type=step["agent_type"],
        status="active",
        origin="sub_agent",
        metadata_={
            "title": f"Agent Chain: {template.name} / {step['name']}",
            "trigger": "agent_chain",
            "agent_chain_template_id": template.id,
            "agent_chain_run_id": chain_run.id,
            "agent_chain_step_id": step["id"],
            **worker_session_capability_metadata("agent_chain_step"),
        },
        parent_session_id=parent_session_id,
        sub_agent_depth=1 if parent_session_id else 0,
    )


def _final_content(events: list[Any]) -> str | None:
    return next(
        (
            event.content
            for event in reversed(events)
            if getattr(event, "role", None) == "assistant" and getattr(event, "content", None)
        ),
        None,
    )


async def _run_chain_step(
    db: AsyncSession,
    *,
    template: AgentChainTemplate,
    chain_run: AgentChainRun,
    current_user: User,
    step: dict[str, Any],
    prompt: str,
    parent_session_id: str | None,
    run_agent_fn: Any = _default_run_agent,
) -> dict[str, Any]:
    sub_session = _sub_session(
        template=template,
        chain_run=chain_run,
        current_user=current_user,
        step=step,
        parent_session_id=parent_session_id,
    )
    db.add(sub_session)
    await db.commit()

    events = []
    async for event in run_agent_fn(
        session_id=sub_session.id,
        user_message=prompt,
        user_id=current_user.id,
        project_id=template.project_id,
        agent_type=step["agent_type"],
        db=db,
        thinking_level=step.get("thinking_level"),
        parent_session_id=parent_session_id,
        sub_agent_depth=1 if parent_session_id else 0,
    ):
        events.append(event)

    final_content = _final_content(events)
    session_row = await db.get(Session, sub_session.id)
    return {
        "step_id": step["id"],
        "name": step["name"],
        "agent_type": step["agent_type"],
        "thinking_level": step.get("thinking_level"),
        "status": "completed" if final_content is not None else "completed",
        "prompt": prompt,
        "content": final_content or "",
        "session_id": sub_session.id,
        "session_status": session_row.status if session_row is not None else None,
    }


def _is_sqlite_database_locked(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


async def _run_chain_step_with_retry(
    db: AsyncSession,
    *,
    template: AgentChainTemplate,
    chain_run: AgentChainRun,
    current_user: User,
    step: dict[str, Any],
    prompt: str,
    parent_session_id: str | None,
    run_agent_fn: Any = _default_run_agent,
) -> dict[str, Any]:
    for attempt in range(5):
        try:
            return await _run_chain_step(
                db,
                template=template,
                chain_run=chain_run,
                current_user=current_user,
                step=step,
                prompt=prompt,
                parent_session_id=parent_session_id,
                run_agent_fn=run_agent_fn,
            )
        except OperationalError as exc:
            await db.rollback()
            if not _is_sqlite_database_locked(exc) or attempt == 4:
                raise
            await db.refresh(template)
            await db.refresh(chain_run)
            await db.refresh(current_user)
            await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("Agent chain step execution did not complete")


async def _run_chain_step_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    template_id: str,
    chain_run_id: str,
    current_user_id: str,
    step: dict[str, Any],
    prompt: str,
    parent_session_id: str | None,
    run_agent_fn: Any = _default_run_agent,
) -> dict[str, Any]:
    for attempt in range(5):
        async with session_factory() as db:
            try:
                template = await db.get(AgentChainTemplate, template_id)
                chain_run = await db.get(AgentChainRun, chain_run_id)
                current_user = await db.get(User, current_user_id)
                if template is None or chain_run is None or current_user is None:
                    raise RuntimeError("Agent chain step execution lost required state")
                return await _run_chain_step_with_retry(
                    db,
                    template=template,
                    chain_run=chain_run,
                    current_user=current_user,
                    step=step,
                    prompt=prompt,
                    parent_session_id=parent_session_id,
                    run_agent_fn=run_agent_fn,
                )
            except OperationalError as exc:
                await db.rollback()
                if not _is_sqlite_database_locked(exc) or attempt == 4:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("Agent chain step execution did not complete")
