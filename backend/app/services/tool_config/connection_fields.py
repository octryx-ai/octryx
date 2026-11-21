"""Which fields of a connector preset form its connection identity, and how scopes combine them.

A connection has four kinds of field, all read from the preset's declared ``fields``:

* **secret fields**: the preset's ``secret_fields``, stored as ``<field>_secret_ref``;
* **principal fields**: who authenticates (``*_username``, ``*_email``, ``*_client_id``,
  ``*_tenant_id``, ``*_bind_dn``, ``*_role_arn``);
* **target fields**: where the credential is sent (``*_url``, ``*_host``, ``*_port``);
* **auth mode fields**: how the credential is sent (``*_auth_mode``);
* **OIDC option fields**: the remaining ``*_oidc_*`` settings of a client credentials grant (scope,
  audience, client authentication method). The ``*_oidc_token_url`` is a target field, the
  ``*_oidc_client_id`` a principal and the ``*_oidc_client_secret`` a secret by the rules above.

* **selector fields**: which local credential, identity file or executable a connector uses
  (``*_binary``, ``*_path``, ``*kubeconfig``, ``aws_profile``, ``terraform_var_file``), and the
  ``allow_platform_credentials`` opt-in, which selects the platform host's own credentials.

Secret, principal, auth mode and OIDC option fields together are the **credential unit**. A Workspace entry and the
global entry never mix their units: when the Workspace entry sets any credential or target
field of a connection, none of the global credential fields apply to it, so neither a
``confluence_token`` beside a global ``confluence_password`` nor a global credential sent to a
Workspace-chosen URL can happen. Non-credential fields (limits, allowlists) still merge field by
field. A global target is inherited only by a Workspace entry without a secret of its own: a
Workspace secret is bound to the Workspace's own target and never sent to an inherited one.
A Workspace entry with an own secret but no own target therefore has no usable connection
(fail closed) until its target is set again.

``Project.config`` is never a connection source: before the tool entries are merged into it,
every preset's target and credential-unit keys are removed from it (:func:`without_connection_identity`),
so a URL or a secret there can neither fill a fail-closed Workspace entry nor redirect a global secret.
Selector fields are removed from it as well: a kubeconfig, an AWS profile or a binary path chosen
in ``Project.config`` would pick a credential or an executable outside the governed entry. Scope
selectors bounded by the governed credential stay (regions, project/account/org ids, namespaces, an OAuth
scope, ``k8s_context``, which only picks a context inside the kubeconfig the entry supplies; stripping it
would fall back to that kubeconfig's default context, possibly another cluster).
"""

from __future__ import annotations

from functools import cache
from typing import Any

from ..secret import secret_ref_field_name
from .presets import TOOL_CONFIG_PRESETS

_PRINCIPAL_SUFFIXES = ("_username", "_email", "_client_id", "_tenant_id", "_bind_dn", "_role_arn")
_TARGET_SUFFIXES = ("_url", "_host", "_port")
_AUTH_MODE_SUFFIX = "_auth_mode"
_OIDC_MARKER = "_oidc_"
_SELECTOR_SUFFIXES = ("_binary", "_path", "kubeconfig")
_SELECTOR_NAMES = frozenset({"aws_profile", "terraform_var_file", "allow_platform_credentials"})


def _preset(tool_name: str) -> dict[str, Any]:
    return TOOL_CONFIG_PRESETS.get(str(tool_name or "").strip().lower(), {})


def secret_fields(tool_name: str) -> tuple[str, ...]:
    return tuple(_preset(tool_name).get("secret_fields") or ())


def principal_fields(tool_name: str) -> tuple[str, ...]:
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and field.endswith(_PRINCIPAL_SUFFIXES)
    )


def target_fields(tool_name: str) -> tuple[str, ...]:
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and field.endswith(_TARGET_SUFFIXES)
    )


def selector_fields(tool_name: str) -> tuple[str, ...]:
    """The non-secret fields that pick a local credential, identity file or executable."""
    secrets = set(secret_fields(tool_name))
    return tuple(
        field
        for field in _preset(tool_name).get("fields") or ()
        if field not in secrets and (field.endswith(_SELECTOR_SUFFIXES) or field in _SELECTOR_NAMES)
    )


def auth_mode_fields(tool_name: str) -> tuple[str, ...]:
    return tuple(field for field in _preset(tool_name).get("fields") or () if field.endswith(_AUTH_MODE_SUFFIX))


def oidc_option_fields(tool_name: str) -> tuple[str, ...]:
    """The ``*_oidc_*`` fields that are neither secret, principal nor target (scope, audience, client auth)."""
    other = {*secret_fields(tool_name), *principal_fields(tool_name), *target_fields(tool_name)}
    return tuple(
        field for field in _preset(tool_name).get("fields") or () if _OIDC_MARKER in field and field not in other
    )


def client_id_fields(tool_name: str) -> tuple[str, ...]:
    """The client ids and usernames a stored secret is bound to: a changed one rebinds it."""
    return tuple(
        field for field in principal_fields(tool_name)
        if field.endswith("_oidc_client_id") or field in ("servicenow_client_id", "servicenow_username")
    )


def credential_unit_keys(tool_name: str) -> frozenset[str]:
    """Every config key of the credential unit: principals, secrets and refs, the auth mode, OIDC options."""
    secrets = secret_fields(tool_name)
    return frozenset(
        (
            *principal_fields(tool_name),
            *secrets,
            *(secret_ref_field_name(field) for field in secrets),
            *auth_mode_fields(tool_name),
            *oidc_option_fields(tool_name),
        )
    )


def _is_set(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict | set):
        return bool(value)
    return True


def sets_connection_identity(tool_name: str, config: dict | None) -> bool:
    """True when ``config`` sets any credential-unit or target field of the connection."""
    keys = credential_unit_keys(tool_name) | frozenset(target_fields(tool_name))
    return any(_is_set((config or {}).get(key)) for key in keys)


def holds_own_secret(tool_name: str, config: dict | None) -> bool:
    """True when ``config`` holds a secret of its own: a value or a secret ref of any secret field."""
    return any(
        _is_set((config or {}).get(field)) or _is_set((config or {}).get(secret_ref_field_name(field)))
        for field in secret_fields(tool_name)
    )


@cache
def _connection_identity_keys() -> frozenset[str]:
    keys: set[str] = set()
    for tool_name in TOOL_CONFIG_PRESETS:
        keys |= credential_unit_keys(tool_name)
        keys |= {*target_fields(tool_name), *selector_fields(tool_name)}
    return frozenset(keys)


def connection_identity_keys() -> frozenset[str]:
    """Every preset's target, selector and credential-unit key: never a ``Project.config`` key."""
    return _connection_identity_keys()


def refused_connection_keys(patch: dict | None) -> list[str]:
    """The connection keys a ``Project.config`` write would set (sorted names, never values); clearing is allowed."""
    keys = _connection_identity_keys()
    return sorted(key for key, value in (patch or {}).items() if key in keys and value not in (None, ""))


def without_connection_identity(config: dict | None) -> dict:
    """``config`` without any preset's target, selector or credential-unit key, as a new dict."""
    keys = _connection_identity_keys()
    return {key: value for key, value in (config or {}).items() if key not in keys}


def global_config_for_scope(tool_name: str, global_config: dict, project_config: dict | None) -> dict:
    """The part of the global entry a Workspace entry inherits, as a new dict.

    The global credential unit is dropped whole when the Workspace entry sets any credential or
    target field of the connection. The global target is dropped too when the Workspace entry
    holds a secret of its own: own secret, own target. Everything else is inherited unchanged.
    """
    inherited = dict(global_config or {})
    if sets_connection_identity(tool_name, project_config):
        for key in credential_unit_keys(tool_name):
            inherited.pop(key, None)
    if holds_own_secret(tool_name, project_config):
        for key in target_fields(tool_name):
            inherited.pop(key, None)
    return inherited


__all__ = [
    "auth_mode_fields",
    "client_id_fields",
    "connection_identity_keys",
    "credential_unit_keys",
    "global_config_for_scope",
    "holds_own_secret",
    "oidc_option_fields",
    "principal_fields",
    "refused_connection_keys",
    "secret_fields",
    "selector_fields",
    "sets_connection_identity",
    "target_fields",
    "without_connection_identity",
]
