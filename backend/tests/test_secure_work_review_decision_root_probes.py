"""Independent acceptance counterexamples for explicit reviewer evidence."""

from datetime import timedelta

from app.time_utils import utc_now
from tests.secure_work_coding_review_evidence_support import _auth, _decision, _gate, _post, _user, _world


async def test_repository_requirement_applies_to_each_matching_change_unit(client, auth_headers, db):
    reviewer = await _user(db, "required")
    item, plan, units = await _world(db, units=2, members=[reviewer])
    for unit in units:
        unit.repository_name = "shared-repository"
    plan.required_approvals_json = [{"type": "code_review", "repository_name": "shared-repository",
                                     "reviewers": [reviewer.username], "required": True}]
    await db.commit()
    # A generic operator approves both units, but the required reviewer covers only one.
    for unit in units:
        assert (await _post(client, auth_headers, item, _decision(plan, unit))).status_code == 200
    assert (await _post(client, _auth(reviewer), item, _decision(plan, units[-1]))).status_code == 200
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] != "pass", "A repository's named reviewer must cover every matching unit"


async def test_malformed_plan_requirement_container_does_not_become_no_requirements(client, auth_headers, db):
    item, plan, units = await _world(db)
    plan.required_approvals_json = {"type": "code_review", "reviewers": ["not-yet-reviewed"]}
    await db.commit()
    assert (await _post(client, auth_headers, item, _decision(plan, units[0]))).status_code == 200
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] != "pass", "Unreadable persisted requirements must keep the review gate open"


async def test_stale_displayed_unit_cannot_be_approved_as_current(client, auth_headers, db):
    item, plan, units = await _world(db)
    unit = units[0]
    displayed_marker = unit.updated_at.isoformat()
    unit.scope = "Different scope added after the reviewer opened the page"
    unit.updated_at = utc_now() + timedelta(seconds=5)
    await db.commit()
    response = await _post(client, auth_headers, item, _decision(
        plan, unit, expected_change_unit_marker=displayed_marker,
    ))
    assert response.status_code == 409, "Never stamp unseen current scope onto an old displayed review"


async def test_review_subject_units_cannot_be_read_or_replanned_outside_workspace(client, auth_headers, db):
    outsider = await _user(db, "outside-unit-scope")
    item, _, _ = await _world(db)
    path = f"/api/v1/secure-work/work-items/{item.id}/change-units"
    assert (await client.get(path, headers=_auth(outsider))).status_code == 404
    assert (await client.post(path + "/plan", headers=_auth(outsider), json={})).status_code == 404
    allowed = await client.get(path, headers=auth_headers)
    assert allowed.status_code == 200
    assert len(allowed.json()["items"]) == 1
