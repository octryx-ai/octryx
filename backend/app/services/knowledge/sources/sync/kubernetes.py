"""A Kubernetes cluster's workload inventory, on the Source Sync contract (operations graph)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_KUBERNETES
from .contract import (
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .http import SourceReader
from .kubernetes_connection import NAMESPACE, KubernetesConnection

MAX_NAMESPACES = 200
MAX_DEPLOYMENTS = 500
MAX_CONTAINERS = 20
# Kubernetes object names (RFC 1123 subdomains) and image references; anything else is a contract violation.
_OBJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")
_IMAGE = re.compile(r"^[^\s()|]{1,500}$")


def _items(payload: dict) -> list:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return items


def _truncated(payload: dict) -> bool:
    metadata = payload.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get("continue"))


def _count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


@dataclass(frozen=True, slots=True)
class Deployment:
    name: str
    resource_version: str
    desired: int
    ready: int
    available: int
    containers: tuple[tuple[str, str], ...]


def deployment_of(raw: object) -> Deployment:
    if not isinstance(raw, dict):
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    metadata, spec, status = raw.get("metadata"), raw.get("spec") or {}, raw.get("status") or {}
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not isinstance(name, str) or not _OBJECT_NAME.fullmatch(name) or not isinstance(spec, dict):
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    template = spec.get("template") or {}
    pod = template.get("spec") if isinstance(template, dict) else None
    raw_containers = pod.get("containers") if isinstance(pod, dict) else None
    containers = []
    for container in raw_containers if isinstance(raw_containers, list) else ():
        if not isinstance(container, dict):
            continue
        cname, image = container.get("name"), container.get("image")
        if isinstance(cname, str) and _OBJECT_NAME.fullmatch(cname) and isinstance(image, str) and _IMAGE.fullmatch(
            image
        ):
            containers.append((cname, image))
    status = status if isinstance(status, dict) else {}
    desired = spec.get("replicas")
    return Deployment(
        name=name,
        resource_version=str(metadata.get("resourceVersion") or ""),
        desired=_count(desired if desired is not None else 1),
        ready=_count(status.get("readyReplicas")),
        available=_count(status.get("availableReplicas")),
        containers=tuple(containers[:MAX_CONTAINERS]),
    )


def render_inventory(cluster: str, namespace: str, deployments: list[Deployment], *, truncated: bool) -> bytes:
    lines = [f"# Kubernetes inventory: namespace {namespace}", "", f"Cluster: {cluster}", "",
             f"## Deployments in {namespace} ({len(deployments)})", ""]
    if truncated:
        lines += [f"The cluster lists more deployments; only the first {MAX_DEPLOYMENTS} deployments are listed.", ""]
    lines += ["| Deployment | Desired replicas | Ready | Available | Containers (image) |", "|---|---|---|---|---|"]
    for item in sorted(deployments, key=lambda deployment: deployment.name):
        containers = ", ".join(f"{name} ({image})" for name, image in item.containers) or "-"
        lines.append(f"| {item.name} | {item.desired} | {item.ready} | {item.available} | {containers} |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def inventory_marker(deployments: list[Deployment], truncated: bool) -> str:
    digest = hashlib.sha256()
    for item in sorted(deployments, key=lambda deployment: deployment.name):
        digest.update(f"{item.name}\x00{item.resource_version}\n".encode())
    digest.update(b"truncated" if truncated else b"complete")
    return digest.hexdigest()[:40]


class KubernetesConnector:
    kind = CONNECTOR_KIND_KUBERNETES
    requires_parser = False

    def __init__(
        self,
        connection: KubernetesConnection,
        *,
        cluster: str,
        namespaces: tuple[str, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._connection = connection
        self._cluster = cluster
        self._namespaces = namespaces
        self._reader = SourceReader(connection, transport=transport)
        self._order: list[str] | None = None
        # namespace -> (deployments, truncated) of this run's listing; ``fetch`` renders from it.
        self._listed: dict[str, tuple[list[Deployment], bool]] = {}

    def _link(self, namespace: str) -> str:
        return f"{self._connection.base_url}/apis/apps/v1/namespaces/{namespace}/deployments"

    async def _namespace_order(self) -> list[str]:
        if self._order is not None:
            return self._order
        allowed = self._connection.allowed_namespaces
        if self._namespaces:
            wanted = [name for name in self._namespaces if allowed is None or name in allowed]
        elif allowed is not None:
            wanted = list(allowed)
        else:
            payload = await self._reader.get_json("/api/v1/namespaces", {"limit": MAX_NAMESPACES})
            wanted = []
            for raw in _items(payload):
                metadata = raw.get("metadata") if isinstance(raw, dict) else None
                name = metadata.get("name") if isinstance(metadata, dict) else None
                if not isinstance(name, str) or not NAMESPACE.fullmatch(name):
                    raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
                wanted.append(name)
        self._order = sorted(set(wanted))[:MAX_NAMESPACES]
        return self._order

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        try:
            start = int(token) if token is not None else 0
        except ValueError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
        order = await self._namespace_order()
        if start < 0 or start > len(order):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        page = order[start : start + limit]
        items = []
        for namespace in page:
            try:
                # The API has no field selection: every deployment arrives with its full pod template, held in
                # memory only while this page is reduced by deployment_of.
                payload = await self._reader.get_json(
                    f"/apis/apps/v1/namespaces/{namespace}/deployments", {"limit": MAX_DEPLOYMENTS}
                )
            except ConnectorError as error:
                if error.reason == REASON_SOURCE_NOT_FOUND:
                    continue  # the namespace is gone: not listed, so the completed pass retires it
                raise
            deployments = [deployment_of(raw) for raw in _items(payload)][:MAX_DEPLOYMENTS]
            truncated = _truncated(payload) or len(_items(payload)) > MAX_DEPLOYMENTS
            self._listed[namespace] = (deployments, truncated)
            items.append(SourceItem(
                # The connector kind (``kubernetes.`` source keys) selects these for the operations layer.
                namespace, f"Namespace {namespace} on {self._cluster}", self._link(namespace),
                inventory_marker(deployments, truncated), AclFacet.scope(),
            ))
        end = start + len(page)
        return ListingPage(items=tuple(items), next_token=str(end) if end < len(order) else None)

    async def fetch(self, item: SourceItem) -> ItemContent:
        listed = self._listed.get(item.external_id)
        if listed is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        deployments, truncated = listed
        data = render_inventory(self._cluster, item.external_id, deployments, truncated=truncated)
        return ItemContent(data=data, media_type="text/markdown")

    async def expand_acl(self, acl: AclFacet) -> None:
        return None


__all__ = [
    "MAX_DEPLOYMENTS",
    "MAX_NAMESPACES",
    "KubernetesConnector",
    "deployment_of",
    "inventory_marker",
    "render_inventory",
]
