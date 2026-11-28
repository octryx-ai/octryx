"""A Workspace's content handling through ``/api/v1/workspaces/{ws}/content-handling``: what members read,
who may change it, and the audited transitions."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserProject, WorkspaceContentGovernance, WorkspaceContentHandling
from app.services.content_security import handling_settings
from app.services.content_security.handling_points import POINTS
from app.services.content_security.handling_preview import reroute_masked_at, reroute_unavailable
from tests.factories import make_project
from tests.policy_engine_support import bearer, make_user

ALIAS = "approved-model"


async def _workspace(db) -> str:
    return (await make_project(db, name=f"handling-{uuid.uuid4().hex[:6]}", commit=True)).id


async def _member(db, workspace_id: str, role: str) -> str:
    user_id = await make_user(db, admin=False)
    db.add(UserProject(user_id=user_id, project_id=workspace_id, role=role))
    await db.commit()
    return user_id


def _url(workspace_id: str, kind: str = "") -> str:
    base = f"/api/v1/workspaces/{workspace_id}/content-handling"
    return f"{base}/{kind}" if kind else base


@pytest.fixture(autouse=True)
def aliases(monkeypatch):
    async def approvals(_db):
        return {ALIAS: frozenset({"pii"})}

    monkeypatch.setattr(handling_settings, "alias_approvals", approvals)


async def test_a_member_reads_the_shipped_defaults_and_cannot_change_them(client, db) -> None:
    workspace = await _workspace(db)
    member = await _member(db, workspace, "member")

    body = (await client.get(_url(workspace), headers=bearer(member))).json()

    assert body["workspace_id"] == workspace and body["can_edit"] is False
    assert body["actions"] == ["refuse", "mask", "reroute", "mask_reroute", "report"]
    assert body["governance_alias"] is None
    assert body["governance_aliases"] == [{"alias": ALIAS, "label": ALIAS}]
    kinds = {item["kind"]: item for item in body["kinds"]}
    assert set(kinds) == {"secrets", "credential_assignment", "email", "internal_ip", "iban", "phone"}
    assert {kind: item["action"] for kind, item in kinds.items()} == {
        "secrets": "mask", "credential_assignment": "mask", "email": "mask", "internal_ip": "report",
        "iban": "none", "phone": "none"}
    assert all(item["is_default"] and item["action"] == item["default_action"] for item in kinds.values())
    defaults = {kind: {path["surface"]: path["action"] for path in item["default_actions"]} for kind, item in kinds.items()}
    assert defaults["email"] == {"platform": "mask", "gateway": "report"}, "a coding agent gets email recorded"
    assert defaults["secrets"] == {"platform": "mask", "gateway": "mask"}
    # Per point what the fixed rules do there: an unfinished part is withheld from a platform model call but refuses
    # the whole gateway request; a masked gateway request still carrying a mask kind is refused.
    fixed = {point["surface"]: {rule["rule"]: rule["action"] for rule in point["rules"]} for point in body["fixed"]}
    assert set(fixed) == {item.id for item in POINTS}
    assert fixed["model_call"] == {"unfinished": "withhold", "unreadable": "refuse", "prompt_injection": "refuse",
                                   "final_bytes": "refuse"}
    assert fixed["gateway_messages"] == {"unfinished": "refuse", "unreadable": "refuse", "prompt_injection": "refuse",
                                         "final_bytes": "refuse"}
    assert fixed["commands"] == {"unfinished": "review", "prompt_injection": "none"}
    # Every point that cannot reroute is listed, whatever the saved action; commands only for their kinds.
    assert {item["surface"] for item in kinds["email"]["reroute_unavailable"]} == {"model_call_direct", "codex_seat"}
    assert "commands" in {item["surface"] for item in kinds["secrets"]["reroute_unavailable"]}
    assert kinds["email"]["reroute_unavailable"] == reroute_unavailable("email")
    assert all(item["label"] for item in kinds["email"]["reroute_unavailable"])
    # The reply direction masks instead of refusing.
    assert [item["surface"] for item in kinds["email"]["reroute_masked_at"]] == ["model_output"]
    assert kinds["email"]["reroute_masked_at"] == reroute_masked_at("email")
    assert {item.id for item in POINTS if item.reroute == "unavailable"} == {"model_call_direct", "codex_seat",
                                                                              "commands"}

    refused = await client.put(_url(workspace, "email"), headers=bearer(member), json={"action": "report"})
    assert refused.status_code == 403
    assert (await db.execute(select(WorkspaceContentHandling))).scalars().all() == []


async def test_a_non_member_and_an_unknown_workspace_get_the_same_404(client, db) -> None:
    workspace = await _workspace(db)
    outsider = await make_user(db, admin=False)
    for url in (_url(workspace), _url(str(uuid.uuid4()))):
        answer = await client.get(url, headers=bearer(outsider))
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == "project_not_found"
    for url in (_url(workspace, "email"), _url(str(uuid.uuid4()), "email")):
        answer = await client.put(url, headers=bearer(outsider), json={"action": "report"})
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == "project_not_found"


async def test_an_admin_changes_a_kind_and_every_change_is_audited(client, db) -> None:
    workspace = await _workspace(db)
    owner = await _member(db, workspace, "owner")

    assert (await client.get(_url(workspace), headers=bearer(owner))).json()["can_edit"] is True
    changed = await client.put(_url(workspace, "secrets"), headers=bearer(owner), json={"action": "report"})
    assert changed.status_code == 200, changed.text
    entry = changed.json()
    assert (entry["kind"], entry["action"], entry["default_action"], entry["is_default"]) == (
        "secrets", "report", "mask", False)
    assert entry["reroute_unavailable"] == reroute_unavailable("secrets")
    assert entry["reroute_masked_at"] == reroute_masked_at("secrets")

    governed = await client.put(_url(workspace, "governance-alias"), headers=bearer(owner), json={"alias": ALIAS})
    assert governed.json() == {"workspace_id": workspace, "governance_alias": ALIAS}
    rerouted = await client.put(_url(workspace, "email"), headers=bearer(owner), json={"action": "mask_reroute"})
    assert rerouted.json()["action"] == "mask_reroute" and "reroute_alias" not in rerouted.json()
    reset = await client.put(_url(workspace, "secrets"), headers=bearer(owner), json={"action": "default"})
    assert reset.json()["action"] == "mask" and reset.json()["is_default"] is True
    again = await client.put(_url(workspace, "secrets"), headers=bearer(owner), json={"action": "default"})
    assert again.status_code == 200

    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "content_handling.changed")
                               .order_by(AuditLog.created_at))).scalars().all()
    details = [row.details for row in audits]
    assert details == [
        {"workspace_id": workspace, "kind": "secrets", "old": "default(mask)", "new": "report"},
        {"workspace_id": workspace, "kind": "governance_alias", "old": None, "new": ALIAS},
        {"workspace_id": workspace, "kind": "email", "old": "default(mask)", "new": "mask_reroute"},
        {"workspace_id": workspace, "kind": "secrets", "old": "report", "new": "default(mask)"},
    ], "an unchanged setting writes no audit row"
    assert all(row.user_id == owner for row in audits)
    stored = (await db.execute(select(WorkspaceContentHandling))).scalars().all()
    assert [(row.kind, row.action) for row in stored] == [("email", "mask_reroute")]
    governance = (await db.execute(select(WorkspaceContentGovernance))).scalars().all()
    assert [(row.workspace_id, row.governance_alias) for row in governance] == [(workspace, ALIAS)]


async def test_a_platform_admin_may_change_it(client, db) -> None:
    workspace = await _workspace(db)
    admin = await make_user(db, admin=True)
    answer = await client.put(_url(workspace, "iban"), headers=bearer(admin), json={"action": "mask"})
    assert answer.status_code == 200 and answer.json()["action"] == "mask"


@pytest.mark.parametrize(("kind", "body", "code"), [
    ("prompt_injection", {"action": "report"}, "content_handling_kind_unknown"),
    ("health", {"action": "report"}, "content_handling_kind_unknown"),
    ("email", {"action": "none"}, "content_handling_action_invalid"),
    ("email", {"action": "review"}, "content_handling_action_invalid"),
    ("email", ["report"], "content_handling_action_invalid"),
    ("email", {"action": "reroute"}, "content_handling_alias_required"),
    ("email", {"action": "mask_reroute"}, "content_handling_alias_required"),
])
async def test_an_invalid_change_is_refused_and_nothing_is_stored(client, db, kind, body, code) -> None:
    workspace = await _workspace(db)
    admin = await _member(db, workspace, "admin")
    answer = await client.put(_url(workspace, kind), headers=bearer(admin), json=body)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == code
    assert (await db.execute(select(WorkspaceContentHandling))).scalars().all() == []
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "content_handling.changed"))).first() is None


def _points(entry: dict, field: str = "surface_defaults") -> dict[str, tuple[str, str, str | None]]:
    return {item["surface"]: (item["configured_action"], item["action"], item["reason"]) for item in entry[field]}


async def test_the_effective_action_is_shown_per_enforcement_point(client, db) -> None:
    workspace = await _workspace(db)
    owner = await _member(db, workspace, "owner")
    kinds = {item["kind"]: item for item in (await client.get(_url(workspace), headers=bearer(owner))).json()["kinds"]}

    secrets = _points(kinds["secrets"])
    assert secrets["model_call"] == ("mask", "mask", None)
    for point in ("gateway_messages", "gateway_responses", "codex_seat"):
        assert secrets[point] == ("mask", "mask", None)
    assert secrets["commands"] == ("review", "review", None)
    assert set(_points(kinds["email"])) == {item.id for item in POINTS} - {"commands"}
    assert _points(kinds["email"])["gateway_messages"] == ("report", "report", None)  # email in code is real data

    assert set(kinds["email"]["surface_choices"]) == {"refuse", "mask", "reroute", "mask_reroute", "report", "default"}
    for choice in ("refuse", "mask", "reroute", "mask_reroute", "report"):
        email_choice = {item["surface"]: item for item in kinds["email"]["surface_choices"][choice]}
        for point in ("gateway_messages", "gateway_responses"):
            assert (email_choice[point]["action"], email_choice[point]["reason"]) == (choice, None)
        seat = email_choice["codex_seat"]
        assert (seat["action"], seat["reason"]) == (("refuse", "content_route_unavailable")
                                                    if choice in ("reroute", "mask_reroute") else (choice, None))
    reroute = {item["surface"]: item for item in kinds["email"]["surface_choices"]["reroute"]}
    assert (reroute["model_call"]["action"], reroute["model_output"]["action"]) == ("reroute", "mask")
    assert (reroute["model_call_direct"]["action"], reroute["model_call_direct"]["reason"]) == (
        "refuse", "content_route_unavailable")
    report = {item["surface"]: item["action"] for item in kinds["secrets"]["surface_choices"]["report"]}
    assert report["gateway_messages"] == report["model_call"] == "report"
    assert kinds["secrets"]["surface_choices"]["default"] == kinds["secrets"]["surface_defaults"]

    saved = (await client.put(_url(workspace, "email"), headers=bearer(owner), json={"action": "mask"})).json()
    email = _points(saved)
    assert email["model_call"] == ("mask", "mask", None)
    assert email["gateway_responses"] == ("mask", "mask", None)
    assert email["tool_results"] == ("mask", "none", "deferred_to_model_entrance")
    choices = kinds["secrets"]["surface_choices"]
    commands = {choice: next(item for item in choices[choice] if item["surface"] == "commands")
                for choice in ("mask", "refuse", "report")}
    assert [(item["action"], item["reason"]) for item in commands.values()] == [
        ("review", "command_review"), ("deny", "command_denied"), ("report", None)]
    listed = {item["surface"] for item in saved["reroute_unavailable"]}
    assert "codex_seat" in listed and listed.isdisjoint({"gateway_messages", "gateway_responses"})


async def _racing_reads(monkeypatch, count: int) -> None:
    arrived, release = [], asyncio.Event()
    read = handling_settings.stored_row

    async def stored_row(db, workspace_id, kind):
        row = await read(db, workspace_id, kind)
        arrived.append(kind)
        if len(arrived) >= count:
            release.set()
        try:  # under row locks (PostgreSQL) the second read waits for the first edit instead: serialized
            await asyncio.wait_for(release.wait(), timeout=2)
        except TimeoutError:
            pass
        return row

    monkeypatch.setattr(handling_settings, "stored_row", stored_row)


async def _audits(db) -> list[dict]:
    db.expire_all()
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "content_handling.changed")
                             .order_by(AuditLog.created_at))).scalars().all()
    return [row.details for row in rows]


@pytest.mark.committed_db  # one session per request, as in production
async def test_concurrent_creates_of_one_kind_give_one_change_and_a_typed_conflict(client, db, monkeypatch) -> None:
    workspace = await _workspace(db)
    owner = await _member(db, workspace, "owner")
    await _racing_reads(monkeypatch, 2)

    answers = await asyncio.gather(*(client.put(_url(workspace, "email"), headers=bearer(owner),
                                                json={"action": action}) for action in ("report", "refuse")))

    assert sorted(answer.status_code for answer in answers) == [200, 409], [answer.text for answer in answers]
    won = next(answer for answer in answers if answer.status_code == 200).json()["action"]
    lost = next(answer for answer in answers if answer.status_code == 409).json()["detail"]
    assert lost["code"] == "content_handling_conflict" and lost["message"]
    db.expire_all()
    stored = (await db.execute(select(WorkspaceContentHandling))).scalars().all()
    assert [(row.kind, row.action) for row in stored] == [("email", won)]
    assert [(item["old"], item["new"]) for item in await _audits(db)] == [("default(mask)", won)]


@pytest.mark.committed_db  # one session per request, as in production
async def test_concurrent_changes_of_one_kind_audit_only_real_transitions(client, db, monkeypatch) -> None:
    workspace = await _workspace(db)
    owner = await _member(db, workspace, "owner")
    assert (await client.put(_url(workspace, "email"), headers=bearer(owner), json={"action": "report"})).status_code == 200
    await _racing_reads(monkeypatch, 2)

    answers = await asyncio.gather(*(client.put(_url(workspace, "email"), headers=bearer(owner),
                                                json={"action": action}) for action in ("refuse", "default")))

    codes = sorted(answer.status_code for answer in answers)
    assert codes in ([200, 200], [200, 409]), [answer.text for answer in answers]
    transitions = [(item["old"], item["new"]) for item in await _audits(db)][1:]
    assert len(transitions) == codes.count(200)
    assert transitions[0][0] == "report"
    for (_old, new), (following_old, _new) in zip(transitions, transitions[1:]):
        assert following_old == new
    db.expire_all()
    stored = (await db.execute(select(WorkspaceContentHandling))).scalars().all()
    final = stored[0].action if stored else "default(mask)"
    assert transitions[-1][1] == final


@pytest.mark.committed_db  # real commits: the setting and its audit row are one transaction
async def test_a_failing_audit_write_commits_no_setting(client, db, monkeypatch) -> None:
    workspace = await _workspace(db)
    owner = await _member(db, workspace, "owner")

    def failing_audit(**values):  # the audit row cannot be written (NOT NULL action)
        return AuditLog(**{**values, "action": None})

    monkeypatch.setattr(handling_settings, "AuditLog", failing_audit)
    for body in ({"action": "report"}, {"action": "refuse"}):
        try:
            answer = await client.put(_url(workspace, "email"), headers=bearer(owner), json=body)
        except Exception:  # noqa: BLE001 - the in-process transport re-raises the app's error
            answer = None
        assert answer is None or answer.status_code >= 500
    db.expire_all()
    assert (await db.execute(select(WorkspaceContentHandling))).scalars().all() == []
    assert await _audits(db) == []
