"""One request slot at a time, and real related resources, for every route that takes a Workspace id.

A route can name a Workspace in several places (path, query, form, body) and a related resource in its path or in a
request field a guarding dependency reads (``workspace_resource_rows``). Each place is varied on its own while every
other one stays valid and constant (the caller's own Workspace, the caller's own related rows, no other reference):

- a foreign shared Workspace, somebody else's private one and an unknown id in one Workspace slot answer the same
  for every persona; an unknown id there is refused for a platform admin too;
- a real resource of a foreign shared or private Workspace in one related-resource slot answers exactly like an id
  that names nothing, for a Work operator and a delegated admin-panel permission holder who own their Workspace;
  the caller's own resource in the same slot is the positive control that the persona reaches the handler.

Nothing is read, written or sent for a refused request (``workspace_id_route_inventory``).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models.project.private_guard import REASON as PRIVATE_NO_WORK
from tests.knowledge_evidence_seed_support import seed_member
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import (
    build_request,
    changed,
    record_side_effects,
    refuses_an_unknown_workspace,
    request_slots,
    snapshot,
    workspace_routes,
)
from tests.workspace_id_route_support import (  # noqa: F401 - the autouse fixtures, active by import
    FOREIGN_MARKER,
    _fixtures_on,
    _platform_configured,
    answer_text,
    compare_answers,
    foreign_workspaces,
    personas_of,
    refusal_code,
)
from tests.workspace_resource_rows import reference_rows_of, resource_rows_of, seed_resource

pytestmark = pytest.mark.asyncio

ROUTES = workspace_routes()
MULTI_SLOT = [(case, slot) for case in ROUTES if len(slots := request_slots(case)) > 1 for slot in slots]


@pytest.mark.parametrize(("case", "slot"), MULTI_SLOT,
                         ids=[f"{case.method} {case.path} [{':'.join(slot)}]" for case, slot in MULTI_SLOT])
async def test_one_workspace_slot_at_a_time_answers_foreign_like_unknown(client, db, auth_headers, monkeypatch,
                                                                       case, slot):
    """Only ``slot`` names the foreign or unknown Workspace; every other Workspace slot names the caller's own."""
    from tests.phased_workflow_fixtures import admin_user

    mine, personas = await personas_of(db, "owner", names=("owner", "operator", "delegated"))
    foreign = await foreign_workspaces(db)
    await db.commit()
    label = f"{case.method} {case.path} [{':'.join(slot)}]"
    if refuses_an_unknown_workspace(case):
        request = build_request(case, str(uuid.uuid4()), (await admin_user(db)).id, own_workspace_id=mine,
                                varied=slot)
        before = await snapshot(db)
        effects = record_side_effects(monkeypatch)
        response = await client.request(case.method, headers=auth_headers, **request)
        assert response.status_code == 404, f"{label}: {response.text[:300]}"
        db.expire_all()
        assert changed(before, await snapshot(db)) == [], label
        assert effects.calls == [], label
    for persona, caller in personas.items():
        answers = await compare_answers(client, db, case, caller, {**foreign, "unknown": str(uuid.uuid4())},
                                        f"{label} as {persona}", own_workspace_id=mine, varied=slot)
        assert answers["shared"] == answers["unknown"] == answers["private"], f"{label} as {persona}: {answers}"


def _resource_slots(case) -> list[tuple[str, object]]:
    """The related-resource places of a route: its path parameters (``RESOURCE_ROWS``) and the request fields it reads
    (``REQUEST_REFERENCES``; not on a form upload)."""
    path = [("path", row) for row in resource_rows_of(case.path, [name for name, _type in case.path_types])]
    fields = [] if case.form or case.files else [
        ("field", row) for row in reference_rows_of(case.dependencies, case.method, case.path)]
    return path + fields


RESOURCE_CASES = [(case, slots) for case in ROUTES if (slots := _resource_slots(case))]
RESOURCE_PERSONAS = ("operator", "delegated")


async def _seed(db, row, workspace_id: str, user_id: str) -> str:
    return await seed_resource(db, row.model, workspace_id=workspace_id, user_id=user_id, marker=FOREIGN_MARKER,
                               values=row.values)


async def _request(client, case, caller: str, mine: str, companions: dict[str, str], kind: str, row,
                   value: str):
    path_values = {**companions, row.param: value} if kind == "path" else companions
    references = {row.param: value} if kind == "field" else None
    request = build_request(case, mine, caller, path_values=path_values, references=references)
    return await client.request(case.method, headers=bearer(caller), **request)


@pytest.mark.parametrize(("case", "slots"), RESOURCE_CASES,
                         ids=[f"{case.method} {case.path}" for case, _slots in RESOURCE_CASES])
async def test_a_related_resource_of_another_workspace_answers_like_a_missing_one(client, db, case, slots):
    """One related-resource slot at a time names a real row of a foreign shared Workspace, of somebody else's
    private one, or an id that names nothing; the caller's own Workspace fills every Workspace slot and the caller's
    own rows every other path resource. Foreign and missing answer the same, and nothing is read, written or sent;
    the caller's own row in the slot shows the persona reaches the handler (``reached``)."""
    mine, personas = await personas_of(db, "owner", names=RESOURCE_PERSONAS)
    foreign = await foreign_workspaces(db)
    owner = await seed_member(db, workspace_id=foreign["shared"], role="owner")
    companions = {row.param: await _seed(db, row, mine, personas["operator"]) for kind, row in slots if kind == "path"}
    await db.commit()
    reached: dict[str, list[str]] = {persona: [] for persona in personas}
    for kind, row in slots:
        values: dict[str, str] = {}
        for where, workspace_id in foreign.items():
            try:
                async with db.begin_nested():
                    values[where] = await _seed(db, row, workspace_id, owner)
            except HTTPException as refused:  # no Work exists in a private Workspace (``models/project/private_guard``)
                assert where == "private" and refused.detail["reason"] == PRIVATE_NO_WORK, refused.detail
        values["missing"] = str(uuid.uuid4())
        own = await _seed(db, row, mine, personas["operator"])
        await db.commit()
        for persona, caller in personas.items():
            label = f"{case.method} {case.path} [{kind}:{row.param}] as {persona}"
            before, answers = await snapshot(db), {}
            for where, value in values.items():
                with pytest.MonkeyPatch.context() as patch:
                    effects = record_side_effects(patch)
                    response = await _request(client, case, caller, mine, companions, kind, row, value)
                assert effects.calls == [], f"{label} sent for the {where} row: {effects.calls}"
                assert FOREIGN_MARKER not in response.text, f"{label} disclosed the {where} row: {response.text[:300]}"
                answers[where] = (response.status_code, refusal_code(response),
                                  answer_text(response, mine, value, *companions.values()))
            db.expire_all()
            assert changed(before, await snapshot(db)) == [], f"{label} wrote"
            for where in answers.keys() - {"missing"}:
                assert answers[where] == answers["missing"], f"{label}: {where} {answers[where]} != {answers['missing']}"
            if await _reaches(client, case, caller, mine, companions, kind, row, own, answers["missing"]):
                reached[persona].append(f"{kind}:{row.param}")
    # Positive control: the caller's own row gets past every reference of a Secure Work route (the scope dependency
    # answers before any role check, so the delegated admin reaches it too); elsewhere the operator reaches it.
    if case.path.startswith("/api/v1/secure-work/"):
        assert all(reached.values()), (case.path, reached)
    assert reached["operator"], (case.path, reached)


async def _reaches(client, case, caller, mine, companions, kind, row, own: str, missing: tuple) -> bool:
    """Whether the caller's own row in the slot gets past the reference (an answer other than the missing one)."""
    with pytest.MonkeyPatch.context() as patch:
        record_side_effects(patch)
        try:
            response = await _request(client, case, caller, mine, companions, kind, row, own)
        except RuntimeError:  # an outbound call the sweep refuses to perform: the handler ran
            return True
    return (response.status_code, refusal_code(response), answer_text(response, mine, own, *companions.values())) \
        != missing
