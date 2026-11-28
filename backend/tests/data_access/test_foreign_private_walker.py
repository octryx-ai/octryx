"""A foreign private row of every Workspace-bound model, on every GET route: by id like an unknown id once its owner
reads it there, lists and counts unchanged, nothing written, for an admin, an anonymous caller and a member."""

from __future__ import annotations

import pytest

from tests.data_access.foreign_private_walk_support import (
    WRITES_ON_READ,
    answer,
    case_urls,
    id_cases,
    list_routes,
    platform_parents,
    seed,
    unclassified_params,
    url,
    world,
)
from tests.data_access.walker_positive_controls import NO_POSITIVE_CONTROL, VOLATILE_LISTS
from tests.workspace_id_route_inventory import changed, snapshot
from tests.workspace_id_route_support import _fixtures_on, _platform_configured  # noqa: F401 - autouse

LISTS = list_routes()
BY_ID = id_cases()


def test_every_path_parameter_is_classified():
    assert unclassified_params() == set()


def test_every_route_without_a_positive_control_still_exists():
    assert set(NO_POSITIVE_CONTROL) - {case.name for case in BY_ID} == set()


def test_a_volatile_list_names_exactly_one_list_route_each():
    assert set(VOLATILE_LISTS) <= {route.path for route in LISTS}
    assert all("{" not in path and "*" not in path for path in VOLATILE_LISTS)


async def _answers(client, scene, path: str, *masked: str) -> dict[str, tuple | None]:
    return {name: await answer(client, path, caller, *masked) for name, caller in scene.outsiders().items()}


async def _nothing_written(db, before, route) -> None:
    db.expire_all()
    if route.path not in WRITES_ON_READ:
        assert changed(before, await snapshot(db)) == [], route.path


@pytest.mark.parametrize("route", LISTS, ids=[route.path for route in LISTS])
async def test_a_list_or_count_never_changes_for_an_outsider_when_a_foreign_private_row_appears(client, db, route):
    scene = await world(db)
    path = url(route, scene.shared)
    seeding = await platform_parents(db, scene)
    first, second = await _answers(client, scene, path), await _answers(client, scene, path)
    rows = await seeding.workspace_rows()
    before = await snapshot(db)
    after = await _answers(client, scene, path)
    await _nothing_written(db, before, route)
    for caller in after:
        leaked = [f"{table}:{row['id']}" for table, row in rows.rows.items()
                  if isinstance(row.get("id"), str) and row["id"] in str(after[caller])]
        assert not leaked, f"{path} as {caller} shows {leaked[:3]}"
        if route.path not in VOLATILE_LISTS and first[caller] is not None and first[caller] == second[caller]:
            assert after[caller] == first[caller], f"{path} as {caller}: {first[caller]} -> {after[caller]}"


@pytest.mark.parametrize("case", BY_ID, ids=[case.name for case in BY_ID])
async def test_a_foreign_private_row_by_id_answers_an_outsider_like_an_unknown_id(client, db, case):
    scene = await world(db)
    rows = await seed(db, scene)
    reached = []
    for table in case.tables:
        known, unknown, known_id, unknown_id = case_urls(case, table, rows)
        if (await answer(client, known, scene.owner, known_id, unknown_id))[0] != 200:
            continue  # the route reads another of the parameter's tables
        reached.append(table)
        before = await snapshot(db)
        seen = await _answers(client, scene, known, known_id, unknown_id)
        missing = await _answers(client, scene, unknown, known_id, unknown_id)
        await _nothing_written(db, before, case.route)
        for caller in seen:
            assert seen[caller] == missing[caller], f"{case.name}={table} as {caller}"
    if case.name in NO_POSITIVE_CONTROL:
        assert not reached, f"{case.name} has a positive control now: drop it from NO_POSITIVE_CONTROL"
        pytest.skip(NO_POSITIVE_CONTROL[case.name])
    assert reached, f"{case.name}: its owner never reads a seeded row ({', '.join(case.tables)})"
