"""Run an agent-chain template: sequential steps one by one, parallel groups together."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import AgentChainRun, AgentChainTemplate, User
from ...time_utils import utc_now
from ..error_facts import error_text
from .serialization import _serialize_run
from .step_input import _extract_step_output, _format_step_input
from .steps import _default_run_agent, _run_chain_step_isolated, _run_chain_step_with_retry
from .templates import _get_template_or_404


@dataclass(frozen=True)
class _ChainScope:
    """What every step of one chain run shares."""

    db: AsyncSession
    template: AgentChainTemplate
    chain_run: AgentChainRun
    current_user: User
    parent_session_id: str | None
    session_factory: async_sessionmaker[AsyncSession] | None
    run_agent_fn: Any


async def _run_step_in_scope(scope: _ChainScope, step: dict[str, Any], prompt: str) -> dict[str, Any]:
    return await _run_chain_step_with_retry(
        scope.db,
        template=scope.template,
        chain_run=scope.chain_run,
        current_user=scope.current_user,
        step=step,
        prompt=prompt,
        parent_session_id=scope.parent_session_id,
        run_agent_fn=scope.run_agent_fn,
    )


def _record_output(
    context: dict[str, Any],
    step_results: list[dict[str, Any]],
    *,
    step_id: Any,
    step: dict[str, Any],
    output: dict[str, Any],
) -> None:
    """Add a finished step to the results and its content, session and mapped output to the context."""
    step_results.append(output)
    context[f"step_{step_id}_content"] = output.get("content")
    context[f"step_{step_id}_session_id"] = output.get("session_id")
    mapped_key, mapped_value = _extract_step_output(step, output)
    if mapped_key:
        context[mapped_key] = mapped_value


def _collect_parallel_group(steps: list[Any], index: int, group_name: str) -> tuple[list[dict[str, Any]], int]:
    """The consecutive parallel steps of ``group_name`` from ``index`` on, and the index after them."""
    group_steps: list[dict[str, Any]] = []
    while index < len(steps):
        candidate = dict(steps[index] or {})
        candidate_group = str(candidate.get("parallel_group") or "").strip()
        if candidate.get("execution_mode") != "parallel" or candidate_group != group_name:
            break
        group_steps.append(candidate)
        index += 1
    return group_steps, index


async def _run_parallel_group(
    scope: _ChainScope, group_steps: list[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Without a session factory the group runs one by one on the caller's session, else concurrently."""
    if scope.session_factory is None:
        group_outputs = []
        for group_step in group_steps:
            prompt = _format_step_input(group_step, context)
            group_outputs.append(await _run_step_in_scope(scope, group_step, prompt))
        return group_outputs
    prompts = [_format_step_input(group_step, context) for group_step in group_steps]
    return await asyncio.gather(
        *[
            _run_chain_step_isolated(
                scope.session_factory,
                template_id=scope.template.id,
                chain_run_id=scope.chain_run.id,
                current_user_id=scope.current_user.id,
                step=group_step,
                prompt=prompt,
                parent_session_id=scope.parent_session_id,
                run_agent_fn=scope.run_agent_fn,
            )
            for group_step, prompt in zip(group_steps, prompts, strict=False)
        ]
    )


async def _run_all_steps(
    scope: _ChainScope,
    steps: list[Any],
    context: dict[str, Any],
    step_results: list[dict[str, Any]],
) -> None:
    index = 0
    while index < len(steps):
        step = dict(steps[index] or {})
        group_name = str(step.get("parallel_group") or "").strip() or None
        is_parallel_group = bool(group_name) and step.get("execution_mode") == "parallel"
        if is_parallel_group:
            group_steps, index = _collect_parallel_group(steps, index, group_name)
            group_outputs = await _run_parallel_group(scope, group_steps, context)
            for output in group_outputs:
                _record_output(
                    context,
                    step_results,
                    step_id=output["step_id"],
                    step=next(group_step for group_step in group_steps if group_step["id"] == output["step_id"]),
                    output=output,
                )
            continue

        prompt = _format_step_input(step, context)
        output = await _run_step_in_scope(scope, step, prompt)
        _record_output(context, step_results, step_id=step["id"], step=step, output=output)
        index += 1


async def _start_chain_run(
    db: AsyncSession, template: AgentChainTemplate, current_user: User, input_payload: dict[str, Any] | None
) -> AgentChainRun:
    chain_run = AgentChainRun(
        template_id=template.id,
        project_id=template.project_id,
        started_by=current_user.id,
        status="running",
        input_payload=dict(input_payload or {}),
        output_payload={},
        step_results=[],
    )
    db.add(chain_run)
    await db.commit()
    await db.refresh(chain_run)
    return chain_run


async def _complete_chain_run(
    db: AsyncSession, chain_run: AgentChainRun, context: dict[str, Any], step_results: list[dict[str, Any]]
) -> dict[str, Any]:
    output_payload = {
        key: value
        for key, value in context.items()
        if key not in {"parent_session_id", "project_id"} and not key.startswith("step_")
    }
    chain_run.status = "completed"
    chain_run.step_results = step_results
    chain_run.output_payload = output_payload
    chain_run.completed_at = utc_now()
    db.add(chain_run)
    await db.commit()
    await db.refresh(chain_run)
    return _serialize_run(chain_run)


async def _fail_chain_run(
    db: AsyncSession, chain_run: AgentChainRun, exc: Exception, step_results: list[dict[str, Any]]
) -> None:
    chain_run.status = "failed"
    chain_run.error = error_text("agent_chain_run_failed", exc)
    chain_run.step_results = step_results
    chain_run.completed_at = utc_now()
    db.add(chain_run)
    await db.commit()


async def execute_agent_chain(
    db: AsyncSession,
    *,
    template_id: str,
    current_user: User,
    input_payload: dict[str, Any] | None = None,
    parent_session_id: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    run_agent_fn: Any = _default_run_agent,
) -> dict[str, Any]:
    template = await _get_template_or_404(db, template_id)
    if not template.is_active:
        raise HTTPException(status_code=400, detail="Agent chain template is inactive")
    chain_run = await _start_chain_run(db, template, current_user, input_payload)

    context: dict[str, Any] = {
        "initial_input": dict(input_payload or {}),
        "project_id": template.project_id or "",
        "parent_session_id": parent_session_id or "",
        **dict(input_payload or {}),
    }
    step_results: list[dict[str, Any]] = []
    steps = list(template.steps_json or [])
    scope = _ChainScope(
        db=db,
        template=template,
        chain_run=chain_run,
        current_user=current_user,
        parent_session_id=parent_session_id,
        session_factory=session_factory,
        run_agent_fn=run_agent_fn,
    )

    try:
        await _run_all_steps(scope, steps, context, step_results)
        return await _complete_chain_run(db, chain_run, context, step_results)
    except Exception as exc:
        await _fail_chain_run(db, chain_run, exc, step_results)
        raise
