"""Simple usage counts per skill, surface and invocation; refusals never name a skill."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import SkillUsageEvent, User
from app.time_utils import utc_now
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.support import BASE, category, published_skill


def _event(event_type: str, *, skill=None, name=None, surface="platform_chat", invocation="get", age_days=0,
           status="success") -> SkillUsageEvent:
    return SkillUsageEvent(id=str(uuid.uuid4()), event_type=event_type, skill_id=skill, skill_name=name,
                           surface=surface, invocation=invocation, policy_status=status,
                           created_at=utc_now() - timedelta(days=age_days))


@pytest.mark.asyncio
async def test_counts_by_surface_with_unmanaged_names_and_anonymous_refusals(client, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    terraform = (await category(db, "iac.terraform")).id
    skill, _ = await published_skill(db, terraform, "style-guide", approver_id=admin.id)
    skill_id = skill.id
    db.add_all([
        _event("get", skill=skill_id, name="style-guide"),
        _event("get", skill=skill_id, name="style-guide"),
        _event("use", skill=skill_id, name="style-guide", surface="octryx_claude", invocation="model"),
        _event("use", skill=skill_id, name="style-guide", surface="octryx_claude", invocation="slash"),
        _event("use", name="my-local-skill", surface="octryx_claude", invocation="model"),
        _event("policy_denied", status="denied"),  # a refused chat skill_get names no skill
        _event("search", invocation="search"),  # a search is not a use
        _event("get", skill=skill_id, name="style-guide", age_days=40),  # outside the window
    ])
    await db.commit()

    usage = (await client.get(f"{BASE}/usage", headers=bearer(admin.id))).json()
    entry = next(item for item in usage["skills"] if item["skill_id"] == skill_id)
    assert entry["uses"] == 4 and entry["by_surface"] == {
        "platform_chat:get": 2, "octryx_claude:model": 1, "octryx_claude:slash": 1}
    assert {"name": "my-local-skill", "uses": 1} in usage["unmanaged"]
    assert usage["totals"]["refusals"] >= 1 and all(item["skill_id"] for item in usage["skills"])
    one = (await client.get(f"{BASE}/skills/{skill_id}/usage?days=90", headers=bearer(admin.id))).json()
    assert one["uses"] == 5
    rows = (await client.get(f"{BASE}/skills", headers=bearer(admin.id))).json()["items"]
    assert next(row for row in rows if row["id"] == skill_id)["uses"] == 5

    member = await make_user(db, admin=False)
    for path in ("/usage", f"/skills/{skill_id}/usage"):
        assert (await client.get(f"{BASE}{path}", headers=bearer(member))).status_code == 403
    assert (await client.get(f"{BASE}/usage?days=0", headers=bearer(admin.id))).status_code == 422
