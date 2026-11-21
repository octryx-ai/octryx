"""CI workflow-control and artifact connector tools."""

from __future__ import annotations

from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITHUB, CONNECTION_GITLAB
from ..context import ToolContext
from .ci_logs import _ci_provider
from .common import _http_json, _limit, _string
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project


class TriggerCiWorkflowTool:
    name = "trigger_workflow"
    description = "Trigger a GitHub Actions workflow or a GitLab pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        provider = _ci_provider(context, params)
        if provider == "github":
            owner, repo = _resolve_github_repo(context, params)
            workflow_id = _string(params.get("workflow_id"))
            ref = _string(params.get("ref") or params.get("branch"))
            if not owner or not repo or not workflow_id or not ref:
                return {"error": "repository, workflow_id and ref are required"}
            await _http_json(
                "POST",
                f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/workflows/{quote(workflow_id, safe='')}/dispatches",
                connection=CONNECTION_GITHUB,
                headers={**await _github_headers(context), "Content-Type": "application/json"},
                json_body={
                    "ref": ref,
                    "inputs": params.get("inputs") if isinstance(params.get("inputs"), dict) else {},
                },
            )
            return {
                "provider": provider,
                "repository": f"{owner}/{repo}",
                "workflow_id": workflow_id,
                "status": "triggered",
            }
        if provider == "gitlab":
            project = _resolve_gitlab_project(context, params)
            ref = _string(params.get("ref") or params.get("branch"))
            if not project or not ref:
                return {"error": "project and ref are required"}
            data = await _http_json(
                "POST",
                f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/pipeline",
                connection=CONNECTION_GITLAB,
                headers={**await _gitlab_headers(context), "Content-Type": "application/json"},
                json_body={
                    "ref": ref,
                    "variables": params.get("variables") if isinstance(params.get("variables"), list) else [],
                },
            )
            return {"provider": provider, "project": project, "pipeline_id": data.get("id"), "status": "triggered"}
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}


class RetryCiJobTool:
    name = "retry_job"
    description = "Retry a failed GitHub Actions job or GitLab CI job."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        provider = _ci_provider(context, params)
        job_id = _string(params.get("job_id"))
        if not job_id:
            return {"error": "job_id is required"}
        if provider == "github":
            owner, repo = _resolve_github_repo(context, params)
            if not owner or not repo:
                return {"error": "repository is required and must be allowed"}
            await _http_json(
                "POST",
                f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/jobs/{quote(job_id, safe='')}/rerun",
                connection=CONNECTION_GITHUB,
                headers=await _github_headers(context),
            )
            return {"provider": provider, "repository": f"{owner}/{repo}", "job_id": job_id, "status": "retried"}
        if provider == "gitlab":
            project = _resolve_gitlab_project(context, params)
            if not project:
                return {"error": "project is required and must be allowed"}
            data = await _http_json(
                "POST",
                f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/jobs/{quote(job_id, safe='')}/retry",
                connection=CONNECTION_GITLAB,
                headers=await _gitlab_headers(context),
            )
            return {"provider": provider, "project": project, "job_id": data.get("id") or job_id, "status": "retried"}
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}


class CancelCiPipelineTool:
    name = "cancel_pipeline"
    description = "Cancel a GitHub Actions workflow run or GitLab pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        provider = _ci_provider(context, params)
        pipeline_id = _string(params.get("pipeline_id") or params.get("run_id"))
        if not pipeline_id:
            return {"error": "pipeline_id or run_id is required"}
        if provider == "github":
            owner, repo = _resolve_github_repo(context, params)
            if not owner or not repo:
                return {"error": "repository is required and must be allowed"}
            await _http_json(
                "POST",
                f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/runs/{quote(pipeline_id, safe='')}/cancel",
                connection=CONNECTION_GITHUB,
                headers=await _github_headers(context),
            )
            return {"provider": provider, "repository": f"{owner}/{repo}", "run_id": pipeline_id, "status": "cancelled"}
        if provider == "gitlab":
            project = _resolve_gitlab_project(context, params)
            if not project:
                return {"error": "project is required and must be allowed"}
            data = await _http_json(
                "POST",
                f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/pipelines/{quote(pipeline_id, safe='')}/cancel",
                connection=CONNECTION_GITLAB,
                headers=await _gitlab_headers(context),
            )
            return {
                "provider": provider,
                "project": project,
                "pipeline_id": data.get("id") or pipeline_id,
                "status": "cancelled",
            }
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}


async def _github_artifacts(context: ToolContext, params: dict) -> dict[str, object]:
    owner, repo = _resolve_github_repo(context, params)
    run_id = _string(params.get("run_id") or params.get("pipeline_id"))
    if not owner or not repo or not run_id:
        return {"error": "repository and run_id are required"}
    data = await _http_json(
        "GET",
        f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/runs/{quote(run_id, safe='')}/artifacts",
        connection=CONNECTION_GITHUB,
        headers=await _github_headers(context),
        params={"per_page": _limit(context, params, default=20, maximum=100)},
    )
    artifacts = data.get("artifacts") or []
    return {
        "provider": "github",
        "repository": f"{owner}/{repo}",
        "run_id": run_id,
        "count": len(artifacts),
        "artifacts": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "size_in_bytes": item.get("size_in_bytes"),
                "expired": item.get("expired"),
                "created_at": item.get("created_at"),
            }
            for item in artifacts
        ],
    }


async def _gitlab_artifacts(context: ToolContext, params: dict) -> dict[str, object]:
    project = _resolve_gitlab_project(context, params)
    pipeline_id = _string(params.get("pipeline_id") or params.get("run_id"))
    if not project or not pipeline_id:
        return {"error": "project and pipeline_id are required"}
    project_url = f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}"
    jobs = await _http_json(
        "GET",
        f"{project_url}/pipelines/{quote(pipeline_id, safe='')}/jobs",
        connection=CONNECTION_GITLAB,
        headers=await _gitlab_headers(context),
        params={"per_page": _limit(context, params, default=50, maximum=100)},
    )
    artifacts = [
        {
            "job_id": item.get("id"),
            "name": ((item.get("artifacts_file") or {}).get("filename")) or item.get("name"),
            "size_in_bytes": ((item.get("artifacts_file") or {}).get("size")),
            "download_url": f"{project_url}/jobs/{item.get('id')}/artifacts",
        }
        for item in jobs
        if item.get("artifacts_file")
    ]
    return {
        "provider": "gitlab",
        "project": project,
        "pipeline_id": pipeline_id,
        "count": len(artifacts),
        "artifacts": artifacts,
    }


class ListCiArtifactsTool:
    name = "list_artifacts"
    description = "List artifacts of a GitHub Actions workflow run or GitLab pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        provider = _ci_provider(context, params)
        if provider == "github":
            return await _github_artifacts(context, params)
        if provider == "gitlab":
            return await _gitlab_artifacts(context, params)
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}


class GetCiArtifactTool:
    name = "get_artifact"
    description = "Get metadata or download details for a GitHub Actions or GitLab CI artifact."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        provider = _ci_provider(context, params)
        if provider == "github":
            owner, repo = _resolve_github_repo(context, params)
            artifact_id = _string(params.get("artifact_id"))
            if not owner or not repo or not artifact_id:
                return {"error": "repository and artifact_id are required"}
            data = await _http_json(
                "GET",
                f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/artifacts/{quote(artifact_id, safe='')}",
                connection=CONNECTION_GITHUB,
                headers=await _github_headers(context),
            )
            artifact = data.get("artifact") or data
            return {
                "provider": provider,
                "repository": f"{owner}/{repo}",
                "artifact": {
                    "id": artifact.get("id"),
                    "name": artifact.get("name"),
                    "size_in_bytes": artifact.get("size_in_bytes"),
                    "expired": artifact.get("expired"),
                    "download_url": artifact.get("archive_download_url"),
                },
            }
        if provider == "gitlab":
            project = _resolve_gitlab_project(context, params)
            job_id = _string(params.get("job_id") or params.get("artifact_id"))
            if not project or not job_id:
                return {"error": "project and job_id are required"}
            data = await _http_json(
                "GET",
                f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/jobs/{quote(job_id, safe='')}",
                connection=CONNECTION_GITLAB,
                headers=await _gitlab_headers(context),
            )
            artifact_file = data.get("artifacts_file") or {}
            return {
                "provider": provider,
                "project": project,
                "artifact": {
                    "job_id": data.get("id") or job_id,
                    "name": artifact_file.get("filename") or data.get("name"),
                    "size_in_bytes": artifact_file.get("size"),
                    "download_url": f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/jobs/{quote(job_id, safe='')}/artifacts",
                },
            }
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}
