"""Change Plan list filters and cursors: contradictory filters and untrusted cursors are a 422, a cursor walk is complete, ordered and rescoped on every page, and the query count per page is constant."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.services.secure_work.plans.plan_listing import encode_plan_cursor
from tests.services.secure_work.secure_work_change_plan_listing_support import (  # noqa: F401
    BASE,
    URL,
    _admin,
    _item,
    _plan,
    _project,
    _user,
    plan_api,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"queue": "review", "status": "approved"},
        {"status": "approved_later"},
        {"status": ""},
        {"queue": "code"},
        {"status": "superseded", "include_superseded": "false"},
        {"limit": "201"},
        {"limit": "0"},
        {"cursor": "not-base64-!!"},
        {"cursor": "x" * 300},
        {"statuses": "approved"},
    ],
)
async def test_contradictory_or_unknown_filters_are_422(db, plan_api, params):  # noqa: F811
    client, state = plan_api
    state["user"] = await _admin(db)
    response = await client.get(URL, params=params)
    assert response.status_code == 422, (params, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    [
        encode_plan_cursor(BASE, "id-1")[:-3] + "AAA",
        "eyJ2IjoxLCJhdCI6IjIwMjYtMTAtMDFUMTI6MDA6MDAifQ",  # {"v":1,"at":...} without id
        "eyJ2IjoyLCJhdCI6IjIwMjYtMTAtMDFUMTI6MDA6MDAiLCJpZCI6ImEifQ",  # version 2
        "eyJ2IjoxLCJhdCI6Im5vdC1hLWRhdGUiLCJpZCI6ImEifQ",  # bad date
        "eyJ2IjoxLCJhdCI6IjIwMjYtMTAtMDFUMTI6MDA6MDAiLCJpZCI6ImEnOyBkcm9wIn0",  # id with quotes
        "WzEsMiwzXQ",  # a JSON list
        # Valid ISO text whose offset leaves datetime's range when normalized to UTC (was HTTP 500).
        "eyJ2IjogMSwgImF0IjogIjAwMDEtMDEtMDFUMDA6MDA6MDArMTQ6MDAiLCAiaWQiOiAidGVzdCJ9",  # underflow
        "eyJ2IjogMSwgImF0IjogIjk5OTktMTItMzFUMjM6NTk6NTktMTQ6MDAiLCAiaWQiOiAidGVzdCJ9",  # overflow
        # The version must be exactly the integer 1: JSON true, 1.0 and "1" are refused.
        "eyJ2IjogdHJ1ZSwgImF0IjogIjIwMjYtMTAtMDFUMTI6MDA6MDAiLCAiaWQiOiAidGVzdCJ9",
        "eyJ2IjogMS4wLCAiYXQiOiAiMjAyNi0xMC0wMVQxMjowMDowMCIsICJpZCI6ICJ0ZXN0In0",
        "eyJ2IjogIjEiLCAiYXQiOiAiMjAyNi0xMC0wMVQxMjowMDowMCIsICJpZCI6ICJ0ZXN0In0",
        "eyJ2IjogMSwgImF0IjogMjAyNjEwMDEsICJpZCI6ICJ0ZXN0In0",  # numeric time
        "eyJ2IjogMSwgImF0IjogIjIwMjYtMTAtMDFUMTI6MDA6MDAiLCAiaWQiOiA3fQ",  # numeric id
    ],
)
async def test_untrusted_cursor_shapes_are_422(db, plan_api, cursor):  # noqa: F811
    client, state = plan_api
    state["user"] = await _admin(db)
    assert (await client.get(URL, params={"cursor": cursor})).status_code == 422


@pytest.mark.asyncio
async def test_cursor_walk_is_complete_ordered_and_rescoped_on_every_page(db, plan_api):  # noqa: F811
    client, state = plan_api
    admin = await _admin(db)
    project = await _project(db, "Plans Walk")
    other = await _project(db, "Plans Other")
    item = await _item(db, "APP-1", project.id)
    foreign = await _item(db, "DOC-1", other.id)
    mine = [await _plan(db, item, admin, version=index + 1, status="approved", minutes=index) for index in range(5)]
    # Two plans share one timestamp: the id breaks the tie deterministically.
    tie = await _plan(db, item, admin, version=6, status="approved", minutes=2)
    await _plan(db, foreign, admin, version=1, status="approved", minutes=3)

    state["user"] = admin
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": "2", "project_id": project.id, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(URL, params=params)).json()
        seen.extend(row["id"] for row in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 6
    expected = sorted([*mine, tie], key=lambda plan: (plan.updated_at, plan.id), reverse=True)
    assert seen == [plan.id for plan in expected]

    # A cursor taken from an admin page grants nothing: the member's next page is still scoped.
    admin_page = (await client.get(URL, params={"limit": "1"})).json()
    state["user"] = await _user(db, "plan-walk-member", projects=(project.id,))
    member_page = (await client.get(URL, params={"cursor": admin_page["next_cursor"], "limit": "200"})).json()
    assert {row["work_item_id"] for row in member_page["items"]} <= {item.id}


@pytest.mark.asyncio
async def test_query_count_is_constant_per_page(db, plan_api):  # noqa: F811
    client, state = plan_api
    admin = await _admin(db)
    project = await _project(db, "Plans Count")
    state["user"] = await _user(db, "plan-count-member", projects=(project.id,))
    statements: list[str] = []
    bind = db.sync_session.get_bind()

    def count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    async def selects_for(plan_count: int) -> int:
        for index in range(plan_count):
            item = await _item(db, f"NCQ-{plan_count}-{index}", project.id)
            await _plan(db, item, admin, version=1, status="ready_for_review", minutes=index)
        statements.clear()
        event.listen(bind, "before_cursor_execute", count)
        try:
            response = await client.get(URL, params={"limit": "200"})
        finally:
            event.remove(bind, "before_cursor_execute", count)
        assert response.status_code == 200
        return len(statements)

    small = await selects_for(2)
    large = await selects_for(20)
    # Role check, workspace scope, counts and page: a few statements, independent of the row count.
    assert small >= 3, statements
    assert small == large, (small, large)
