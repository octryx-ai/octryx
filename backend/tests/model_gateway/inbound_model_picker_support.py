"""Shared helpers for the test_inbound_model_picker_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from app.models import OAuthGrant, Project
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.oauth_provider import mint_access_token
from app.services.secret import set_secret_value
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

from .conftest import ALIAS, GATEWAY_HOST, MODEL_GROUP, VIRTUAL_KEY, gateway_config, gateway_provider

MODELS = "/api/v1/model-gateway/anthropic/v1/models"


SECOND = "octryx-second"


NO_TOOLS = "octryx-no-tools"


UNGRANTED = "octryx-ungranted"


OPT_IN = {"seat_mode": "allowed", "seat_allows_governed_models": True}


def _alias(group: str, **extra: Any) -> dict[str, Any]:
    return {"model_group": group, "context_limit": 128000, "data_policy_class": "internal",
            "capabilities": {"tools": True},
            "cost": {"source": "catalog_pricing", "input_per_million_usd": 1.0, "output_per_million_usd": 2.0},
            **extra}


CATALOG = {
    ALIAS: _alias(MODEL_GROUP, display_name="General model"),
    SECOND: _alias("second-group"),
    NO_TOOLS: {**_alias("plain-group"), "capabilities": {"tools": False}},
    UNGRANTED: _alias("other-group"),
}


async def _workspace(db, *, policy: dict | None, grant: tuple[str, ...] = (ALIAS, SECOND, NO_TOOLS),
                     catalog: dict | None = None, second_provider: dict | None = None) -> tuple[str, dict]:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    config: dict[str, Any] = {"data_policy": {"classification": "internal"},
                              "model_policy": {"allowed_aliases": list(grant)}}
    if policy is not None:
        config["agent_gateway_policy"] = policy
    project.config = config
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key", project_id=None,
                                    value=VIRTUAL_KEY)
    db.add(gateway_provider(name="litellm-a", api_key_secret_ref=secret.id, endpoint_url=f"https://{GATEWAY_HOST}",
                            config_json=gateway_config(aliases=dict(catalog or CATALOG))))
    if second_provider is not None:
        db.add(gateway_provider(name="litellm-b", api_key_secret_ref=secret.id,
                                endpoint_url=f"https://{GATEWAY_HOST}", config_json=gateway_config(aliases=second_provider)))
    grant_row = OAuthGrant(id=str(uuid.uuid4()), user_id=user_id, client_id="octryx-claude-test",
                           scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant_row)
    await db.commit()
    token, _ = mint_access_token(user_id=user_id, client_id=grant_row.client_id, grant_id=grant_row.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    return workspace_id, {"authorization": f"Bearer {token}", "x-api-key": token,
                          "x-octryx-workspace": workspace_id, "x-octryx-session": str(uuid.uuid4())}


def _ids(payload: dict[str, Any]) -> list[str]:
    return [row["id"] for row in payload["data"]]
