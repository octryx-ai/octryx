"""Saved policy test cases: a bench question plus its expected answer."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, PolicyTestCase
from ...time_utils import utc_now
from .bench_question import BenchError, parse_question
from .engine import text_digest
from .test_bench import CustomText, ask

EXPECTED = ("allow", "deny")
MAX_CASES = 500
ERROR_CASE_INVALID = "policy_test_case_invalid"
ERROR_CASE_NOT_FOUND = "policy_test_case_not_found"
ERROR_TOO_MANY = "policy_test_cases_too_many"
AUDIT_SAVED = "policy_engine.test_case_saved"
AUDIT_DELETED = "policy_engine.test_case_deleted"


async def list_cases(db: AsyncSession) -> list[PolicyTestCase]:
    return list((await db.execute(select(PolicyTestCase).order_by(PolicyTestCase.name, PolicyTestCase.id))).scalars())


def serialize_case(row: PolicyTestCase) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "expected": row.expected, "request": row.request,
            "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None}


async def create_case(db: AsyncSession, *, body: Any, actor_id: str) -> PolicyTestCase:
    if not isinstance(body, dict):
        raise BenchError(ERROR_CASE_INVALID)
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 120:
        raise BenchError(ERROR_CASE_INVALID, path="name")
    if body.get("expected") not in EXPECTED:
        raise BenchError(ERROR_CASE_INVALID, path="expected")
    question = parse_question(body.get("request"))
    if len(await list_cases(db)) >= MAX_CASES:
        raise BenchError(ERROR_TOO_MANY, 409)
    now = utc_now()
    row = PolicyTestCase(name=name, request=question.to_json(), expected=body["expected"], created_by=actor_id,
                         created_at=now, updated_at=now)
    db.add(row)
    await db.flush()
    db.add(AuditLog(user_id=actor_id, action=AUDIT_SAVED, resource_type="policy_test_case", resource_id=row.id,
                    details={"name": name, "expected": row.expected, "action": question.action}))
    await db.flush()
    return row


async def delete_case(db: AsyncSession, *, case_id: str, actor_id: str) -> None:
    row = await db.get(PolicyTestCase, case_id)
    if row is None:
        raise BenchError(ERROR_CASE_NOT_FOUND, 404)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_DELETED, resource_type="policy_test_case", resource_id=row.id,
                    details={"name": row.name}))
    await db.delete(row)
    await db.flush()


async def run_cases(db: AsyncSession, custom: CustomText) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for row in await list_cases(db):
        try:
            answer = await ask(db, parse_question(row.request), custom)
            actual, determining, error = answer["decision"], [item["id"] for item in answer["determining"]], None
        except BenchError as refusal:
            actual, determining, error = "error", [], refusal.code
        results.append({"id": row.id, "name": row.name, "expected": row.expected, "actual": actual,
                        "passed": actual == row.expected, "determining": determining, "error": error})
    failed = sum(1 for item in results if not item["passed"])
    return {"ran_at": utc_now().isoformat(), "custom_digest": text_digest(custom.text), "total": len(results),
            "failed": failed, "ok": failed == 0, "results": results}


__all__ = [
    "EXPECTED",
    "create_case",
    "delete_case",
    "list_cases",
    "run_cases",
    "serialize_case",
]
