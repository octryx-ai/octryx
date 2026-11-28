"""Model Policy registry: create, save draft, admission, submit / publish / retire."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider, ModelPolicy, ModelPolicyRevision, User
from ...models.runtime.governed_revision import (
    REGISTRY_STATUS_ACTIVE,
    REVISION_STATE_DRAFT,
)
from ...time_utils import utc_now
from ..model_gateway.litellm.runtime_admission import LITELLM_GATEWAY_DRIVER
from . import lifecycle
from .entries import ModelPolicyAdmission, entries_digest, evaluate_admission, normalize_entries
from .entry_lifecycle import require_entry_active, retire_entry
from .errors import (
    MODEL_POLICY_NEEDS_CONFIGURATION,
    MODEL_POLICY_NOT_FOUND,
    NAME_TAKEN,
    REVISION_NOT_FOUND,
    RegistryRefusalError,
)
from .governance import KIND_MODEL_POLICY, record_audit
from .naming import next_revision_number, normalize_name


async def gateway_catalog_configs(db: AsyncSession, workspace_id: str) -> list[Any]:
    rows = (
        await db.execute(
            select(LLMProvider.config_json)
            .where(
                LLMProvider.driver == LITELLM_GATEWAY_DRIVER,
                LLMProvider.is_active.is_(True),
                or_(LLMProvider.is_global.is_(True), LLMProvider.project_id == workspace_id),
            )
            .order_by(LLMProvider.name.asc())
        )
    ).scalars()
    return list(rows)


async def policy_admission(db: AsyncSession, workspace_id: str, revision: ModelPolicyRevision) -> ModelPolicyAdmission:
    return evaluate_admission(revision.entries_json, await gateway_catalog_configs(db, workspace_id))


def _new_revision(policy_id: str, number: int, entries: list[dict[str, Any]], user: User) -> ModelPolicyRevision:
    now = utc_now()
    return ModelPolicyRevision(
        policy_id=policy_id,
        revision=number,
        state=REVISION_STATE_DRAFT,
        entries_json=entries,
        digest=entries_digest(entries),
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )


async def create_policy(
    db: AsyncSession, *, workspace_id: str, name: object, entries: Any, user: User
) -> tuple[ModelPolicy, ModelPolicyRevision]:
    normalized = normalize_name(name)
    checked = normalize_entries(entries)
    existing = (
        await db.execute(
            select(ModelPolicy.id).where(ModelPolicy.workspace_id == workspace_id, ModelPolicy.name == normalized)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise RegistryRefusalError(NAME_TAKEN, name=normalized)
    now = utc_now()
    policy = ModelPolicy(
        workspace_id=workspace_id,
        name=normalized,
        status=REGISTRY_STATUS_ACTIVE,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    try:
        await db.flush()
    except IntegrityError:
        raise RegistryRefusalError(NAME_TAKEN, name=normalized) from None
    revision = _new_revision(policy.id, 1, checked, user)
    db.add(revision)
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action="model_policy.create",
        resource_type=KIND_MODEL_POLICY,
        resource_id=policy.id,
        project_id=workspace_id,
        details={"workspace_id": workspace_id, "revision": 1, "digest": revision.digest},
    )
    return policy, revision


async def save_policy_draft(db: AsyncSession, *, policy: ModelPolicy, entries: Any, user: User) -> ModelPolicyRevision:
    require_entry_active(policy, policy_id=policy.id)
    checked = normalize_entries(entries)
    revision = (
        (
            await db.execute(
                select(ModelPolicyRevision)
                .where(ModelPolicyRevision.policy_id == policy.id, ModelPolicyRevision.state == REVISION_STATE_DRAFT)
                .order_by(ModelPolicyRevision.revision.desc())
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        number = await next_revision_number(db, ModelPolicyRevision.revision, ModelPolicyRevision.policy_id, policy.id)
        revision = _new_revision(policy.id, number, checked, user)
        db.add(revision)
    else:
        revision.entries_json = checked
        revision.digest = entries_digest(checked)
        revision.updated_at = utc_now()
    policy.updated_at = utc_now()
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action="model_policy.save_draft",
        resource_type=KIND_MODEL_POLICY,
        resource_id=policy.id,
        project_id=policy.workspace_id,
        details={"revision": revision.revision, "digest": revision.digest},
    )
    return revision


def _bindings(db: AsyncSession, policy: ModelPolicy, revision: ModelPolicyRevision) -> dict[str, Any]:
    async def precheck() -> None:
        normalize_entries(revision.entries_json)
        admission = await policy_admission(db, policy.workspace_id, revision)
        if admission.status != "admitted":
            raise RegistryRefusalError(MODEL_POLICY_NEEDS_CONFIGURATION, admission=admission.as_dict())

    return {
        "kind": KIND_MODEL_POLICY,
        "parent_id": policy.id,
        "revision": revision,
        "recompute_digest": lambda: entries_digest(revision.entries_json),
        "precheck": precheck,
    }


async def submit_policy_revision(
    db: AsyncSession, *, policy: ModelPolicy, revision: ModelPolicyRevision, user: User
) -> ModelPolicyRevision:
    require_entry_active(policy, policy_id=policy.id)
    return await lifecycle.submit_revision(
        db, workspace_id=policy.workspace_id, label=policy.name, user=user, **_bindings(db, policy, revision)
    )


async def publish_policy_revision(
    db: AsyncSession,
    *,
    policy: ModelPolicy,
    revision: ModelPolicyRevision,
    approval_id: str | None,
    user: User,
    self_approve: bool = False,
) -> dict[str, Any]:
    require_entry_active(policy, policy_id=policy.id)
    return await lifecycle.publish_revision(
        db, workspace_id=policy.workspace_id, approval_id=approval_id, user=user, self_approve=self_approve,
        **_bindings(db, policy, revision),
    )


async def retire_policy_revision(
    db: AsyncSession, *, policy: ModelPolicy, revision: ModelPolicyRevision, user: User
) -> ModelPolicyRevision:
    return await lifecycle.retire_revision(
        db, kind=KIND_MODEL_POLICY, parent_id=policy.id, workspace_id=policy.workspace_id, revision=revision, user=user
    )


async def retire_policy(db: AsyncSession, *, policy: ModelPolicy, user: User) -> ModelPolicy:
    return await retire_entry(db, kind=KIND_MODEL_POLICY, entry=policy, user=user)


async def list_policies(db: AsyncSession, workspace_id: str) -> list[ModelPolicy]:
    stmt = select(ModelPolicy).where(ModelPolicy.workspace_id == workspace_id).order_by(ModelPolicy.name.asc())
    return list((await db.execute(stmt)).scalars())


async def get_policy(db: AsyncSession, policy_id: str) -> ModelPolicy:
    policy = await db.get(ModelPolicy, str(policy_id or "").strip()) if policy_id else None
    if policy is None:
        raise RegistryRefusalError(MODEL_POLICY_NOT_FOUND)
    return policy


async def list_policy_revisions(db: AsyncSession, policy: ModelPolicy) -> list[ModelPolicyRevision]:
    stmt = (
        select(ModelPolicyRevision)
        .where(ModelPolicyRevision.policy_id == policy.id)
        .order_by(ModelPolicyRevision.revision.asc())
    )
    return list((await db.execute(stmt)).scalars())


async def get_policy_revision(db: AsyncSession, policy: ModelPolicy, number: int) -> ModelPolicyRevision:
    revision = (
        await db.execute(
            select(ModelPolicyRevision).where(
                ModelPolicyRevision.policy_id == policy.id, ModelPolicyRevision.revision == int(number)
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise RegistryRefusalError(REVISION_NOT_FOUND, revision=int(number))
    return revision


__all__ = [
    "create_policy",
    "gateway_catalog_configs",
    "get_policy",
    "get_policy_revision",
    "list_policies",
    "list_policy_revisions",
    "policy_admission",
    "publish_policy_revision",
    "retire_policy",
    "retire_policy_revision",
    "save_policy_draft",
    "submit_policy_revision",
]
