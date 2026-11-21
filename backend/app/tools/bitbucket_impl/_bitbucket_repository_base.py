"""Bitbucket repository metadata and file listing tools."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_BITBUCKET, egress_transport
from app.tools.context import ToolContext

from ..evidence_fields import with_source
from . import _bitbucket_internal_network
from ._bitbucket_cloud import cloud_context
from ._bitbucket_evidence import file_url, with_entry_source, with_repo_source
from ._bitbucket_internal_core import (
    _bitbucket_base_url,
    _bitbucket_http_auth,
    _is_repo_allowed,
    _normalize_allowed_repos,
)


class ListBitbucketRepositories:
    name = "list_bitbucket_repositories"
    description = "List the Bitbucket repositories explicitly allowed for the current project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        repos = _normalize_allowed_repos(context.project_config)
        base_url = _bitbucket_base_url(context)
        return {
            # Each repository names its browse page on the configured Bitbucket (evidence fields).
            "repositories": [
                with_repo_source(
                    {
                        "project_key": repo["project_key"],
                        "repo_slug": repo["repo_slug"],
                        "enabled": bool(repo.get("enabled", True)),
                        "label": repo.get("label") or f"{repo['project_key']}/{repo['repo_slug']}",
                    },
                    base_url,
                )
                for repo in repos
                if repo.get("enabled", True)
            ]
        }


class ReadBitbucketFile:
    name = "read_bitbucket_file"
    description = "Read a file from an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ._bitbucket_internal_core import _truncate

        bitbucket_url = _bitbucket_base_url(context)
        if not bitbucket_url:
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        path = str(params.get("path") or "").lstrip("/")
        ref = str(params.get("ref") or "").strip()
        if not project_key or not repo_slug or not path:
            return {"error": "project_key, repo_slug and path are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
        if cloud_context(context):  # its own client would send the Cloud token to a Server REST path
            return {"error": "This Bitbucket operation is not available for Bitbucket Cloud connections yet."}

        auth = await _bitbucket_http_auth(context)
        headers = {"Accept": "text/plain, */*"}
        request_kwargs: dict[str, Any] = {"headers": headers}
        if auth:
            request_kwargs["auth"] = auth
        if ref:
            request_kwargs["params"] = {"at": ref}

        async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)) as client:
            response = await client.get(
                f"{bitbucket_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/raw/{path}",
                **request_kwargs,
            )
            response.raise_for_status()

        result = {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "path": path,
            "ref": ref or None,
            "content": _truncate(response.text),
        }
        # The file's browse page (at the read ref) on the configured Bitbucket (evidence fields).
        url = file_url(bitbucket_url, project_key, repo_slug, path, ref or None)
        return with_source(result, title=f"{project_key}/{repo_slug}: {path}", url=url)


class ListBitbucketDirectory:
    name = "list_bitbucket_directory"
    description = "List files and directories inside an allowed Bitbucket repository path."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        bitbucket_url = _bitbucket_base_url(context)
        if not bitbucket_url:
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        path = str(params.get("path") or "").strip().strip("/")
        ref = str(params.get("ref") or "").strip()
        if not project_key or not repo_slug:
            return {"error": "project_key and repo_slug are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        request_params: dict[str, Any] = {}
        if ref:
            request_params["at"] = ref
        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/browse{'/' + path if path else ''}",
            params=request_params,
        )

        children = payload.get("children", {}).get("values", [])
        return {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "path": path or "",
            "ref": ref or None,
            # Each entry names its browse page on the configured Bitbucket (evidence fields).
            "entries": [
                with_entry_source(
                    {
                        "path": "/".join(part for part in (path, "/".join(entry.get("path", {}).get("components", []))) if part),
                        "type": entry.get("type"),
                    },
                    bitbucket_url,
                    project_key,
                    repo_slug,
                    ref or None,
                )
                for entry in children
            ],
        }
