"""The ``/chat/api`` turn-start adapter with the chat HTTP contract for a refusal, and the task-generation handler."""

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import async_session_factory
from ...models import (
    ControlPlaneRuntimeTarget,
    LLMProvider,
    Message,
    User,
)
from ...models import (
    Session as AgentSession,
)
from ...services.control_plane_service import (
    build_provider_client_kwargs_async,
    ensure_control_plane_defaults,
    get_runtime_targets,
)
from ...services.error_facts import error_text
from ...services.model_gateway.dispatch_admission import admit_client_kwargs_for_dispatch
from ...services.model_selection.gates import gate
from ...services.model_selection.snapshot import load_scope, load_snapshot
from ...services.model_selection.task_models import TASK_EXTRACT
from ...services.session.turn_refusals import TurnRefusal
from ...services.session.turn_start import load_prepared_session, start_turn
from ...services.system_config import get_agent_default_model
from .api_guards import _require_api_user
from .chat_turn_prepare import chat_refusal_http_exception, chat_turn_request
from .generated_task import TASK_EXTRACTION_SYSTEM_PROMPT, _parse_generated_task, _persist_generated_task

logger = logging.getLogger(__name__)

__all__ = [
    "_start_chat_turn",
    "_chat_generate_task_impl",
]


async def _start_chat_turn(
    *,
    db: AsyncSession,
    user: User,
    session_factory=None,
    **request_kwargs,
) -> AgentSession:
    started = await start_turn(
        chat_turn_request(user_id=user.id, **request_kwargs),
        session_factory=session_factory or async_session_factory,
    )
    if isinstance(started, TurnRefusal):
        raise chat_refusal_http_exception(started)
    session = await load_prepared_session(db, started)
    if session is None:
        raise HTTPException(status_code=500, detail="Prepared session could not be reloaded")
    return session


def _pre_turn_dispatch_failure(
    admission_denial: dict | None, last_error: Exception | None
) -> HTTPException:
    # A Workspace refusal stays reported even when a later candidate failed for a provider reason: otherwise the generic
    # runtime error would hide the policy state an operator must act on.
    if admission_denial is not None:
        return HTTPException(
            status_code=502 if last_error is not None else 409,
            detail={**admission_denial, "runtime_failure": last_error is not None},
        )
    if last_error is None:
        return HTTPException(status_code=502, detail="all_runtimes_failed")
    return HTTPException(status_code=502, detail=error_text("all_runtimes_failed", last_error))


async def _task_extraction_candidates(db: AsyncSession, session: AgentSession) -> tuple[list[tuple], Any, Any]:
    candidates: list[tuple] = []
    session_meta = dict(session.metadata_ or {})
    session_runtime_target_id = str(session_meta.get("runtime_target_id") or "").strip()
    seen_rt_ids: set[str] = set()
    snapshot = await load_snapshot(db)
    scope = await load_scope(db, workspace_id=session.project_id, session_metadata=session_meta)
    # The Workspace's own task model (Workspace → Models → task overrides) wins over the platform's, as in the resolver.
    extract_key = dict(scope.task_overrides).get(TASK_EXTRACT) or snapshot.task_models.get(TASK_EXTRACT, "")
    extract_model = snapshot.model(extract_key) if extract_key else None
    if extract_model is not None and extract_model.target_ids:
        session_runtime_target_id = extract_model.target_ids[0]

    if session_runtime_target_id:
        rt = await db.get(ControlPlaneRuntimeTarget, session_runtime_target_id)
        if rt:
            prov_obj = await db.get(LLMProvider, rt.provider_id)
            if prov_obj and prov_obj.is_active:
                candidates.append((prov_obj, rt.model_id))
                seen_rt_ids.add(rt.id)

    cp_config = await ensure_control_plane_defaults(db)
    for _rt in await get_runtime_targets(db, cp_config, active_only=True):
        if _rt.id in seen_rt_ids:
            continue
        _prov = await db.get(LLMProvider, _rt.provider_id)
        if _prov and _prov.is_active:
            candidates.append((_prov, _rt.model_id))
            seen_rt_ids.add(_rt.id)
    return candidates, snapshot, scope


async def _dispatch_task_extraction(
    db: AsyncSession,
    *,
    session: AgentSession,
    candidates: list[tuple],
    snapshot: Any,
    scope: Any,
    llm_messages: list[dict],
) -> dict:
    from ...agent.providers import get_provider as _get_provider
    from ...services.content_security.model_call_scope import model_call_scope, session_call

    response = None
    last_error: Exception | None = None
    admission_denial: dict | None = None
    for _prov_obj, _model_id in candidates:
        if gate(snapshot.for_ref(_prov_obj.id, _model_id), scope):
            continue
        _model = _model_id or await get_agent_default_model(db)
        # The Workspace is the session row's own project; the request body cannot
        # name one. A governed gateway target this Workspace has not granted is
        # skipped before a client exists, and its explicit state is reported
        # instead of collapsing into the generic "all runtimes failed" 502.
        _admission = await admit_client_kwargs_for_dispatch(
            db,
            await build_provider_client_kwargs_async(db, _prov_obj),
            model=_model,
            project_ids=session.project_id,
            owner="chat_turn_task_extraction",
        )
        if not _admission.allowed:
            admission_denial = _admission.to_result()
            continue
        _client = _get_provider(**(_admission.first_dispatchable_runtime() or {}))
        try:
            # The content handling of the session's Workspace (the one the runtime was admitted for).
            with model_call_scope(session_call(session.project_id, session_id=session.id, user_id=session.user_id)):
                response = await _client.chat(
                    messages=llm_messages,
                    model=_model,
                    temperature=0,
                    max_tokens=1024,
                )
            if not (response.get("content") or "").strip():
                last_error = RuntimeError(f"Provider {_prov_obj.name}/{_model_id} returned empty content")
                response = None
                continue
            break
        except Exception as _exc:
            last_error = _exc
        finally:
            if hasattr(_client, "close"):
                await _client.close()

    if response is None:
        raise _pre_turn_dispatch_failure(admission_denial, last_error)
    return response


async def _chat_generate_task_impl(
    session_id: str,
    request: Request,
    db: AsyncSession,
):
    user = await _require_api_user(request, db)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages_result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc()).limit(60)
    )
    messages_list = messages_result.scalars().all()
    conversation = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages_list if m.content)

    # Every candidate passes the model resolver's gates for the session's Workspace.
    candidates, snapshot, scope = await _task_extraction_candidates(db, session)
    if not candidates:
        raise HTTPException(status_code=400, detail="No active runtime configured")

    llm_messages = [
        {"role": "system", "content": TASK_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"Generate a task definition from this conversation:\n\n{conversation}"},
    ]
    response = await _dispatch_task_extraction(
        db, session=session, candidates=candidates, snapshot=snapshot, scope=scope, llm_messages=llm_messages
    )
    task_data = _parse_generated_task(response.get("content") or "")
    task = await _persist_generated_task(db, session=session, user=user, task_data=task_data)
    return JSONResponse(
        {
            "task_id": task.id,
            "task_name": task.name,
            "task_url": f"/admin/tasks?task_id={task.id}",
        }
    )
