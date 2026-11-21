"""A plugin's UI in Octryx: files, token, settings, bridge.

- **Files**: the UI bundle is kept at install (``plugin_ui_files``) and served under
  ``/plugin-ui/{install_id}/{token}/{path}`` into a sandboxed iframe (``allow-scripts allow-forms``, never
  ``allow-same-origin``). Every response carries a strict CSP (no network: ``connect-src 'none'``; only framed by
  Octryx), ``Referrer-Policy: no-referrer`` and ``nosniff``.
- **Token**: a sandboxed iframe has an opaque origin and sends no cookies, so the viewer's access travels in the
  path. The plugin can read it, therefore it opens only GET on this one install's files: its own audience (never an
  Octryx bearer), bound to install and viewer, valid one hour. Expired: 401 ``plugin_ui_token_expired``.
- **Settings**: plain values on the install, secrets (``format: password`` or ``x-secret: true``) in the secret store;
  reading a secret only says whether it is set.
- **Bridge**: the plugin UI asks Octryx through the frame (postMessage), the frame calls ``bridge``. Only methods the
  manifest declares (``contributes.ui.methods``) run, always **as the viewer**: an Octryx tool through the same
  governed chain as chat (roles, connector policy, approvals: a write returns ``confirmation_required`` and the person
  confirms in the Octryx frame), a tool of the plugin's own MCP server through the registry's governed MCP path,
  ``settings.get`` without secrets. Every call is audited.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import AuditLog, Session
from ...models.runtime.plugin_install import STATUS_ACTIVE, PluginInstall, PluginUiFile
from ...time_utils import utc_now_aware
from .manifest import MCP_METHOD, SETTINGS_METHOD

TOKEN_AUDIENCE = "octryx-plugin-ui"
TOKEN_ISSUER = "octryx-backend"
TOKEN_SCOPE = "plugin_ui"
TOKEN_LIFETIME = timedelta(hours=1)
AUDIT_BRIDGE = "plugins.bridge_call"
AUDIT_SETTINGS = "plugins.settings_saved"
SESSION_AGENT_TYPE = "plugin"
FILE_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; font-src 'self' data:; connect-src 'none'; "
                                "frame-ancestors 'self'; form-action 'none'; base-uri 'none'"),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
}


class PluginUiError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---- token -------------------------------------------------------------------------------------------------------

def issue_token(install_id: str, user_id: str) -> str:
    payload = {"sub": user_id, "iid": install_id, "scope": TOKEN_SCOPE, "aud": TOKEN_AUDIENCE, "iss": TOKEN_ISSUER,
               "exp": utc_now_aware() + TOKEN_LIFETIME}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def read_token(token: str, install_id: str) -> str:
    """The viewer's user id, or :class:`PluginUiError` (expired: 401 ``plugin_ui_token_expired``)."""
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=TOKEN_AUDIENCE,
                            issuer=TOKEN_ISSUER)
    except jwt.ExpiredSignatureError:
        raise PluginUiError("plugin_ui_token_expired", "Reload the plugin.", 401) from None
    except jwt.PyJWTError:
        raise PluginUiError("plugin_ui_token_invalid", "Not found.", 404) from None
    if claims.get("scope") != TOKEN_SCOPE or claims.get("iid") != install_id or not claims.get("sub"):
        raise PluginUiError("plugin_ui_token_invalid", "Not found.", 404)
    return str(claims["sub"])


def masked_path(path: str) -> str:
    """``/plugin-ui/<id>/<token>/x`` → ``/plugin-ui/<id>/***/x`` (access logs never keep the token)."""
    parts = path.split("/", 4)
    if len(parts) >= 4 and parts[1] == "plugin-ui":
        parts[3] = "***"
    return "/".join(parts)


# ---- view and files ----------------------------------------------------------------------------------------------

def ui_of(row: PluginInstall) -> dict[str, Any]:
    return dict((dict(row.manifest_json or {}).get("contributes") or {}).get("ui") or {})


def ui_view(row: PluginInstall, user_id: str, *, base: str = "/plugin-ui") -> dict[str, Any]:
    if row.status != STATUS_ACTIVE:
        raise PluginUiError("plugin_disabled", "The plugin is disabled.", 404)
    ui = ui_of(row)
    if not ui.get("bundle"):
        raise PluginUiError("plugin_has_no_ui", "This plugin brings no UI.", 404)
    return {
        "install_id": row.id, "plugin": row.plugin_key, "version": row.version,
        "base_url": f"{base}/{row.id}/{issue_token(row.id, user_id)}/",
        "expires_in": int(TOKEN_LIFETIME.total_seconds()),
        "slots": {slot: ui.get(slot) or [] for slot in ("pages", "tiles", "tabs", "phone")},
        "methods": ui.get("methods") or [],
    }


async def ui_file(db: AsyncSession, install_id: str, token: str, path: str) -> PluginUiFile:
    read_token(token, install_id)
    row = await db.get(PluginInstall, install_id)
    if row is None or row.status != STATUS_ACTIVE:
        raise PluginUiError("plugin_not_found", "Not found.", 404)
    found = (await db.execute(select(PluginUiFile).where(PluginUiFile.install_id == install_id,
                                                         PluginUiFile.path == (path or "index.html")))).scalar()
    if found is None:
        raise PluginUiError("plugin_ui_file_not_found", "Not found.", 404)
    return found


# ---- settings ----------------------------------------------------------------------------------------------------

def _schema(row: PluginInstall) -> dict[str, Any]:
    return dict(dict(row.permissions_json or {}).get("settings") or {})


def _is_secret(spec: dict[str, Any]) -> bool:
    return spec.get("format") == "password" or spec.get("x-secret") is True


def _secret_tool(row: PluginInstall) -> str:
    return f"plugin:{row.id}"


async def read_settings(db: AsyncSession, row: PluginInstall) -> dict[str, Any]:
    from ..secret.service import get_secret_entry

    schema, plain = _schema(row), dict(row.settings_json or {})
    values: dict[str, Any] = {}
    for key, spec in dict(schema.get("properties") or {}).items():
        if _is_secret(dict(spec or {})):
            entry = await get_secret_entry(db, tool_name=_secret_tool(row), field_name=key,
                                           project_id=row.workspace_id)
            values[key] = {"set": entry is not None}
        elif key in plain:
            values[key] = plain[key]
    return {"schema": schema, "values": values}


def _checked(spec: dict[str, Any], key: str, value: Any) -> Any:
    kind = spec.get("type")
    ok = {"string": isinstance(value, str), "boolean": isinstance(value, bool),
          "integer": isinstance(value, int) and not isinstance(value, bool),
          "number": isinstance(value, int | float) and not isinstance(value, bool)}.get(kind, True)
    if not ok or ("enum" in spec and value not in spec["enum"]):
        raise PluginUiError("plugin_setting_invalid", f"'{key}' is not a valid {kind}.", 422)
    if isinstance(value, str) and len(value) > 4000:
        raise PluginUiError("plugin_setting_invalid", f"'{key}' is too long.", 422)
    return value


async def save_settings(db: AsyncSession, row: PluginInstall, values: dict[str, Any], *, user_id: str
                        ) -> dict[str, Any]:
    """Validate against the plugin's schema; a secret field left out keeps its stored value."""
    from ..secret.service import get_secret_entry, set_secret_value

    schema = _schema(row)
    properties = dict(schema.get("properties") or {})
    unknown = sorted(set(values) - set(properties))
    if unknown:
        raise PluginUiError("plugin_setting_unknown", f"Unknown settings: {', '.join(unknown)}.", 422)
    plain = dict(row.settings_json or {})
    changed: list[str] = []
    for key, raw in values.items():
        spec = dict(properties[key] or {})
        if _is_secret(spec):
            if raw in (None, ""):
                continue
            await set_secret_value(db, tool_name=_secret_tool(row), field_name=key, project_id=row.workspace_id,
                                   value=str(_checked({**spec, "type": "string"}, key, raw)))
        elif raw is None:
            plain.pop(key, None)
        else:
            plain[key] = _checked(spec, key, raw)
        changed.append(key)
    for key in schema.get("required") or []:
        spec = dict(properties.get(key) or {})
        present = (await get_secret_entry(db, tool_name=_secret_tool(row), field_name=key,
                                          project_id=row.workspace_id)) is not None if _is_secret(spec) \
            else key in plain
        if not present:
            raise PluginUiError("plugin_setting_required", f"'{key}' is required.", 422)
    row.settings_json = plain
    db.add(AuditLog(user_id=user_id, action=AUDIT_SETTINGS, resource_type="plugin_install", resource_id=row.id,
                    details={"plugin": row.plugin_key, "changed": sorted(changed)}))  # never the values
    await db.flush()
    return await read_settings(db, row)


# ---- bridge ------------------------------------------------------------------------------------------------------

async def _session(db: AsyncSession, row: PluginInstall, user_id: str, workspace_id: str) -> str:
    """The viewer's session for this plugin in this Workspace (approvals and their grants are keyed on it)."""
    sessions = (await db.execute(select(Session).where(
        Session.user_id == user_id, Session.project_id == workspace_id, Session.agent_type == SESSION_AGENT_TYPE,
        Session.status == "active"))).scalars().all()
    found = next((item for item in sessions if dict(item.metadata_ or {}).get("plugin_install_id") == row.id), None)
    if found is None:
        found = Session(user_id=user_id, project_id=workspace_id, agent_type=SESSION_AGENT_TYPE, status="active",
                        metadata_={"plugin_install_id": row.id, "plugin": row.plugin_key, "title": row.name})
        db.add(found)
        await db.flush()
    return found.id


async def _tool_context(db: AsyncSession, user_id: str, workspace_id: str, session_id: str):
    """The viewer's chat context: read-only, a connector write only confirmed per call, like a chat turn."""
    from app.tools.capability_requirements import CAPABILITY_READ_ONLY

    from ...tools.context import ToolContext
    from ..mcp_extra_scope import chat_tool_project_config
    from ..run_capability.declared import DeclaredRunCapability
    from ..work_role_model.surfaces import chat_turn_grant

    capability = DeclaredRunCapability(capability_class=CAPABILITY_READ_ONLY, source=CAPABILITY_SOURCE,
                                       chat_connector_writes=True)
    context = ToolContext(user_id=user_id, project_ids=[workspace_id], roles=[], session_id=session_id,
                          project_config=await chat_tool_project_config(db, user_id=user_id,
                                                                        workspace_id=workspace_id), db=db,
                          run_capability=capability.tool_context_state())
    context.work_role_grant = await chat_turn_grant(db, user_id=user_id, workspace_id=workspace_id)
    return context


def _outcome(result: Any) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {"result": result}
    category = str(payload.get("category") or payload.get("error_category") or "")
    if category == "approval_required" or "pending approval" in str(payload.get("error") or "").lower():
        return {"error": {"code": "confirmation_required", "message": "Confirm this action in Octryx.",
                          "approval": {key: payload.get(key) for key in ("approval_id", "change_preview_id",
                                                                         "tool_name") if payload.get(key)}}}
    if payload.get("error") and not payload.get("success", False):
        return {"error": {"code": "tool_refused", "message": str(payload.get("error"))[:500]}}
    return {"result": payload}


CAPABILITY_SOURCE = "plugin_page"


async def bridge(db: AsyncSession, row: PluginInstall, *, user_id: str, workspace_id: str, method: str,
                 params: dict[str, Any]) -> dict[str, Any]:
    """Run one declared method as the viewer; ``{"result": …}`` or ``{"error": {code, message}}``. Flushes."""
    if row.status != STATUS_ACTIVE:
        raise PluginUiError("plugin_disabled", "The plugin is disabled.", 409)
    if method not in (ui_of(row).get("methods") or []):
        raise PluginUiError("plugin_method_not_declared", f"'{method}' is not a method this plugin declares.", 403)
    if method == SETTINGS_METHOD:
        values = (await read_settings(db, row))["values"]
        outcome = {"result": {key: value for key, value in values.items() if not isinstance(value, dict)}}
    else:
        from ...tools.registry import execute_tool_with_plugins

        tool = f"mcp__{method.replace('.', '__', 1)}" if MCP_METHOD.fullmatch(method) and "." in method else method
        session_id = await _session(db, row, user_id, workspace_id)
        context = await _tool_context(db, user_id, workspace_id, session_id)
        try:
            from ..content_security.knowledge_fence import unfenced_result

            outcome = _outcome(unfenced_result(await execute_tool_with_plugins(tool, dict(params or {}), context)))
        except Exception as error:  # noqa: BLE001 - a tool that raises is a refused call, never a 500 to the plugin
            outcome = {"error": {"code": "tool_failed", "message": f"{type(error).__name__}"}}
    db.add(AuditLog(user_id=user_id, action=AUDIT_BRIDGE, resource_type="plugin_install", resource_id=row.id,
                    details={"plugin": row.plugin_key, "version": row.version, "method": method,
                             "workspace_id": workspace_id,
                             "outcome": outcome["error"]["code"] if "error" in outcome else "ok"}))
    await db.flush()
    return outcome


__all__ = ["FILE_HEADERS", "PluginUiError", "bridge", "issue_token", "masked_path", "read_settings", "read_token",
           "save_settings", "ui_file", "ui_view"]
