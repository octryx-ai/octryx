"""Validated config of a submitted tool config form, with its secrets stored or carried for a test."""

import json

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from ...services.tool_config import TOOL_CONFIG_PRESETS

__all__ = [
    "_build_tool_config_payload",
]


async def _apply_secret_fields(
    db: AsyncSession,
    *,
    secret_fields: list[str],
    form_data: FormData,
    parsed_config: dict,
    existing_config: dict,
    tool_name: str,
    project_id: str | None,
    persist_secrets: bool,
) -> None:
    """Replace the preset's secret fields in ``parsed_config`` by secret refs (or the typed value for a test)."""
    from ...services.secret import set_secret_value

    for field_name in secret_fields:
        parsed_config.pop(field_name, None)
        ref_key = f"{field_name}_secret_ref"
        # A secret ref is only ever set here, from a submitted value or the stored entry.
        parsed_config.pop(ref_key, None)
        submitted_secret = str(form_data.get(field_name) or "").strip()
        if submitted_secret and not persist_secrets:
            parsed_config[field_name] = submitted_secret
        elif submitted_secret:
            secret_entry = await set_secret_value(
                db,
                tool_name=tool_name,
                field_name=field_name,
                project_id=project_id,
                value=submitted_secret,
            )
            parsed_config[ref_key] = secret_entry.id
        elif existing_config.get(ref_key):
            parsed_config[ref_key] = existing_config[ref_key]


async def _build_tool_config_payload(
    request: Request,
    db: AsyncSession,
    *,
    tool_name: str,
    project_id: str | None,
    config_json: str,
    actor_user_id: str | None = None,
    persist_secrets: bool = True,
) -> dict:
    """The validated config of one tool config form.

    ``persist_secrets=False`` (a connection test) never writes the secret store: a typed
    secret is carried in the returned config for that test only, and the stored refs stay untouched.
    """
    from ...services.tool_config import get_tool_config, validate_tool_config
    from ...services.tool_config.secret_rebind import CONFIRM_SECRET_REBIND_FIELD, enforce_secret_rebind

    form_data = await request.form()
    try:
        parsed_config = json.loads(config_json or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON for tool config")

    existing_entry = await get_tool_config(db, tool_name, project_id)
    existing_config = dict(existing_entry.config) if existing_entry and existing_entry.config else {}
    preset = TOOL_CONFIG_PRESETS.get(tool_name, {})
    # Before any secret is stored: a kept secret never silently follows a changed target
    # (raises SecretRebindRequiredError after auditing it; the route answers 409).
    await enforce_secret_rebind(
        db,
        actor_user_id=actor_user_id,
        tool_name=tool_name,
        project_id=project_id,
        stored=existing_config,
        proposed=parsed_config if isinstance(parsed_config, dict) else {},
        submitted_secret_fields={
            field for field in preset.get("secret_fields", []) if str(form_data.get(field) or "").strip()
        },
        confirmed=form_data.get(CONFIRM_SECRET_REBIND_FIELD),
    )
    await _apply_secret_fields(
        db,
        secret_fields=preset.get("secret_fields", []),
        form_data=form_data,
        parsed_config=parsed_config,
        existing_config=existing_config,
        tool_name=tool_name,
        project_id=project_id,
        persist_secrets=persist_secrets,
    )
    try:
        return validate_tool_config(tool_name, parsed_config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
