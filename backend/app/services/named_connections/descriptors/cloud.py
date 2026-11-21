"""Azure and GCP: named connections per subscription or project.

- **Azure**: a service principal (tenant, client id, client secret) bound to subscription ids; a call names
  ``subscription_id`` (or a ``resource_id`` under ``/subscriptions/<id>/``). The connection's subscription list
  is narrowed to its bound subscriptions. The Microsoft Graph helper prefers Outlook and SharePoint
  credentials of the merged config over Azure's own, so a named Azure call never carries them
  (``named_drops``): it signs in with exactly its own principal.
- **GCP**: a service account JSON or an access token bound to project ids; a call names ``project_id``. The
  default serves its own ``gcp_project_id``.

A named connection without its credential is refused before the call.
"""

from __future__ import annotations

import re

from ..descriptor import (
    CASE_LOWER,
    UNSCOPED_SINGLE,
    Allowlist,
    Binding,
    ConnectorDescriptor,
    Field,
    UnitIncompleteError,
    present,
    require_fields,
)

_GUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
_SUBSCRIPTION_IN_RESOURCE = re.compile(rf"/subscriptions/({_GUID})(/|$)", re.IGNORECASE)
_GRAPH_PREFERRED = tuple(
    f"{prefix}_{name}"
    for prefix in ("outlook", "sharepoint")
    for name in ("access_token", "tenant_id", "client_id", "client_secret", "client_secret_secret_ref")
) + ("microsoft_graph_access_token", "azure_access_token")


def _unavailable() -> UnitIncompleteError:
    return UnitIncompleteError("named_connection_credential_unavailable", "its credential is not available.")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _subscription_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    explicit = _text(params.get("subscription_id"))
    if explicit:
        return (explicit,)
    found = _SUBSCRIPTION_IN_RESOURCE.search(_text(params.get("resource_id")))
    return (found.group(1),) if found else ()


def _azure_complete(config: dict) -> None:
    require_fields(config, "azure_tenant_id", "azure_client_id", "azure_client_secret")


def _azure_guard(config: dict) -> None:
    if not all(_text(config.get(name)) for name in ("azure_tenant_id", "azure_client_id", "azure_client_secret")):
        raise _unavailable()


AZURE = ConnectorDescriptor(
    connector="azure",
    label="Azure",
    binding=Binding("subscription", "Subscriptions", _GUID, CASE_LOWER, "00000000-0000-0000-0000-000000000001"),
    fields=(
        Field("azure_tenant_id", "Tenant id", required=True),
        Field("azure_client_id", "Client id", required=True),
        Field("azure_client_secret", "Client secret", kind="secret", required=True),
    ),
    usable_field="azure_tenant_id",
    default_usable_fields=("azure_client_id",),
    request_keys=_subscription_keys,
    request_params={"subscription_id": {
        "type": "string", "description": "Optional: the Azure subscription id; the call runs on its connection.",
    }},
    allowlist=Allowlist("azure_subscription_ids", serves_unlisted=False),
    unscoped=UNSCOPED_SINGLE,
    named_drops=_GRAPH_PREFERRED,
    complete=_azure_complete,
    runtime_guard=_azure_guard,
)


def _project_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    project = _text(params.get("project_id"))
    return (project,) if project else ()


def _gcp_complete(config: dict) -> None:
    if not (present(config, "gcp_service_account_json") or present(config, "gcp_access_token")):
        raise UnitIncompleteError("connection_invalid",
                                  "An own GCP connection needs gcp_service_account_json or gcp_access_token.")


def _gcp_guard(config: dict) -> None:
    if not (_text(config.get("gcp_service_account_json")) or _text(config.get("gcp_access_token"))):
        raise _unavailable()


GCP = ConnectorDescriptor(
    connector="gcp",
    label="Google Cloud",
    binding=Binding("project", "Projects", r"[A-Za-z][A-Za-z0-9-]{4,28}[A-Za-z0-9]", CASE_LOWER,
                    "project-id-1, project-id-2"),
    fields=(
        Field("gcp_region", "Region", placeholder="region"),
        Field("gcp_service_account_json", "Service account JSON", kind="secret"),
        Field("gcp_access_token", "Access token", kind="secret"),
    ),
    usable_field="gcp_region",
    default_usable_fields=("gcp_project_id", "gcp_service_account_json", "gcp_service_account_json_secret_ref",
                           "gcp_access_token", "gcp_access_token_secret_ref"),
    request_keys=_project_keys,
    request_params={"project_id": {
        "type": "string", "description": "Optional: the GCP project id; the call runs on its connection.",
    }},
    default_key_fields=("gcp_project_id",),
    unscoped=UNSCOPED_SINGLE,
    named_drops=("gcp_project_id",),
    tool_names=frozenset({"list_gcp_cloud_sql_instances", "get_gcp_cloud_sql_metrics"}),
    complete=_gcp_complete,
    runtime_guard=_gcp_guard,
)

__all__ = ["AZURE", "GCP"]
