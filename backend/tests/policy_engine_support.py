"""Helpers for the Cedar policy engine tests: users, bearer headers, a published custom set."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Approval, Role, User, UserRole
from app.services.auth import create_access_token
from app.services.policy_engine.custom_policies import check_custom_policies
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime

BASE = "/api/v1/admin/policy-engine"


async def make_user(db, *, admin: bool) -> str:
    user_id = str(uuid.uuid4())
    handle = f"pe{user_id[:8]}"
    db.add(User(id=user_id, username=handle, email=f"{handle}@example.com", password_hash="x", is_active=True))
    await db.flush()
    if admin:
        role_id = (await db.execute(select(Role.id).where(Role.name == "admin"))).scalar_one()
        db.add(UserRole(user_id=user_id, role_id=role_id))
        await db.flush()
    await db.commit()
    return user_id


def bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def approve(db, approval_id: str, approver_id: str) -> None:
    approval = await db.get(Approval, approval_id)
    approval.status = "approved"
    approval.approved_by = approver_id
    await db.commit()


def use_custom_policies(text: str, *, mode: str = "shadow", version: int = 1) -> PolicyRuntime:
    checked = check_custom_policies(text)
    runtime = PolicyRuntime(mode=mode, custom_text=checked.text, custom_ids=frozenset(checked.ids),
                            custom_version=version, custom_digest=checked.digest, loaded_at=1e18)
    set_policy_runtime(runtime)
    return runtime


ROLLOUT_POLICY = (
    '@id("rollout-restart-non-prod-only")\n'
    'forbid (principal in Role::"sre", action == Action::"run_command", resource)\n'
    'when { resource.program == "kubectl" && resource.arguments.containsAll(["rollout", "restart"]) && '
    '!resource.argument_values.contains("--context=nonprod") };\n'
)


async def grant_role(db, user_id: str, role_name: str) -> None:
    role_id = (await db.execute(select(Role.id).where(Role.name == role_name))).scalar_one_or_none()
    if role_id is None:
        role = Role(name=role_name, description="test role")
        db.add(role)
        await db.flush()
        role_id = role.id
    db.add(UserRole(user_id=user_id, role_id=role_id))
    await db.commit()


async def publish(client, db, policies: str) -> int:
    author, reviewer = await make_user(db, admin=True), await make_user(db, admin=True)
    created = await client.post(f"{BASE}/policy-sets", json={"policies": policies}, headers=bearer(author))
    assert created.status_code == 201, created.text
    version = created.json()["version"]
    approval_id = (await client.post(f"{BASE}/policy-sets/{version}/submit", headers=bearer(author))).json()[
        "governance_approval_id"]
    await approve(db, approval_id, reviewer)
    published = await client.post(f"{BASE}/policy-sets/{version}/publish",
                                  json={"governance_approval_id": approval_id}, headers=bearer(author))
    assert published.status_code == 200, published.text
    return version


__all__ = ["BASE", "ROLLOUT_POLICY", "approve", "bearer", "grant_role", "make_user", "publish", "use_custom_policies"]
