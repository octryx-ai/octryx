"""Copilot device login of a control-plane provider: start the GitHub device flow and store its tokens."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from ...copilot_oauth import persist_copilot_oauth_tokens
from ...error_facts import error_code


async def start_control_plane_copilot_device(
    db: AsyncSession,
    *,
    provider_id: str,
    begin_flow_func: Callable[[], Any],
    flow_state: dict[str, dict[str, Any]],
) -> str:
    provider = await db.get(LLMProvider, provider_id)
    if not provider or provider.driver != "copilot_api":
        raise HTTPException(status_code=404, detail="Copilot provider not found")
    device_data = await begin_flow_func()
    flow_id = str(uuid.uuid4())
    flow_state[flow_id] = {
        "provider_id": provider.id,
        "device_code": device_data.get("device_code", ""),
        "user_code": device_data.get("user_code", ""),
        "verification_uri": device_data.get("verification_uri", "https://github.com/login/device"),
        "interval": int(device_data.get("interval", 5) or 5),
        "status": "pending",
        "error": "",
    }
    return flow_id


async def complete_control_plane_copilot_device(
    db: AsyncSession,
    *,
    provider_id: str,
    flow_id: str,
    flow_state: dict[str, dict[str, Any]],
    poll_flow_func: Callable[[str], Any],
    provider_secret_scope_func: Callable[[LLMProvider], tuple[str, str]],
    set_secret_value_func: Callable[..., Any],
    fetch_profile_func: Callable[[str], Any],
) -> dict[str, Any]:
    provider = await db.get(LLMProvider, provider_id)
    flow = flow_state.get(flow_id)
    if not provider or provider.driver != "copilot_api" or not flow or flow.get("provider_id") != provider.id:
        raise HTTPException(status_code=404, detail="Copilot login flow not found")
    token_data = await poll_flow_func(flow["device_code"])
    if token_data.get("access_token"):
        await persist_copilot_oauth_tokens(
            db,
            provider=provider,
            token_data=token_data,
            set_secret_value_func=set_secret_value_func,
            fetch_profile_func=fetch_profile_func,
        )
        flow_state.pop(flow_id, None)
        return {"status": "connected", "provider_id": provider.id}

    # GitHub's closed snake_case device-flow code only; free text never reaches the redirect.
    flow_error_code = error_code(str(token_data.get("error") or "authorization_pending"))
    if flow_error_code == "slow_down":
        flow["status"] = "waiting"
        flow["error"] = "GitHub requested a slower polling interval. Wait a few seconds and try again."
    elif flow_error_code == "authorization_pending":
        flow["status"] = "pending"
        flow["error"] = ""
    else:
        flow["status"] = "failed"
        flow["error"] = flow_error_code
    await db.commit()
    return {"status": flow["status"], "error": flow["error"], "provider_id": provider.id}
