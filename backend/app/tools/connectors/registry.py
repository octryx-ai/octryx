"""Docker registry and Harbor connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_CONTAINER_REGISTRY

from ..context import ToolContext
from .common import (
    _headers_with_basic,
    _limit,
    _normalize_string_list,
    _string,
    connection_http_json,
    connection_http_response,
)

#: This module's HTTP helpers use the container_registry egress rule.
_http_json = connection_http_json(CONNECTION_CONTAINER_REGISTRY)
_http_response = connection_http_response(CONNECTION_CONTAINER_REGISTRY)


def _docker_registry_provider(context: ToolContext, params: dict[str, Any]) -> str:
    explicit = _string(params.get("provider") or context.project_config.get("docker_registry_provider")).lower()
    if explicit in {"registry", "harbor"}:
        return explicit
    if _string(context.project_config.get("harbor_project")):
        return "harbor"
    return "registry"


def _docker_registry_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("docker_registry_url")).rstrip("/")


def _docker_registry_headers(context: ToolContext, *, accept_manifest: bool = False) -> dict[str, str]:
    username = _string(context.project_config.get("docker_registry_username"))
    password = _string(
        context.project_config.get("docker_registry_password") or context.project_config.get("docker_registry_token")
    )
    extra = {"Accept": "application/json"}
    if accept_manifest:
        extra["Accept"] = ", ".join(
            [
                "application/vnd.docker.distribution.manifest.v2+json",
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
            ]
        )
    return _headers_with_basic(username or None, password or None, extra=extra)


def _docker_registry_repository(context: ToolContext, params: dict[str, Any]) -> str:
    repository = _string(params.get("repository") or params.get("repo"))
    allowed = _normalize_string_list(context.project_config.get("docker_registry_allowed_repositories"))
    if not repository and len(allowed) == 1:
        repository = allowed[0]
    if not repository:
        raise ValueError("repository is required")
    if allowed and repository not in allowed:
        raise ValueError("repository is not allowed")
    return repository


def _docker_registry_harbor_project(context: ToolContext, params: dict[str, Any]) -> str:
    project = _string(params.get("project") or context.project_config.get("harbor_project"))
    if not project:
        raise ValueError("project is required for Harbor mode")
    return project


class ListDockerRegistryRepositoriesTool:
    name = "list_repositories"
    description = "List repositories from a Docker Registry or Harbor."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _docker_registry_base_url(context)
        if not base:
            return {"error": "docker_registry_url is required"}
        limit = _limit(context, params, default=20, maximum=100)
        provider = _docker_registry_provider(context, params)
        try:
            if provider == "harbor":
                project = _docker_registry_harbor_project(context, params)
                data = await _http_json(
                    "GET",
                    f"{base}/api/v2.0/projects/{quote(project, safe='')}/repositories",
                    headers=_docker_registry_headers(context),
                    params={"page_size": limit},
                )
                items = data if isinstance(data, list) else []
                repositories = [
                    {
                        "name": item.get("name"),
                        "pull_count": item.get("pull_count"),
                        "artifact_count": item.get("artifact_count"),
                        "project_id": item.get("project_id"),
                    }
                    for item in items
                ]
            else:
                data = await _http_json(
                    "GET", f"{base}/v2/_catalog", headers=_docker_registry_headers(context), params={"n": limit}
                )
                repositories = [{"name": item} for item in (data.get("repositories") or [])]
            allowed = _normalize_string_list(context.project_config.get("docker_registry_allowed_repositories"))
            if allowed:
                repositories = [item for item in repositories if _string(item.get("name")) in allowed]
            return {"provider": provider, "count": len(repositories), "repositories": repositories[:limit]}
        except Exception as exc:
            return {"error": str(exc)}


class ListDockerRegistryTagsTool:
    name = "list_tags"
    description = "List tags for an allowed Docker Registry or Harbor repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _docker_registry_base_url(context)
        if not base:
            return {"error": "docker_registry_url is required"}
        try:
            repository = _docker_registry_repository(context, params)
            data = await _http_json(
                "GET",
                f"{base}/v2/{quote(repository, safe='/')}/tags/list",
                headers=_docker_registry_headers(context),
                params={"n": _limit(context, params, default=50, maximum=200)},
            )
        except Exception as exc:
            return {"error": str(exc)}
        tags = data.get("tags") or []
        return {"repository": repository, "count": len(tags), "tags": tags}


class GetRegistryImageVulnerabilitiesTool:
    name = "get_image_vulnerabilities"
    description = "Get image vulnerability information from Harbor."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _docker_registry_base_url(context)
        if not base:
            return {"error": "docker_registry_url is required"}
        provider = _docker_registry_provider(context, params)
        if provider != "harbor":
            return {"error": "get_image_vulnerabilities is only supported in Harbor mode"}
        try:
            project = _docker_registry_harbor_project(context, params)
            repository = _docker_registry_repository(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        reference = _string(params.get("reference") or params.get("tag") or params.get("digest"))
        if not reference:
            return {"error": "tag or digest is required"}
        try:
            data = await _http_json(
                "GET",
                f"{base}/api/v2.0/projects/{quote(project, safe='')}/repositories/{quote(repository, safe='')}/artifacts/{quote(reference, safe='')}/additions/vulnerabilities",
                headers=_docker_registry_headers(context),
            )
        except Exception as exc:
            return {"error": str(exc)}
        vulnerabilities = data if isinstance(data, list) else data.get("vulnerabilities") or []
        return {
            "repository": repository,
            "reference": reference,
            "count": len(vulnerabilities),
            "vulnerabilities": vulnerabilities,
        }


class DeleteRegistryTagTool:
    name = "delete_tag"
    description = "Delete a tag from an allowed Docker Registry or Harbor repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _docker_registry_base_url(context)
        if not base:
            return {"error": "docker_registry_url is required"}
        try:
            repository = _docker_registry_repository(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        tag = _string(params.get("tag"))
        if not tag:
            return {"error": "tag is required"}
        try:
            manifest_response = await _http_response(
                "HEAD",
                f"{base}/v2/{quote(repository, safe='/')}/manifests/{quote(tag, safe='')}",
                headers=_docker_registry_headers(context, accept_manifest=True),
            )
            if manifest_response.status_code == 405:
                manifest_response = await _http_response(
                    "GET",
                    f"{base}/v2/{quote(repository, safe='/')}/manifests/{quote(tag, safe='')}",
                    headers=_docker_registry_headers(context, accept_manifest=True),
                )
            manifest_response.raise_for_status()
            digest = manifest_response.headers.get("Docker-Content-Digest") or manifest_response.headers.get(
                "docker-content-digest"
            )
            if not digest:
                return {"error": "registry did not return Docker-Content-Digest for the tag"}
            delete_response = await _http_response(
                "DELETE",
                f"{base}/v2/{quote(repository, safe='/')}/manifests/{quote(digest, safe=':')}",
                headers=_docker_registry_headers(context, accept_manifest=True),
            )
            delete_response.raise_for_status()
        except Exception as exc:
            return {"error": str(exc)}
        return {"status": "deleted", "repository": repository, "tag": tag, "digest": digest}
