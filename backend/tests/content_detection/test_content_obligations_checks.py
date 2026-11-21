"""Save-time obligation checks: annotations, stored policies with removed detectors, and route targets that must exist and be approved for the categories."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models import Project
from tests.content_detection.content_obligations_support import ROUTED, ROUTED_ID, _governed_alias


def _mask_body(mask: str, style: str | None = None) -> dict[str, Any]:
    annotations = {"obligation": "mask", "mask": mask, **({"mask_style": style} if style else {})}
    return {"annotations": annotations, "action": {"op": "==", "entity": {"type": "Action", "id": "call_model"}}}


# --- save-time checks -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "code"), [
    ('@id("a")\n@obligation("route")\nforbid (principal, action == Action::"call_model", resource);',
     "obligation_invalid"),
    ('@id("a")\n@obligation("mask")\nforbid (principal, action, resource);', "obligation_invalid"),
    ('@id("a")\n@obligation("reroute")\n@reroute_to("x")\n'
     'forbid (principal, action == Action::"receive_tool_result", resource);', "obligation_invalid"),
    ('@id("a")\n@obligation("mask")\nforbid (principal, action == Action::"call_model", resource);',
     "obligation_mask_invalid"),
    ('@id("a")\n@obligation("mask")\n@mask("email")\n@mask_style("stars")\n'
     'forbid (principal, action == Action::"call_model", resource);', "obligation_mask_invalid"),
    ('@id("a")\n@obligation("reroute")\nforbid (principal, action == Action::"call_model", resource);',
     "obligation_reroute_invalid"),
    ('@id("a")\n@mask("email")\nforbid (principal, action == Action::"call_model", resource);', "obligation_invalid"),
])
def test_obligation_annotations_are_checked_on_save(text, code):
    from app.services.policy_engine.custom_policies import CustomPolicyError, check_custom_policies

    with pytest.raises(CustomPolicyError) as raised:
        check_custom_policies(text)
    assert code in {item["code"] for item in raised.value.issues}


def test_a_removed_detector_in_a_stored_policy_is_not_an_issue_while_a_known_detector_remains():
    from app.services.policy_engine.obligation_checks import obligation_issues

    assert obligation_issues("a", _mask_body("track_data,email", "last4")) == []
    [issue] = obligation_issues("a", _mask_body("track_data"))
    assert issue["code"] == "obligation_mask_invalid"


@pytest.mark.asyncio
async def test_route_target_must_exist_and_be_approved_for_the_categories(client, db):
    from app.services.policy_engine.custom_policies import custom_digest
    from tests.policy_engine_support import BASE, bearer, make_user

    admin = await make_user(db, admin=True)
    workspace = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(workspace)
    await db.commit()

    async def save(text):
        return await client.put(f"{BASE}/policy-sets/0/policies/{ROUTED_ID}", json={"cedar": text},
                                headers={**bearer(admin), "If-Match": custom_digest("")})

    unknown = await save(ROUTED)
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["issues"][0]["code"] == "reroute_target_unknown"
    await _governed_alias(db, workspace.id, approved=["secrets"])
    not_approved = await save(ROUTED)
    assert not_approved.json()["detail"]["issues"][0]["code"] == "reroute_target_not_approved"
    assert "pii" in not_approved.json()["detail"]["issues"][0]["message"]
