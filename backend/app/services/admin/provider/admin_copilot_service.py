"""Admin-panel service helpers for Copilot device login flows.

Neither the 502 responses nor the stored flow carry provider or exception text: a failure keeps
a closed error code (GitHub's own snake_case device-flow code when it passes the code validator)
and the exception class name.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from ...copilot_oauth import persist_copilot_oauth_tokens
from ...error_facts import error_code, error_text
from ...provider.oauth_config_bridge import read_oauth_metadata


def _device_flow_error_message(token_data: dict[str, Any], default: str = "authorization_pending") -> str:
    """GitHub's device-flow error code; its free-text ``error_description`` is never kept."""
    return error_code(str(token_data.get("error") or default).strip() or default)


async def start_copilot_device_flow(
    db: AsyncSession,
    *,
    provider_id: str,
    flow_state: dict[str, dict[str, Any]],
    begin_flow_func: Callable[[], Any],
) -> dict[str, Any]:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider or provider.driver != "copilot_api":
        raise HTTPException(status_code=404, detail="Copilot provider not found")
    try:
        device_data = await begin_flow_func()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub device flow could not be started. {error_text('device_flow_start_failed', exc)}",
        ) from None
    if "error" in device_data:
        raise HTTPException(status_code=502, detail=_device_flow_error_message(device_data, "device_flow_failed"))
    if not device_data.get("device_code") or not device_data.get("user_code"):
        raise HTTPException(status_code=502, detail="GitHub device flow response was missing required fields")
    flow_id = str(uuid.uuid4())
    flow_state[flow_id] = {
        "provider_id": provider.id,
        "device_code": device_data.get("device_code", ""),
        "user_code": device_data.get("user_code", ""),
        "verification_uri": device_data.get("verification_uri", "https://github.com/login/device"),
        "interval": int(device_data.get("interval", 5) or 5),
        "client_id": device_data.get("client_id", ""),
        "status": "pending",
        "error": "",
    }
    return {
        "flow_id": flow_id,
        "user_code": flow_state[flow_id]["user_code"],
        "verification_uri": flow_state[flow_id]["verification_uri"],
        "interval": flow_state[flow_id]["interval"],
        "client_id": flow_state[flow_id]["client_id"],
    }


async def poll_copilot_device_login(
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
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    flow = flow_state.get(flow_id)
    if not provider or provider.driver != "copilot_api" or not flow or flow.get("provider_id") != provider.id:
        raise HTTPException(status_code=404, detail="Copilot login flow not found")
    try:
        token_data = await poll_flow_func(flow["device_code"])
    except Exception as exc:
        flow["status"] = "failed"
        flow["error"] = error_text("device_flow_poll_failed", exc)
        raise HTTPException(
            status_code=502, detail=f"GitHub device flow could not be polled. {flow['error']}"
        ) from None
    if token_data.get("access_token"):
        try:
            await persist_copilot_oauth_tokens(
                db,
                provider=provider,
                token_data=token_data,
                set_secret_value_func=set_secret_value_func,
                fetch_profile_func=fetch_profile_func,
            )
        except Exception as exc:
            flow["status"] = "failed"
            flow["error"] = (
                f"GitHub login succeeded, but token storage failed. {error_text('token_storage_failed', exc)}"
            )
            await db.rollback()
            return {"status": "failed", "error": flow["error"]}
        flow_state.pop(flow_id, None)
        meta = await read_oauth_metadata(db, provider)
        return {"status": "connected", "login": meta.get("login", "")}
    flow_error_code = _device_flow_error_message(token_data)
    if flow_error_code == "slow_down":
        flow["status"] = "waiting"
        flow["interval"] = min(flow["interval"] + 5, 30)
        return {"status": "waiting", "interval": flow["interval"]}
    if flow_error_code == "authorization_pending":
        return {"status": "pending"}
    flow["status"] = "failed"
    flow["error"] = flow_error_code
    return {"status": "failed", "error": flow["error"]}
