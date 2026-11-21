"""Cedar policy engine admin API: test bench, saved test cases, entities, settings, one decision.

Platform admins only (``policy_engine.require_admin``). Under ``/api/v1/admin/policy-engine``:

- ``GET  /entities`` — real Workspaces, users, tools, model aliases and actions for the bench pickers.
- ``POST /test-bench`` ``{workspace_id, user_id?, action, resource, source?: published|draft, policies?}``.
- ``GET|POST /tests``, ``DELETE /tests/{id}``, ``POST /tests/run`` ``{source?}`` — saved cases and a report.
- ``PUT  /settings`` ``{enforce_window_hours?, decision_log_retention_days?}``.
- ``GET  /decisions/{id}`` — one decision-log record (the "why was this blocked" link of a refusal).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import PolicyDecisionLog, Project, User
from ...services.access_control import require_existing_workspace
from ...services.data_classification.levels import level_registry
from ...services.data_classification.policy_matrix import load_classification_policy
from ...services.data_classification.policy_matrix_admin import policy_view
from ...services.model_gateway.data_policy.source import resolve_workspace_data_classification
from ...services.policy_engine import test_cases
from ...services.policy_engine.admin import PolicyEngineSettingError, set_settings
from ...services.policy_engine.bench_question import BenchError, parse_question
from ...services.policy_engine.custom_policies import CustomPolicyError
from ...services.policy_engine.decision_log import serialize_decision
from ...services.policy_engine.schema import ACTIONS
from ...services.policy_engine.test_bench import ask, custom_text
from ...tools.definitions import get_all_definitions
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/policy-engine", tags=["policy-engine"])

MAX_PICKER_ROWS = 500


def _bench_refusal(error: BenchError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "path": error.path})


def _policy_refusal(error: CustomPolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues})


async def _source(db: AsyncSession, body: dict[str, Any]):
    policies = body.get("policies")
    if policies is not None and not isinstance(policies, str):
        raise HTTPException(status_code=422, detail={"code": "policy_bench_request_invalid", "path": "policies"})
    return await custom_text(db, body.get("source"), policies)


async def _named_workspace(db: AsyncSession, body: dict[str, Any]) -> None:
    """A question names a real Workspace: an unknown one is 404 ``project_not_found`` before it is asked or saved."""
    workspace_id = body.get("workspace_id")
    await require_existing_workspace(db, workspace_id if isinstance(workspace_id, str) else None)


@router.get("/entities")
async def get_entities(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    projects = (await db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
                                 .limit(MAX_PICKER_ROWS))).scalars().all()
    workspaces = []
    for project in projects:
        classification = await resolve_workspace_data_classification(db, project_id=project.id)
        workspaces.append({"id": project.id, "name": project.name,
                           "classification": classification.classification if classification.resolved else None})
    users = (await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.username)
                              .limit(MAX_PICKER_ROWS))).scalars().all()
    matrix = await policy_view(db, await load_classification_policy(db), can_edit=False)
    return {
        "workspaces": workspaces,
        "users": [{"id": user.id, "username": user.username, "display_name": user.display_name} for user in users],
        "tools": sorted(get_all_definitions()),
        "model_aliases": list(matrix.get("model_aliases") or []),
        "actions": list(ACTIONS),
        "data_policy_classes": list(level_registry().model_levels()),
    }


@router.post("/test-bench")
async def post_test_bench(
    body: dict[str, Any] = Body(...), _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _named_workspace(db, body)
    try:
        return await ask(db, parse_question(body), await _source(db, body))
    except BenchError as error:
        raise _bench_refusal(error) from None
    except CustomPolicyError as error:
        raise _policy_refusal(error) from None


@router.get("/tests")
async def get_tests(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = await test_cases.list_cases(db)
    return {"items": [test_cases.serialize_case(row) for row in rows], "count": len(rows)}


@router.post("/tests", status_code=201)
async def post_test(
    body: dict[str, Any] = Body(...), user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _named_workspace(db, body)
    try:
        row = await test_cases.create_case(db, body=body, actor_id=user.id)
    except BenchError as error:
        raise _bench_refusal(error) from None
    await db.commit()
    return test_cases.serialize_case(row)


@router.delete("/tests/{case_id}")
async def delete_test(
    case_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        await test_cases.delete_case(db, case_id=case_id, actor_id=user.id)
    except BenchError as error:
        raise _bench_refusal(error) from None
    await db.commit()
    return {"deleted": case_id}


@router.post("/tests/run")
async def run_tests(
    body: dict[str, Any] = Body(default={}), _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        return await test_cases.run_cases(db, await _source(db, body))
    except BenchError as error:
        raise _bench_refusal(error) from None
    except CustomPolicyError as error:
        raise _policy_refusal(error) from None


@router.put("/settings")
async def put_settings(
    body: dict[str, Any] = Body(...), user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        saved = await set_settings(db, values=body, actor_id=user.id)
    except PolicyEngineSettingError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, **error.details}) from None
    await db.commit()
    return saved


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await db.get(PolicyDecisionLog, decision_id[:36])
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "policy_decision_not_found"})
    return serialize_decision(row)


__all__ = ["router"]
