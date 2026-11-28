"""Proposed checks (From Correction to Check)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog
from app.services.check_proposals import stub
from app.services.check_proposals.rules import approve_refusal, instead_refusal

BASE = "/api/v1/workspaces/{ws}/check-proposals"


@pytest.fixture(autouse=True)
def _stub_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "check_proposals_stub", True)
    stub.reset()
    yield
    stub.reset()


def test_who_changed_a_proposal_does_not_approve_it_and_proof_comes_first():
    proposal = {"state": "proposed", "author": {"kind": "platform"}, "edits": [{"by": "u-1"}],
                "proof": {"state": "proven"}}
    assert approve_refusal(proposal, user_id="u-1", may_approve=True, accept_unproven=False).code == "four_eyes_required"
    assert approve_refusal(proposal, user_id="u-2", may_approve=True, accept_unproven=False) is None
    assert approve_refusal(proposal, user_id="u-2", may_approve=False,
                           accept_unproven=False).code == "approver_permission_missing"
    unproven = {**proposal, "proof": {"state": "running"}}
    assert approve_refusal(unproven, user_id="u-2", may_approve=True, accept_unproven=False).code == "proof_missing"
    assert approve_refusal(unproven, user_id="u-2", may_approve=True, accept_unproven=True) is None
    assert instead_refusal({"what": "x", "instead": "  "}).code == "instead_required"


@pytest.mark.asyncio
async def test_an_owner_approves_a_proven_check_and_an_edited_one_needs_a_second_person(client, auth_headers):
    ws = (await client.post("/api/v1/projects", headers=auth_headers, json={"name": "Check proposals"})).json()["id"]
    listed = (await client.get(BASE.format(ws=ws), headers=auth_headers)).json()
    assert listed["stub"] is True and listed["may_approve"] is True
    assert listed["counts"] == {"proposed": 2, "approved": 1, "rejected": 1}
    assert all("occurrences" not in row["evidence"] for row in listed["items"]), "the list is the summary"
    detail = (await client.get(BASE.format(ws=ws) + "/chp_timeout", headers=auth_headers)).json()
    assert detail["message"]["instead"] and len(detail["evidence"]["occurrences"]) == 3

    approved = await client.post(BASE.format(ws=ws) + "/chp_timeout/approve", headers=auth_headers, json={})
    assert approved.status_code == 200 and approved.json()["state"] == "approved"

    no_instead = await client.post(BASE.format(ws=ws) + "/chp_money_eq/edit", headers=auth_headers,
                                   json={"message": {"instead": ""}})
    assert no_instead.status_code == 422 and no_instead.json()["detail"]["code"] == "instead_required"
    edited = await client.post(BASE.format(ws=ws) + "/chp_money_eq/edit", headers=auth_headers,
                               json={"message": {"instead": "Compare cents with round(a * 100)."}})
    assert edited.status_code == 200 and edited.json()["edits"][0]["fields"] == ["message.instead"]
    unexplained = await client.post(BASE.format(ws=ws) + "/chp_money_eq/approve", headers=auth_headers,
                                    json={"accept_unproven": True})
    assert unexplained.status_code == 422 and unexplained.json()["detail"]["code"] == "reason_required"
    own = await client.post(BASE.format(ws=ws) + "/chp_money_eq/approve", headers=auth_headers,
                            json={"accept_unproven": True, "note": "The pattern is obvious from the three reviews."})
    assert own.status_code == 403 and own.json()["detail"]["code"] == "four_eyes_required"
    rejected = await client.post(BASE.format(ws=ws) + "/chp_money_eq/reject", headers=auth_headers,
                                 json={"reason": ""})
    assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "reason_required"


@pytest.mark.asyncio
async def test_switching_an_approved_check_off_needs_a_reason_and_the_audit_keeps_it(client, auth_headers, db):
    ws = (await client.post("/api/v1/projects", headers=auth_headers, json={"name": "Check switches"})).json()["id"]
    off = await client.post(BASE.format(ws=ws) + "/chp_web_db/enabled", headers=auth_headers,
                            json={"enabled": False, "reason": "Too strict for the migration week."})
    assert off.status_code == 200 and off.json()["enabled"] is False
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "check_proposal.switched"))).scalar_one()
    assert audit.details["reason"] == "Too strict for the migration week." and audit.details["enabled"] is False
    not_approved = await client.post(BASE.format(ws=ws) + "/chp_money_eq/enabled", headers=auth_headers,
                                     json={"enabled": False, "reason": "x"})
    assert not_approved.status_code == 409 and not_approved.json()["detail"]["code"] == "not_approved"


@pytest.mark.asyncio
async def test_no_fixtures_on_a_production_like_stack(client, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "check_proposals_stub", None)
    monkeypatch.setattr(get_settings(), "runtime_profile", "production")
    ws = (await client.post("/api/v1/projects", headers=auth_headers, json={"name": "Prod-like"})).json()["id"]
    answer = await client.get(BASE.format(ws=ws), headers=auth_headers)
    # The store: a production-like stack never shows fixtures; it shows its own (here: no) proposals.
    assert answer.status_code == 200 and answer.json()["items"] == [] and "stub" not in answer.json()
