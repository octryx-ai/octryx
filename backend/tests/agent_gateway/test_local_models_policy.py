"""Local model licences: permissive only by default, a platform admin's switch,
read by the launchers in /client-policy; a local upstream gets an 8k answer floor on the Codex route."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.model_gateway.inbound.openai_service import LOCAL_MIN_OUTPUT_TOKENS, local_upstream
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/local-models"


@pytest.mark.asyncio
async def test_permissive_only_is_on_by_default_and_only_a_platform_admin_switches_it(client, db):
    admin = await make_user(db, admin=True)
    member = await make_user(db, admin=False)
    await db.commit()

    default = (await client.get(ROUTE, headers=bearer(member))).json()
    refused = await client.put(ROUTE, json={"permissive_only": False}, headers=bearer(member))
    invalid = await client.put(ROUTE, json={"permissive_only": "no"}, headers=bearer(admin))
    unknown = await client.put(ROUTE, json={"permissive_only": False, "x": 1}, headers=bearer(admin))
    off = await client.put(ROUTE, json={"permissive_only": False}, headers=bearer(admin))

    assert default == {"permissive_only": True, "can_edit": False}
    assert refused.status_code == 403 and invalid.status_code == 422 and unknown.status_code == 422
    assert off.json() == {"permissive_only": False, "can_edit": True}
    assert (await client.get(ROUTE, headers=bearer(member))).json()["permissive_only"] is False
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.local_models.permissive_only_updated"))
             ).scalars().all()
    assert [row.details for row in audit] == [{"before": True, "after": False}]


@pytest.mark.parametrize(("url", "local"), [
    ("http://127.0.0.1:8795/v1", True), ("http://localhost:11434", True), ("http://host.docker.internal:8797", True),
    ("http://[::1]:8080/v1", True), ("http://mac-mini.local:8080", True),
    ("https://litellm.example.com/v1", False), ("http://10.0.0.5:4000", False), ("", False),
])
def test_a_local_upstream_is_recognised(url, local):
    assert local_upstream(url) is local
    assert LOCAL_MIN_OUTPUT_TOKENS == 8192
