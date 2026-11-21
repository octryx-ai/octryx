"""The connection of a ``kubernetes`` Source Sync connector: one cluster's API URL and token.

Resolved like every Source Sync connection (``connections.py``): a named connection bound to the
connector's cluster, or the Workspace's default ``kubernetes`` entry. Only the API path is
used: a kubeconfig, a context or the platform pod's own service account never are, so a config
without ``k8s_api_url`` and ``k8s_token`` is ``connection_not_configured``. ``k8s_allowed_namespaces``
limits what the connector may read; ``k8s_verify_tls: false`` turns the TLS check off as the
Kubernetes tools do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_KUBERNETES
from ...ledger.errors import InvalidEvidenceRequestError
from ..source_url import normalize_source_url

# A namespace (an RFC 1123 label) and a cluster name (the named-connection binding of the Kubernetes tools).
NAMESPACE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
CLUSTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True, slots=True)
class KubernetesConnection:
    """API URL, token and namespace allowlist of one cluster connection; the token never leaves ``repr``."""

    base_url: str
    token: str = field(repr=False)
    verify: bool = True
    # ``None``: the connection may read every namespace; else only these.
    allowed_namespaces: frozenset[str] | None = None
    kind: str = CONNECTOR_KIND_KUBERNETES

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def http_auth(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        return None



def kubernetes_connection(config: dict) -> KubernetesConnection | None:
    """The API connection a resolved ``kubernetes`` config describes; ``None`` without its URL or token.

    Only the API path: a kubeconfig, a context or the platform pod's service account are never used.
    """
    token = str(config.get("k8s_token") or "").strip()
    try:
        base_url = normalize_source_url(str(config.get("k8s_api_url") or "").strip().rstrip("/"))
    except InvalidEvidenceRequestError:
        base_url = None
    if not base_url or not token:
        return None
    raw = config.get("k8s_allowed_namespaces")
    items = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    allowed = frozenset(str(item).strip() for item in items if str(item).strip())
    verify = config.get("k8s_verify_tls")
    return KubernetesConnection(base_url, token, verify is not False, allowed or None)


__all__ = ["CLUSTER", "NAMESPACE", "KubernetesConnection", "kubernetes_connection"]
