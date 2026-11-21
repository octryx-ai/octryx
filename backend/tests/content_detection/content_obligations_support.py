"""Shared helpers for the test_content_obligations_* modules."""

from __future__ import annotations

import uuid

from app.models import Project
from app.services.secret import set_secret_value
from tests.model_gateway.conftest import ALIAS, GATEWAY_HOST, VIRTUAL_KEY, gateway_config, gateway_provider

EMAIL = "jane.doe@example.org"


PHONE = "+49 30 1234567"


DATA_TEXT = f"mail {EMAIL} tel {PHONE} declined"


ROUTED_ID = "pii-approved-model"


ROUTED = ('@id("' + ROUTED_ID + '")\n@obligation("mask_reroute")\n@reroute_to("' + ALIAS + '")\n'
          '@mask("email,phone")\n@mask_style("last4")\n'
          'forbid (principal, action == Action::"call_model", resource)\n'
          'when { context.content.detected.containsAny(["email", "phone"]) || '
          '(context.content.scanned && !context.content.complete) || '
          '(principal is AgentSession && principal.sensitive.containsAny(["pii"])) }\n'
          'unless { context.route == "governed" && resource.approved_for.containsAll(["pii"]) && '
          '!context.content.detected.containsAny(["email", "phone"]) };')


async def _governed_alias(db, workspace_id: str, *, approved: list[str], grant: bool = True) -> None:
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "model_policy": {"allowed_aliases": [ALIAS] if grant else []}}
    secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key", project_id=None,
                                    value=VIRTUAL_KEY)
    config = gateway_config()
    config["litellm_gateway"]["aliases"][ALIAS]["approved_data_categories"] = approved
    db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", api_key_secret_ref=secret.id,
                            endpoint_url=f"https://{GATEWAY_HOST}", config_json=config))
    await db.commit()


ROUTE_GOVERNED = "/api/v1/model-gateway/anthropic/v1/messages"
