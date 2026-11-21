"""Running a published workflow capability as a tool call.

The run starts in a Workspace: the caller's (the session's, or the one the route names) or else the capability's own.
Without one the start is refused as ``needs_configuration`` / ``workspace_required`` (``WorkflowRunError``) before
any session, audit start or run is written (``flow_orchestration.start_scope``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Session, User
from ...tools.context import ToolContext
from ..flow_orchestration.runner import execute_flow_version
from ..flow_orchestration.start_scope import require_flow_start_workspace
from ..flow_trace import serialize_flow_run
from ..run_capability.declared import SOURCE_FLOW_DEFINITION, declared_run_capability
from .catalog import _context_project_id, _get_capability_for_tool
from .naming import _PERSON_QUESTION_RE


async def execute_flow_capability_tool(
    db: AsyncSession,
    *,
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any]:
    project_id = await _context_project_id(db, context)
    capability = await _get_capability_for_tool(db, tool_name=tool_name, project_id=project_id)
    if capability is None:
        return {"error": f"Workflow capability is not available: {tool_name}", "tool_name": tool_name}
    workspace_id = project_id or capability.get("project_id")
    # The run's Workspace, before the session, the audit start or the run is written (``WorkflowRunError``).
    await require_flow_start_workspace(db, context.user_id, workspace_id)
    initial_input = _capability_initial_input(params, context=context, capability=capability)
    await _ensure_capability_session(db, context=context)
    await _audit_capability_event(
        db,
        user_id=context.user_id,
        session_id=context.session_id,
        action="workflow.capability_run_started",
        capability=capability,
        details={"input_keys": sorted(str(key) for key in initial_input.keys())[:50]},
    )
    run = await execute_flow_version(
        db=db,
        flow_version_id=capability["version_id"],
        parent_session_id=context.session_id,
        project_id=workspace_id,
        initial_input=initial_input,
        user_id=context.user_id,
        agent_type=context.capability_type or context.agent_mode_key or "change",
    )
    await _audit_capability_event(
        db,
        user_id=context.user_id,
        session_id=context.session_id,
        action="workflow.capability_run_completed",
        capability=capability,
        details={"flow_run_id": run.id, "status": run.status},
    )
    return {
        "workflow_capability": {
            "tool_name": capability["tool_name"],
            "flow_id": capability["flow_id"],
            "version_id": capability["version_id"],
            "version": capability["version"],
            "name": capability["name"],
        },
        "flow_run": serialize_flow_run(run),
        "evidence_summary": _flow_evidence_summary(run.merged_output_json),
        "result": dict(run.merged_output_json or {}),
    }


async def run_published_flow_capability(
    db: AsyncSession,
    *,
    tool_name: str,
    project_id: str | None,
    parent_session_id: str | None,
    initial_input: dict[str, Any],
    current_user: User,
    agent_type: str = "change",
) -> dict[str, Any]:
    if project_id:  # a named Workspace is resolved before the capability is looked up in it
        await require_flow_start_workspace(db, current_user.id, project_id)
    context = ToolContext(
        user_id=current_user.id,
        project_ids=[project_id] if project_id else [],
        roles=[],
        session_id=parent_session_id or f"flow-cap-{uuid.uuid4().hex[:12]}",
        project_config={},
        db=db,
        capability_type=agent_type,
        # Started outside a run: nothing is declared here; the flow's own class governs its nodes.
        run_capability=declared_run_capability(None, source=SOURCE_FLOW_DEFINITION).tool_context_state(),
    )
    return await execute_flow_capability_tool(
        db,
        tool_name=tool_name,
        params=initial_input,
        context=context,
    )


def _capability_initial_input(
    params: dict[str, Any],
    *,
    context: ToolContext,
    capability: dict[str, Any],
) -> dict[str, Any]:
    raw_input = params.get("input") if isinstance(params.get("input"), dict) else params
    initial_input = dict(raw_input or {})
    user_message = str(getattr(context, "current_user_message", "") or "").strip()
    if user_message and not str(initial_input.get("request") or "").strip():
        initial_input["request"] = user_message
    if not str(initial_input.get("subject_hint") or "").strip():
        hint = _infer_subject_hint(initial_input.get("request") or user_message, capability=capability)
        if hint:
            initial_input["subject_hint"] = hint
    return initial_input


def _infer_subject_hint(value: Any, *, capability: dict[str, Any]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _PERSON_QUESTION_RE.search(text)
    if match:
        return match.group(1).strip()
    haystack = " ".join(
        str(capability.get(key) or "")
        for key in ("tool_name", "name", "description")
    )
    if "person" in haystack.lower() or "identity" in haystack.lower():
        return text
    return ""


def _flow_evidence_summary(merged_output: Any) -> dict[str, Any]:
    payload = merged_output if isinstance(merged_output, dict) else {}
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), dict) else {}
    observations: list[dict[str, Any]] = []
    for node_id, node_output in nodes.items():
        if not isinstance(node_output, dict):
            continue
        tool_name = str(node_output.get("tool") or "").strip()
        result = node_output.get("result") if isinstance(node_output.get("result"), dict) else {}
        if not tool_name or not result:
            continue
        observations.append(_tool_observation(str(node_id), tool_name, result))
    summary: dict[str, Any] = {
        "observations": observations,
        "answer_guidance": [
            "Use only the tools and evidence listed in observations.",
            "Do not claim that a source profile exists unless an observation explicitly contains that profile.",
            "Treat zero-result live connector searches as evidence gaps, not negative proof.",
        ],
    }
    release_context = _flow_release_context(payload)
    if release_context:
        summary["release_context"] = release_context
    return summary


def _flow_release_context(payload: dict[str, Any]) -> dict[str, Any]:
    final = payload.get("final") if isinstance(payload.get("final"), dict) else {}
    result = final.get("result") if isinstance(final.get("result"), dict) else final
    context: dict[str, Any] = {}
    for key in ("release_name", "release_id", "release_date", "release_project_key", "release_status"):
        value = result.get(key) if isinstance(result, dict) else None
        if value not in (None, ""):
            context[key] = value
    return context


def _tool_observation(node_id: str, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    observation: dict[str, Any] = {"node_id": node_id, "tool": tool_name}
    for key in (
        "query",
        "matched_user",
        "total",
        "count",
        "total_matches",
        "source_counts",
        "author_filter",
        "total_commit_count",
    ):
        if key in result:
            observation[key] = result.get(key)
    if isinstance(result.get("users"), list):
        observation["user_examples"] = result["users"][:2]
    if isinstance(result.get("results"), list):
        observation["result_examples"] = result["results"][:3]
    if isinstance(result.get("repositories"), list):
        observation["repository_examples"] = [
            {
                "label": repo.get("label"),
                "commit_count": repo.get("commit_count"),
                "commits": (repo.get("commits") or [])[:2] if isinstance(repo, dict) else [],
            }
            for repo in result["repositories"][:3]
            if isinstance(repo, dict)
        ]
    return observation


async def _ensure_capability_session(db: AsyncSession, *, context: ToolContext) -> None:
    if not context.session_id:
        return
    existing = await db.get(Session, context.session_id)
    if existing is not None:
        return
    db.add(
        Session(
            id=context.session_id,
            user_id=context.user_id,
            agent_type=context.capability_type or context.agent_mode_key or "change",
            status="active",
            origin="flow",
            metadata_={"workflow_capability_session": True},
        )
    )
    await db.flush()


async def _audit_capability_event(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str | None,
    action: str,
    capability: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            session_id=session_id,
            action=action,
            resource_type="flow_capability",
            resource_id=capability["flow_id"],
            details={
                "tool_name": capability["tool_name"],
                "flow_id": capability["flow_id"],
                "flow_key": capability["flow_key"],
                "version_id": capability["version_id"],
                "version": capability["version"],
                "project_id": capability.get("project_id"),
                **(details or {}),
            },
        )
    )
    await db.flush()
