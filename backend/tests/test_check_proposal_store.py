"""From Correction to Check, the proposal store: a signature that reaches
the Workspace's threshold becomes one proposal in the store; the routes serve it (no fixtures); edits make
co-authors; approving needs the permission, another person than the authors, a proof or accept_unproven, and a
drafted check; a rejection names its reason; an approved check is switched on and off with a reason."""

from __future__ import annotations

import pytest

from app.services.check_proposals import signature_updated
from app.services.check_proposals.settings import settings
from app.services.observability import check_proposal_metrics

RULE = {"rule": {"tool": "ruff", "rule_id": "B006"}, "summary": "a mutable default argument"}
MESSAGE = {"what": "a list as a default argument", "why": "it is shared between calls",
           "instead": "default to None and create the list in the function"}
BASE = "/api/v1/workspaces/{ws}/check-proposals"


@pytest.fixture(autouse=True)
def _real_store(monkeypatch):
    """The store, not the fixtures (a development profile turns the fixtures on by default)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "check_proposals_stub", False)


def _signature(workspace_id: str, repeats: int) -> dict:
    return {"id": "sig_mutable_default", "workspace_id": workspace_id, "check_kind": "lint_rule",
            "occurrences": [{"source": "review_fixed", "run_id": f"run-{index}", "at": f"2026-11-1{index}T10:00:00",
                             "excerpt": "def total(items=[]):"} for index in range(repeats)]
            + [{"source": "not_a_source", "run_id": "x", "at": "2026-11-19T10:00:00"}]}


def test_the_settings_say_where_each_value_comes_from():
    found = settings({"check_proposals": {"threshold": 3, "approver_permission": "nobody"}})
    assert found["threshold"] == {"value": 3, "source": "workspace"}
    assert found["approver_permission"] == {"value": "workspace_owner", "source": "default"}  # invalid: default
    assert settings(None)["threshold"] == {"value": 2, "source": "default"}


@pytest.mark.asyncio
async def test_a_repeated_correction_becomes_one_stored_proposal_that_two_people_decide(client, db):
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.policy_engine_support import bearer

    check_proposal_metrics.reset()
    workspace_id = await seed_workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    second = await seed_member(db, workspace_id=workspace_id, role="owner")
    member = await seed_member(db, workspace_id=workspace_id, role="member")

    assert await signature_updated(db, _signature(workspace_id, 1)) is None  # below the threshold of 2
    proposal_id = (await signature_updated(db, _signature(workspace_id, 2))).id
    again = await signature_updated(db, _signature(workspace_id, 3))
    await db.commit()
    await db.refresh(again)
    assert again.id == proposal_id and again.evidence["repeats"] == 3  # one proposal, its evidence refreshed
    assert again.evidence["sources"] == {"review_fixed": 3} and again.proof == {"state": "not_run"}

    base = BASE.format(ws=workspace_id)
    listed = (await client.get(base, params={"state": "proposed"}, headers=bearer(member))).json()
    assert [item["id"] for item in listed["items"]] == [proposal_id] and "stub" not in listed
    assert listed["may_approve"] is False and "occurrences" not in listed["items"][0]["evidence"]

    async def post(path: str, body: dict, who: str):
        return await client.post(f"{base}/{proposal_id}/{path}", json=body, headers=bearer(who))

    no_instead = await post("edit", {"message": {"what": "x", "why": "y"}}, owner)
    assert no_instead.json()["detail"]["code"] == "instead_required"
    assert (await post("approve", {"accept_unproven": True, "note": "no proof yet, team agreed"}, owner)).json()[
        "detail"]["code"] == "draft_incomplete"
    assert (await post("edit", {"draft": RULE, "message": MESSAGE}, owner)).status_code == 200  # owner co-authors
    assert (await post("approve", {}, member)).json()["detail"]["code"] == "approver_permission_missing"
    assert (await post("approve", {}, owner)).json()["detail"]["code"] == "four_eyes_required"
    assert (await post("approve", {}, second)).json()["detail"]["code"] == "proof_missing"
    approved = await post("approve", {"accept_unproven": True, "note": "proof follows"}, second)
    assert approved.json()["state"] == "approved" and approved.json()["decision"]["accept_unproven"] is True
    assert (await post("enabled", {"enabled": False, "reason": ""}, second)).json()["detail"]["code"] == \
        "reason_required"
    off = await post("enabled", {"enabled": False, "reason": "too noisy for now"}, owner)
    assert off.json()["enabled"] is False and off.json()["edits"][-1]["fields"] == ["enabled"]
    assert check_proposal_metrics.PROPOSALS.series  # counted at the event


@pytest.mark.asyncio
async def test_a_rejection_names_its_reason_and_a_stranger_sees_nothing(client, db):
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.policy_engine_support import bearer

    workspace_id = await seed_workspace(db)
    other_workspace = await seed_workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    stranger = await seed_member(db, workspace_id=other_workspace, role="owner")
    proposal_id = (await signature_updated(db, _signature(workspace_id, 2))).id
    await db.commit()
    base = BASE.format(ws=workspace_id)
    assert (await client.get(base, headers=bearer(stranger))).status_code in (403, 404)
    empty = await client.post(f"{base}/{proposal_id}/reject", json={"reason": " "}, headers=bearer(owner))
    assert empty.json()["detail"]["code"] == "reason_required"
    rejected = await client.post(f"{base}/{proposal_id}/reject", json={"reason": "we allow it in scripts"},
                                 headers=bearer(owner))
    assert rejected.json()["state"] == "rejected" and rejected.json()["decision"]["reason"] == "we allow it in scripts"
    assert (await client.get(f"{base}/settings", headers=bearer(owner))).json()["threshold"]["value"] == 2
