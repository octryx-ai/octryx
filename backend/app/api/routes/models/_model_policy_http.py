"""HTTP plumbing of the Model Policy routes: refusal-to-HTTP mapping and loading an authorized policy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ModelPolicy, User
from ....models.runtime.governed_revision import ImmutableRevisionError
from ....services.model_policy.errors import MODEL_POLICY_NOT_FOUND, RegistryRefusalError
from ....services.model_policy.policies import get_policy
from ....services.workspace_authorization import authorize_workspace


@contextmanager
def refusals_as_http() -> Iterator[None]:
    try:
        yield
    except RegistryRefusalError as refusal:
        raise HTTPException(status_code=refusal.http_status, detail=refusal.as_dict()) from None
    except ImmutableRevisionError as refusal:
        raise HTTPException(status_code=409, detail={"code": refusal.code}) from None


async def authorized_policy(db: AsyncSession, user: User, policy_id: str, *, author: bool) -> ModelPolicy:
    with refusals_as_http():
        policy = await get_policy(db, policy_id)
    await authorize_workspace(
        db,
        current_user=user,
        workspace_id=policy.workspace_id,
        require_author=author,
        not_found_detail={"code": MODEL_POLICY_NOT_FOUND},
    )
    return policy


__all__ = ["authorized_policy", "refusals_as_http"]
