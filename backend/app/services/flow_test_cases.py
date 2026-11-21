from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flow_orchestration.dag.execute import execute_v2_partial_flow_dag

from ..models import FlowDefinition, FlowDefinitionVersion, User
from ..time_utils import utc_now
from .access_control import require_existing_workspace
from .flow_definitions import get_flow_definition
from .flow_orchestration.runner import execute_flow_version
from .flow_orchestration.start_scope import require_flow_start_workspace
from .flow_test_assertions import evaluate_flow_test_output
from .flow_version_state import FlowVersionStateError, ensure_runnable, load_flow_version

MAX_BATCH_CASES = 20


async def list_flow_test_cases(db: AsyncSession, *, flow_id: str) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    return {"flow_id": flow_id, "version_id": version.id, "items": _test_cases(version)}


async def create_flow_test_case(
    db: AsyncSession,
    *,
    flow_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    project_id = str(payload.get("project_id") or "").strip() or None
    await require_existing_workspace(db, project_id)  # the Workspace its runs start in
    now = utc_now().isoformat()
    test_case = {
        "id": str(uuid.uuid4()),
        "name": str(payload.get("name") or "Untitled test case").strip()[:160],
        "description": str(payload.get("description") or "").strip(),
        "project_id": project_id,
        "flow_id": flow_id,
        "flow_version_id": version.id,
        "input": payload.get("input") if isinstance(payload.get("input"), dict) else {},
        "expected_output": payload.get("expected_output") if isinstance(payload.get("expected_output"), dict) else {},
        "assertions": payload.get("assertions") if isinstance(payload.get("assertions"), list) else [],
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        "created_by": current_user.id,
        "created_at": now,
        "updated_at": now,
        "last_run_id": None,
        "last_status": None,
        "last_output": None,
        "changed_since_previous": False,
    }
    if not test_case["name"]:
        raise HTTPException(status_code=422, detail="name is required")
    test_cases = _test_cases(version)
    test_cases.append(test_case)
    await _save_test_cases(db, version=version, test_cases=test_cases)
    return test_case


async def update_flow_test_case(
    db: AsyncSession,
    *,
    flow_id: str,
    test_case_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    test_cases = _test_cases(version)
    index, existing = _find_test_case(test_cases, test_case_id)
    updated = {
        **existing,
        "name": str(payload.get("name", existing.get("name")) or "Untitled test case").strip()[:160],
        "description": str(payload.get("description", existing.get("description") or "") or "").strip(),
        "input": payload.get("input") if isinstance(payload.get("input"), dict) else existing.get("input") or {},
        "expected_output": (
            payload.get("expected_output")
            if isinstance(payload.get("expected_output"), dict)
            else existing.get("expected_output") or {}
        ),
        "assertions": (
            payload.get("assertions")
            if isinstance(payload.get("assertions"), list)
            else existing.get("assertions") or []
        ),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else existing.get("tags") or [],
        "updated_at": utc_now().isoformat(),
    }
    test_cases[index] = updated
    await _save_test_cases(db, version=version, test_cases=test_cases)
    return updated


async def delete_flow_test_case(db: AsyncSession, *, flow_id: str, test_case_id: str) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    test_cases = _test_cases(version)
    _, _existing = _find_test_case(test_cases, test_case_id)
    next_cases = [item for item in test_cases if item.get("id") != test_case_id]
    await _save_test_cases(db, version=version, test_cases=next_cases)
    return {"ok": True}


async def run_flow_test_case(
    db: AsyncSession,
    *,
    flow_id: str,
    test_case_id: str,
    current_user: User,
) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    test_cases = _test_cases(version)
    index, test_case = _find_test_case(test_cases, test_case_id)
    previous_output = test_case.get("last_output")
    await require_flow_start_workspace(db, current_user.id, _case_workspace(test_case))
    try:
        run = await execute_flow_version(
            db,
            flow_version_id=version.id,
            project_id=_case_workspace(test_case),
            initial_input=test_case.get("input") if isinstance(test_case.get("input"), dict) else {},
            user_id=current_user.id,
            agent_type="change",
        )
    except FlowVersionStateError as error:
        raise error.to_http() from None
    output = dict(run.merged_output_json or {})
    evaluation_summary = evaluate_flow_test_output(
        run_status=run.status,
        output=output,
        expected_output=test_case.get("expected_output") if isinstance(test_case.get("expected_output"), dict) else {},
        assertions=test_case.get("assertions") if isinstance(test_case.get("assertions"), list) else [],
    )
    updated = {
        **test_case,
        "previous_run_id": test_case.get("last_run_id"),
        "last_run_id": run.id,
        "last_status": run.status,
        "last_evaluation_status": evaluation_summary["status"],
        "last_passed": evaluation_summary["passed"],
        "last_output": output,
        "last_evaluation_summary": evaluation_summary,
        "changed_since_previous": previous_output not in (None, {}) and previous_output != output,
        "updated_at": utc_now().isoformat(),
    }
    test_cases[index] = updated
    await _save_test_cases(db, version=version, test_cases=test_cases)
    return {
        "test_case": updated,
        "run_id": run.id,
        "status": run.status,
        "passed": evaluation_summary["passed"],
        "evaluation_summary": evaluation_summary,
        "assertion_results": evaluation_summary["results"],
        "output": output,
    }


async def batch_run_flow_test_cases(
    db: AsyncSession,
    *,
    flow_id: str,
    test_case_ids: list[str] | None,
    current_user: User,
) -> dict[str, Any]:
    version = await _current_version(db, flow_id=flow_id)
    ids = set(test_case_ids or [])
    cases = [case for case in _test_cases(version) if not ids or case.get("id") in ids][:MAX_BATCH_CASES]
    for case in cases:  # every case's Workspace before the first run starts
        await require_flow_start_workspace(db, current_user.id, _case_workspace(case))
    results = []
    for case in cases:
        result = await run_flow_test_case(db, flow_id=flow_id, test_case_id=str(case["id"]), current_user=current_user)
        results.append(result)
    return {
        "flow_id": flow_id,
        "version_id": version.id,
        "count": len(results),
        "passed": sum(1 for result in results if result.get("passed") is True),
        "failed": sum(1 for result in results if result.get("passed") is False),
        "results": results,
    }


async def run_partial_flow_version(
    db: AsyncSession,
    *,
    version_id: str,
    node_id: str,
    project_id: str | None,
    initial_input: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    try:
        version = await load_flow_version(db, version_id)
        ensure_runnable(version)
    except FlowVersionStateError as error:
        raise error.to_http() from None
    run = await execute_v2_partial_flow_dag(
        db,
        version=version,
        start_node_id=node_id,
        parent_session_id=None,
        project_id=project_id,
        initial_input=initial_input,
        user_id=current_user.id,
        agent_type="change",
    )
    return {"run_id": run.id, "status": run.status, "output": dict(run.merged_output_json or {})}


def _case_workspace(test_case: dict[str, Any]) -> str | None:
    return str(test_case.get("project_id") or "").strip() or None


async def _current_version(db: AsyncSession, *, flow_id: str) -> FlowDefinitionVersion:
    flow = await db.get(FlowDefinition, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow definition not found")
    version_id = flow.current_version_id
    if not version_id:
        detail = await get_flow_definition(db, flow_id=flow_id)
        versions = detail.get("versions") or []
        version_id = versions[-1]["id"] if versions else None
    version = await db.get(FlowDefinitionVersion, version_id) if version_id else None
    if version is None:
        raise HTTPException(status_code=404, detail="Flow definition version not found")
    return version


def _test_cases(version: FlowDefinitionVersion) -> list[dict[str, Any]]:
    settings = dict(version.runtime_settings or {})
    cases = settings.get("test_cases")
    return [dict(case) for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []


async def _save_test_cases(
    db: AsyncSession,
    *,
    version: FlowDefinitionVersion,
    test_cases: list[dict[str, Any]],
) -> None:
    version.runtime_settings = {**dict(version.runtime_settings or {}), "test_cases": test_cases}
    await db.flush()


def _find_test_case(test_cases: list[dict[str, Any]], test_case_id: str) -> tuple[int, dict[str, Any]]:
    for index, test_case in enumerate(test_cases):
        if test_case.get("id") == test_case_id:
            return index, dict(test_case)
    raise HTTPException(status_code=404, detail="Flow test case not found")


__all__ = [
    "batch_run_flow_test_cases",
    "create_flow_test_case",
    "delete_flow_test_case",
    "list_flow_test_cases",
    "run_flow_test_case",
    "run_partial_flow_version",
    "update_flow_test_case",
]
