"""Publishing, review, unpublishing and running of flow definition versions and capabilities.

Included into the ``/api/v1/flows`` router by ``flow_definitions.py``; this router has no prefix of its own. A version
run and a capability run start in a Workspace (``flow_orchestration.start_scope``): without one the answer is 409
``needs_configuration`` / ``workspace_required`` before anything is written.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.flow_capabilities import (
    list_flow_capabilities,
    run_published_flow_capability,
    unpublish_flow_definition_version,
)
from ...services.flow_definitions import publish_flow_definition_version
from ...services.flow_orchestration.runner import execute_flow_version
from ...services.flow_orchestration.start_scope import require_flow_start_workspace
from ...services.flow_publish_review import request_review
from ...services.flow_trace import list_flow_node_runs, serialize_flow_node_run, serialize_flow_run
from ...services.flow_version_state import FlowVersionStateError
from ...services.notification_delivery import require_admin_user
from ...services.workflow_runs.records import WorkflowRunError
from ._workflow_run_http import _http

router = APIRouter()


@router.post("/versions/{version_id}/publish")
async def post_publish_flow_definition_version(
    version_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    result = await publish_flow_definition_version(
        db,
        version_id=version_id,
        current_user=current_user,
        publish_metadata=body.get("publish_metadata") if isinstance(body.get("publish_metadata"), dict) else body,
    )
    await db.commit()
    return result


@router.post("/versions/{version_id}/request-review")
async def post_request_flow_version_review(
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """D2b2: the author asks a second admin to publish their phased workflow version (four-eyes)."""
    await require_admin_user(db, current_user)
    result = await request_review(db, version_id=version_id, current_user=current_user)
    await db.commit()
    return result


@router.post("/versions/{version_id}/unpublish")
async def post_unpublish_flow_definition_version(
    version_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    result = await unpublish_flow_definition_version(
        db,
        version_id=version_id,
        current_user=current_user,
        reason=str(body.get("reason") or "").strip() or None,
    )
    await db.commit()
    return result


@router.get("/capabilities")
async def get_flow_capabilities(
    project_id: str | None = None,
    include_hidden: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return {
        "items": await list_flow_capabilities(
            db,
            project_id=str(project_id or "").strip() or None,
            include_hidden=include_hidden,
        )
    }


@router.post("/capabilities/{tool_name}/run")
async def post_run_flow_capability(
    tool_name: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    input_payload = body.get("input") if isinstance(body.get("input"), dict) else body.get("initial_input")
    try:
        result = await run_published_flow_capability(
            db,
            tool_name=tool_name,
            project_id=str(body.get("project_id") or "").strip() or None,
            parent_session_id=str(body.get("parent_session_id") or "").strip() or None,
            initial_input=input_payload if isinstance(input_payload, dict) else {},
            current_user=current_user,
            agent_type=str(body.get("agent_type") or "change"),
        )
    except WorkflowRunError as error:
        raise _http(error) from None
    await db.commit()
    return result


@router.post("/versions/{version_id}/run")
async def post_run_flow_definition_version(
    version_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    project_id = str(body.get("project_id") or "").strip() or None
    try:
        await require_flow_start_workspace(db, current_user.id, project_id)
    except WorkflowRunError as error:
        raise _http(error) from None
    try:
        run = await execute_flow_version(
            db,
            flow_version_id=version_id,
            parent_session_id=str(body.get("parent_session_id") or "").strip() or None,
            project_id=project_id,
            triggered_by_node_id=str(body.get("triggered_by_node_id") or "").strip() or None,
            initial_input=body.get("initial_input") if isinstance(body.get("initial_input"), dict) else {},
            user_id=current_user.id,
            agent_type=str(body.get("agent_type") or "change"),
        )
    except FlowVersionStateError as error:
        raise error.to_http() from None
    node_runs = await list_flow_node_runs(db, run_id=run.id)
    await db.commit()
    return {
        "run": serialize_flow_run(run),
        "node_runs": [serialize_flow_node_run(node_run) for node_run in node_runs],
    }
