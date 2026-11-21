"""Test cases of a flow definition: list, edit, delete and run.

Included into the ``/api/v1/flows`` router by ``flow_definitions.py``; this router has no prefix of its own. A test
case names the Workspace its runs start in (an unknown one is 404 ``project_not_found`` when it is saved); a run of a
case without a Workspace it may start in is 409 ``needs_configuration`` / ``workspace_required`` before anything runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.flow_test_cases import (
    batch_run_flow_test_cases,
    create_flow_test_case,
    delete_flow_test_case,
    list_flow_test_cases,
    run_flow_test_case,
    update_flow_test_case,
)
from ...services.flow_trace import get_flow_run_trace
from ...services.notification_delivery import require_admin_user
from ...services.workflow_runs.records import WorkflowRunError
from ._workflow_run_http import _http

router = APIRouter()


@router.get("/{flow_id}/test-cases")
async def get_flow_test_cases(
    flow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_flow_test_cases(db, flow_id=flow_id)


@router.post("/{flow_id}/test-cases")
async def post_flow_test_case(
    flow_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await create_flow_test_case(db, flow_id=flow_id, current_user=current_user, payload=payload or {})
    await db.commit()
    return result


@router.put("/{flow_id}/test-cases/{test_case_id}")
async def put_flow_test_case(
    flow_id: str,
    test_case_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await update_flow_test_case(db, flow_id=flow_id, test_case_id=test_case_id, payload=payload or {})
    await db.commit()
    return result


@router.delete("/{flow_id}/test-cases/{test_case_id}")
async def delete_flow_test_case_route(
    flow_id: str,
    test_case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    result = await delete_flow_test_case(db, flow_id=flow_id, test_case_id=test_case_id)
    await db.commit()
    return result


@router.post("/{flow_id}/test-cases/{test_case_id}/run")
async def post_run_flow_test_case(
    flow_id: str,
    test_case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    try:
        result = await run_flow_test_case(db, flow_id=flow_id, test_case_id=test_case_id, current_user=current_user)
    except WorkflowRunError as error:
        raise _http(error) from None
    await db.commit()
    return {
        **result,
        "trace": await get_flow_run_trace(db, run_id=str(result["run_id"])),
    }


@router.post("/{flow_id}/test-cases/batch-run")
async def post_batch_run_flow_test_cases(
    flow_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    ids = body.get("test_case_ids") if isinstance(body.get("test_case_ids"), list) else None
    try:
        result = await batch_run_flow_test_cases(
            db,
            flow_id=flow_id,
            test_case_ids=[str(item) for item in ids] if ids is not None else None,
            current_user=current_user,
        )
    except WorkflowRunError as error:
        raise _http(error) from None
    await db.commit()
    return result
