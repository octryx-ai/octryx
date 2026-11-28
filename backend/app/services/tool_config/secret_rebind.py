"""A stored secret never silently follows its connection to another host."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..secret import secret_ref_field_name
from .connection_fields import client_id_fields, secret_fields, target_fields

SECRET_REBIND_REQUIRED = "secret_rebind_required"
CONFIRM_SECRET_REBIND_FIELD = "confirm_secret_rebind"
AUDIT_ACTION_REFUSED = "tool_config.secret_rebind_refused"
AUDIT_ACTION_CONFIRMED = "tool_config.secret_rebind_confirmed"


@dataclass(frozen=True, slots=True)
class SecretRebind:
    tool_name: str
    project_id: str | None
    changed_target_fields: tuple[str, ...]
    carried_secret_fields: tuple[str, ...]


class SecretRebindRequiredError(Exception):
    def __init__(self, rebind: SecretRebind) -> None:
        super().__init__(SECRET_REBIND_REQUIRED)
        self.rebind = rebind

    def detail(self) -> dict[str, Any]:
        return {
            "state": SECRET_REBIND_REQUIRED,
            "tool_name": self.rebind.tool_name,
            "changed_target_fields": list(self.rebind.changed_target_fields),
            "kept_fields": list(self.rebind.carried_secret_fields),
            "remediation": (
                "Re-enter the listed secrets for the new target, or confirm the rebind explicitly "
                f"with {CONFIRM_SECRET_REBIND_FIELD}=true."
            ),
        }


def _target_identity(field: str, value: Any) -> tuple[str, ...] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not field.endswith("_url"):
        return (text.lower(),)
    try:
        parts = urlsplit(text)
        return (parts.scheme.lower(), (parts.hostname or "").lower().rstrip("."), str(parts.port or ""))
    except ValueError:
        return ("unparseable", text)


def changed_target_fields(
    tool_name: str, stored: dict | None, proposed: dict | None, inherited: dict | None = None
) -> tuple[str, ...]:
    changed = []
    for field in target_fields(tool_name):
        new = _target_identity(field, (proposed or {}).get(field))
        old = _target_identity(field, (stored or {}).get(field))
        if inherited:
            inherited_identity = _target_identity(field, inherited.get(field))
            new = new if new is not None else inherited_identity
            old = old if old is not None else inherited_identity
        if new is not None and new != old:
            changed.append(field)
    for field in client_id_fields(tool_name):  # exact: client ids are case-sensitive at the IdP
        new_id, old_id = (str((config or {}).get(field) or "").strip() for config in (proposed, stored))
        if new_id and new_id != old_id:
            changed.append(field)
    return tuple(changed)


def carried_secret_fields(tool_name: str, stored: dict | None, submitted: set[str]) -> tuple[str, ...]:
    return tuple(
        field
        for field in secret_fields(tool_name)
        if field not in submitted and str((stored or {}).get(secret_ref_field_name(field)) or "").strip()
    )


def evaluate_secret_rebind(
    *,
    tool_name: str,
    project_id: str | None,
    stored: dict | None,
    proposed: dict | None,
    submitted_secret_fields: set[str],
    confirmed: bool,
    inherited: dict | None = None,
) -> SecretRebind | None:
    changed = changed_target_fields(tool_name, stored, proposed, inherited)
    carried = carried_secret_fields(tool_name, stored, submitted_secret_fields) if changed else ()
    if not changed or not carried:
        return None
    rebind = SecretRebind(tool_name, project_id, changed, carried)
    if not confirmed:
        raise SecretRebindRequiredError(rebind)
    return rebind


def record_secret_rebind_audit(
    db: AsyncSession, *, actor_user_id: str | None, rebind: SecretRebind, refused: bool
) -> None:
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_REFUSED if refused else AUDIT_ACTION_CONFIRMED,
        resource_type="tool_config",
        resource_id=f"{rebind.tool_name}:{rebind.project_id or 'global'}",
        project_id=rebind.project_id,
        before=None,
        after=None,
        details={
            "tool_name": rebind.tool_name,
            "project_id": rebind.project_id,
            "changed_target_fields": list(rebind.changed_target_fields),
            # Key names avoid the audit redactor's markers ("secret"), so the names survive.
            "kept_fields": list(rebind.carried_secret_fields),
            "state": SECRET_REBIND_REQUIRED if refused else "secret_rebind_confirmed",
        },
    )


async def enforce_secret_rebind(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    tool_name: str,
    project_id: str | None,
    stored: dict | None,
    proposed: dict | None,
    submitted_secret_fields: set[str],
    confirmed: Any,
    inherits_global_target: bool = True,
) -> None:
    inherits = project_id is not None and inherits_global_target
    inherited = await _inherited_targets(db, tool_name) if inherits else None
    try:
        rebind = evaluate_secret_rebind(
            tool_name=tool_name,
            project_id=project_id,
            stored=stored,
            proposed=proposed,
            submitted_secret_fields=submitted_secret_fields,
            confirmed=is_confirmed(confirmed),
            inherited=inherited,
        )
    except SecretRebindRequiredError as refused:
        await db.rollback()
        record_secret_rebind_audit(db, actor_user_id=actor_user_id, rebind=refused.rebind, refused=True)
        await db.commit()
        raise
    if rebind is not None:
        record_secret_rebind_audit(db, actor_user_id=actor_user_id, rebind=rebind, refused=False)


async def _inherited_targets(db: AsyncSession, tool_name: str) -> dict:
    from . import get_tool_config  # the package imports this module

    entry = await get_tool_config(db, tool_name, None)
    if entry is None or not entry.is_active:
        return {}
    config = dict(entry.config or {})
    return {field: config[field] for field in target_fields(tool_name) if field in config}


async def enforce_global_payload_rebind(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    tool_name: str,
    stored: dict | None,
    proposed: dict | None,
    payload: dict[str, Any],
) -> None:
    submitted = {field for field in secret_fields(tool_name) if str(payload.get(field) or "").strip()}
    try:
        await enforce_secret_rebind(
            db,
            actor_user_id=actor_user_id,
            tool_name=tool_name,
            project_id=None,
            stored=stored,
            proposed=proposed,
            submitted_secret_fields=submitted,
            confirmed=payload.get(CONFIRM_SECRET_REBIND_FIELD),
        )
    except SecretRebindRequiredError as refused:
        raise HTTPException(status_code=409, detail=refused.detail()) from None


def is_confirmed(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() == "true"


__all__ = [
    "AUDIT_ACTION_CONFIRMED",
    "AUDIT_ACTION_REFUSED",
    "CONFIRM_SECRET_REBIND_FIELD",
    "SECRET_REBIND_REQUIRED",
    "SecretRebind",
    "SecretRebindRequiredError",
    "carried_secret_fields",
    "changed_target_fields",
    "enforce_global_payload_rebind",
    "enforce_secret_rebind",
    "evaluate_secret_rebind",
    "is_confirmed",
    "record_secret_rebind_audit",
]
