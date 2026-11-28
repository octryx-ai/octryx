"""The MCP plan tools require the work-operator role before any lookup, never disclose out-of-scope items and allow operator members, groups and admins."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.services import mcp_secure_work_tools as work_tools
from app.services.mcp_work_access import build_work_grant_scope
from tests.support.secure_work_plan_access_support import _side_effects, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def _with_unrestricted_grant(handler):
    async def call(db, *, user, arguments):
        scope = await build_work_grant_scope(db, user=user, grant_id=None, binding=None)
        return await handler(db, user=user, scope=scope, arguments=arguments)

    call.__name__ = handler.__name__
    return call


mcp_change_plan_decide = _with_unrestricted_grant(work_tools.mcp_change_plan_decide)


mcp_change_plan_generate = _with_unrestricted_grant(work_tools.mcp_change_plan_generate)


mcp_work_item_context = _with_unrestricted_grant(work_tools.mcp_work_item_context)


mcp_work_item_find = _with_unrestricted_grant(work_tools.mcp_work_item_find)


mcp_work_item_redeclare = _with_unrestricted_grant(work_tools.mcp_work_item_redeclare)


async def test_mcp_plan_mutations_require_work_operator_before_lookup(db, world):  # noqa: F811
    plain = world["plain_member"]
    item, plan = world["own"]
    before = await _side_effects(db, item)
    for reference in (item.source_key, item.id, "OCX-ACCESS-MISSING"):
        for handler, arguments in (
            (mcp_change_plan_generate, {"work_item": reference}),
            (mcp_work_item_redeclare, {"work_item": reference, "reason": "denied probe"}),
        ):
            with pytest.raises(HTTPException) as exc:
                await handler(db, user=plain, arguments=arguments)
            assert exc.value.status_code == 403 and "operation role" in exc.value.detail, (handler.__name__, reference)
    for plan_id in (plan.id, str(uuid.uuid4())):
        with pytest.raises(HTTPException) as exc:
            await mcp_change_plan_decide(
                db, user=plain, arguments={"change_plan_id": plan_id, "action": "reject", "reason": "denied probe"}
            )
        assert exc.value.status_code == 403 and "operation role" in exc.value.detail
    assert await _side_effects(db, item) == before

    assert (await mcp_work_item_find(db, user=plain, arguments={"work_item": item.source_key}))["id"] == item.id
    context = await mcp_work_item_context(db, user=plain, arguments={"work_item": item.id})
    assert context["latest_plan"]["id"] == plan.id


async def test_mcp_plan_tools_do_not_disclose_out_of_scope_items(db, world):  # noqa: F811
    outsider, member = world["outsider"], world["member"]
    cases = ((outsider, "own"), (outsider, "foreign"), (outsider, "null"), (member, "foreign"), (member, "null"))
    for user, scope in cases:
        item, plan = world[scope]
        before = await _side_effects(db, item)
        for reference in (item.source_key, item.id):
            for handler, arguments in (
                (mcp_work_item_find, {"work_item": reference}),
                (mcp_work_item_context, {"work_item": reference}),
                (mcp_change_plan_generate, {"work_item": reference}),
                (mcp_work_item_redeclare, {"work_item": reference, "reason": "denied probe"}),
            ):
                with pytest.raises(HTTPException) as exc:
                    await handler(db, user=user, arguments=arguments)
                assert (exc.value.status_code, exc.value.detail) == (404, f"Work item not found: {reference}"), (
                    handler.__name__,
                    scope,
                )
        with pytest.raises(HTTPException) as exc:
            await mcp_change_plan_decide(
                db, user=user, arguments={"change_plan_id": plan.id, "action": "reject", "reason": "denied probe"}
            )
        assert (exc.value.status_code, exc.value.detail) == (404, "Change Plan not found")
        assert await _side_effects(db, item) == before

    for handler, arguments in (
        (mcp_work_item_find, {"work_item": "OCX-ACCESS-MISSING"}),
        (mcp_change_plan_generate, {"work_item": "OCX-ACCESS-MISSING"}),
    ):
        with pytest.raises(HTTPException) as exc:
            await handler(db, user=member, arguments=arguments)
        assert (exc.value.status_code, exc.value.detail) == (404, "Work item not found: OCX-ACCESS-MISSING")
    with pytest.raises(HTTPException) as exc:
        await mcp_change_plan_decide(
            db, user=member, arguments={"change_plan_id": str(uuid.uuid4()), "action": "reject"}
        )
    assert (exc.value.status_code, exc.value.detail) == (404, "Change Plan not found")


async def test_mcp_plan_tools_allow_operator_members_groups_and_admin(db, world):  # noqa: F811
    member, group_member, admin = world["member"], world["group_member"], world["admin"]
    item, plan = world["own"]
    assert (await mcp_work_item_find(db, user=member, arguments={"work_item": item.id}))[
        "source_key"
    ] == item.source_key
    assert (await mcp_work_item_context(db, user=group_member, arguments={"work_item": item.source_key}))[
        "latest_plan"
    ]["id"] == plan.id

    generated = await mcp_change_plan_generate(db, user=member, arguments={"work_item": item.source_key})
    assert generated["version"] == 2
    decided = await mcp_change_plan_decide(
        db,
        user=group_member,
        arguments={"change_plan_id": generated["id"], "action": "reject", "reason": "Scope is unclear."},
    )
    assert decided["status"] == "rejected"
    redeclared = await mcp_work_item_redeclare(
        db, user=group_member, arguments={"work_item": item.id, "reason": "Declined PR."}
    )
    assert redeclared["work_item_id"] == item.id

    null_item, null_plan = world["null"]
    assert (await mcp_work_item_find(db, user=admin, arguments={"work_item": null_item.source_key}))[
        "id"
    ] == null_item.id
    assert (await mcp_work_item_context(db, user=admin, arguments={"work_item": null_item.id}))["latest_plan"][
        "id"
    ] == null_plan.id
    admin_decided = await mcp_change_plan_decide(
        db,
        user=admin,
        arguments={"change_plan_id": null_plan.id, "action": "request_clarification", "reason": "Name the owner."},
    )
    assert admin_decided["status"] == "needs_clarification"
    admin_redeclared = await mcp_work_item_redeclare(
        db, user=admin, arguments={"work_item": null_item.source_key, "reason": "Declined PR."}
    )
    assert admin_redeclared["superseded_plans"] == 1
