"""The connection unit of a named connection, as its connector's descriptor declares it.

The same rules as the Workspace's own connection (``connection_unit.py``) for every connector type: only
the unit's non-secret fields are returned, a typed secret is taken only from the request, a mode switch
drops the previous mode's principal and secret ref (connectors with an auth mode), and a unit is complete
only as the descriptor's ``complete`` check says. Every message names fields and fixed codes only.
"""

from __future__ import annotations

from typing import Any

from ...named_connections.contract import require_descriptor
from ...named_connections.descriptor import ConnectorDescriptor, UnitIncompleteError
from ...secret import secret_ref_field_name
from ...tool_config.connection_fields import auth_mode_fields
from ...tool_config.presets import TOOL_CONFIG_PRESETS
from .connection_unit import is_set, refuse
from .connection_unit import one_credential_unit as _mode_switch


def _kinds(descriptor: ConnectorDescriptor) -> dict[str, str]:
    return {item.name: item.kind for item in descriptor.fields}


def public_fields(tool: str, config: dict[str, Any]) -> dict[str, Any]:
    descriptor = require_descriptor(tool)
    return {name: config[name] for name in descriptor.editable_fields if is_set(config.get(name))}


def secret_status(tool: str, config: dict[str, Any]) -> dict[str, bool]:
    return {
        name: bool(config.get(name) or config.get(secret_ref_field_name(name)))
        for name in require_descriptor(tool).secret_fields
    }


def _value(kind: str, value: Any) -> Any:
    """A payload value in its field's form; ``None`` removes the field."""
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return True if text in ("true", "1", "yes", "on") else False if text in ("false", "0", "no", "off") else None
    if kind == "list":
        items = value if isinstance(value, list | tuple) else str(value or "").replace(",", " ").split()
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        return cleaned or None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if kind == "int" and isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())  # a form sends text; anything else stays as sent and the validation refuses it
    return value.strip() if isinstance(value, str) else value


def proposed_unit(tool: str, stored: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """The stored unit with the payload's non-secret fields applied (empty removes)."""
    descriptor = require_descriptor(tool)
    kinds = _kinds(descriptor)
    proposed = dict(stored)
    for name in descriptor.editable_fields:
        if name in payload:
            value = _value(kinds[name], payload[name])
            if value is None:
                proposed.pop(name, None)
            else:
                proposed[name] = value
    return proposed


def one_credential_unit(tool: str, stored: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """A connector with an auth mode drops the fields the new mode does not read; others keep the unit."""
    return _mode_switch(tool, stored, proposed) if auth_mode_fields(tool) else proposed


def kept_secret_view(tool: str, stored: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """``stored`` without the secrets (refs or plaintext) the proposal does not keep."""
    names = require_descriptor(tool).secret_fields
    secrets = {*names, *(secret_ref_field_name(name) for name in names)}
    return {key: value for key, value in stored.items() if key not in secrets or key in proposed}


def typed_secrets(tool: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        name: payload[name].strip()
        for name in require_descriptor(tool).secret_fields
        if isinstance(payload.get(name), str) and payload[name].strip()
    }


def preset_fields_of(tool: str, config: dict[str, Any]) -> dict[str, Any]:
    """The part of ``config`` the preset's validator checks: its fields and secret refs, except the fields the
    descriptor types itself (yes/no, lists: read by their kind in :func:`proposed_unit`)."""
    preset = TOOL_CONFIG_PRESETS.get(tool, {})
    secrets = preset.get("secret_fields") or ()
    known = {*(preset.get("fields") or ()), *(secret_ref_field_name(name) for name in secrets)}
    typed = {name for name, kind in _kinds(require_descriptor(tool)).items() if kind in ("bool", "list")}
    return {key: value for key, value in config.items() if key in known and key not in typed}


def require_complete_unit(tool: str, effective: dict[str, Any]) -> None:
    """The descriptor's completeness check; an incomplete unit is a 422 with the check's fixed code."""
    try:
        require_descriptor(tool).complete(effective)
    except UnitIncompleteError as exc:
        raise refuse(422, exc.code, str(exc)) from None


__all__ = [
    "kept_secret_view",
    "one_credential_unit",
    "preset_fields_of",
    "proposed_unit",
    "public_fields",
    "require_complete_unit",
    "secret_status",
    "typed_secrets",
]
