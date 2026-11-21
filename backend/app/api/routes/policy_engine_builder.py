"""Cedar policy engine admin API, the guided builder. Platform admins only.

Under ``/api/v1/admin/policy-engine``:

- ``POST /policy-builder/render`` ``{model}`` — the live preview: the generated Cedar, the plain-language sentence,
  the scope, warnings and every issue (model and schema); nothing is saved. Custom detectors
  resolve against the working version (open draft, else published).
- ``PUT /policy-sets/{version}/policies/{policy_id}`` ``{model | cedar, note?, create?}`` with ``If-Match: <digest of
  {version}>`` — save one policy into the draft (a new draft from the published version, or from the empty set
  when ``version`` is 0); ``DELETE`` the same path removes it. ``409 policy_set_draft_conflict`` when the draft
  changed meanwhile; ``422`` with the issues when the result does not validate.
- ``POST /test-bench/generate`` ``{model, original_id?}`` — impact examples: up to three questions the policy
  must block and one control it must leave alone, answered by the test bench against the working draft with this
  policy in it, plus the saved test cases against the same candidate.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import DetectorSetError

from ...db import get_db
from ...models import User
from ...services.policy_engine import store
from ...services.policy_engine.builder import render
from ...services.policy_engine.builder_content import custom_categories
from ...services.policy_engine.builder_model import model_from_json
from ...services.policy_engine.builder_sentence import scope, sentence
from ...services.policy_engine.custom_policies import CustomPolicyError, check_custom_policies
from ...services.policy_engine.entity_listing import load_name_index
from ...services.policy_engine.impact import impact
from ...services.policy_engine.policy_edits import PolicyEditError, delete_policy, open_or_published, put_policy
from ...services.policy_engine.policy_sentence import warnings
from ...services.policy_engine.policy_view import describe, index
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/policy-engine", tags=["policy-engine"])


def _edit_refusal(error: PolicyEditError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, **error.details})


async def _read_model(db: AsyncSession, raw: Any):
    """The model with the working version's custom detectors; an invalid stored set leaves them unknown."""
    try:
        definitions = store.detector_definitions(await open_or_published(db))
    except DetectorSetError:
        return model_from_json(raw, {})
    return model_from_json(raw, custom_categories(definitions))


@router.post("/policy-builder/render")
async def render_model(
    body: dict[str, Any] = Body(...), _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    model, issues = await _read_model(db, body.get("model"))
    if model is None:
        return {"valid": False, "issues": issues, "text": "", "sentence": [], "scope": "", "warnings": []}
    text = render(model)
    names = await load_name_index(db)
    try:
        check_custom_policies(text)
    except CustomPolicyError as error:
        issues = [{"path": "", "code": error.code, "message": item.get("message", "")} for item in error.issues]
    (statement,) = index(text)
    return {"valid": not issues, "issues": issues, "text": text, "sentence": sentence(model, names),
            "scope": scope(model, names), "warnings": warnings(statement, names)}


@router.post("/test-bench/generate")
async def generate_examples(
    body: dict[str, Any] = Body(...), _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Questions this policy must block and one it must leave alone, answered against the draft with it."""
    model, issues = await _read_model(db, body.get("model"))
    if model is None:
        raise HTTPException(status_code=422, detail={"code": "policy_builder_model_invalid", "issues": issues})
    original = body.get("original_id")
    if original is not None and not isinstance(original, str):
        raise HTTPException(status_code=422, detail={"code": "policy_bench_request_invalid", "path": "original_id"})
    try:
        return await impact(db, model, original)
    except CustomPolicyError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues}) from None


async def _answer(db: AsyncSession, row, policy_id: str | None) -> dict[str, Any]:
    names = await load_name_index(db)
    item = next((describe(statement, names) for statement in index(row.policies_text)
                 if statement.policy_id == policy_id), None) if policy_id else None
    return {"version": store.serialize_version(row), "policy": item}


@router.put("/policy-sets/{version}/policies/{policy_id:path}")
async def put_version_policy(
    version: int, policy_id: str, body: dict[str, Any] = Body(...), if_match: str | None = Header(default=None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row, saved_id = await put_policy(db, version, policy_id, body, if_match=if_match, actor_id=user.id)
    except PolicyEditError as error:
        raise _edit_refusal(error) from None
    except CustomPolicyError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues}) from None
    except store.PolicyStoreRefusalError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, **error.details}) from None
    await db.commit()
    return await _answer(db, row, saved_id)


@router.delete("/policy-sets/{version}/policies/{policy_id:path}")
async def delete_version_policy(
    version: int, policy_id: str, if_match: str | None = Header(default=None), user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await delete_policy(db, version, policy_id, if_match=if_match, note=f"Remove {policy_id}",
                                  actor_id=user.id)
    except PolicyEditError as error:
        raise _edit_refusal(error) from None
    except CustomPolicyError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "issues": error.issues}) from None
    except store.PolicyStoreRefusalError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, **error.details}) from None
    await db.commit()
    return await _answer(db, row, None)


__all__ = ["router"]
