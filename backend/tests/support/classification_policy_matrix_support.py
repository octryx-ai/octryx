"""Shared helpers for the test_classification_policy_matrix_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import LLMModel, LLMProvider, Project, User
from app.services.auth import create_access_token
from app.services.data_classification.policy_matrix_admin import set_classification_policy
from app.services.secret import set_secret_value
from tests.model_gateway.conftest import ALIAS, GATEWAY_HOST, VIRTUAL_KEY, gateway_provider

ROUTE = "/api/v1/admin/data-classification/policy"


RERANKER = "bedrock_cohere_rerank35_v1"


REMOTE_SPACE = "bedrock_titan2_1024_v1"


def _summary(project_id: str) -> str:
    return f"/api/v1/workspaces/{project_id}/policy-summary"


async def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def _workspace(db, level: str | None = "internal", **config) -> str:
    project = Project(
        id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
        config={"model_policy": {"allowed_aliases": [ALIAS]},
                **({"data_policy": {"classification": level}} if level else {}), **config},
    )
    db.add(project)
    await db.commit()
    return project.id


async def _matrix(db, level: str = "internal", **rules) -> None:
    await set_classification_policy(db, levels=[{"level": level, "rules": rules}], actor_id=await _admin_id(db))
    await db.commit()


async def _gateway(db) -> None:
    secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key", project_id=None,
                                    value=VIRTUAL_KEY)
    db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", api_key_secret_ref=secret.id,
                            endpoint_url=f"https://{GATEWAY_HOST}"))
    await db.commit()


async def _catalog_clearance(db, cleared_up_to: str | None, *, enabled: bool = True) -> None:
    for provider in (await db.execute(select(LLMProvider).where(LLMProvider.driver == "litellm_gateway"))).scalars():
        row = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id,
                                                       LLMModel.model_id == ALIAS))).scalar_one_or_none()
        if row is None:
            row = LLMModel(provider_id=provider.id, model_id=ALIAS)
            db.add(row)
        row.cleared_up_to, row.is_active = cleared_up_to, enabled
    await db.commit()
