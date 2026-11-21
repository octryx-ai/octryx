"""CI log and test-result connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITHUB, CONNECTION_GITLAB
from ..context import ToolContext
from .azure_devops import _azure_devops_base_url, _azure_devops_headers, _resolve_azure_devops_project
from .common import _http_json, _http_text, _limit, _string
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project


def _ci_provider(context: ToolContext, params: dict[str, Any]) -> str:
    explicit = _string(params.get("provider")).lower()
    if explicit in {"github", "gitlab", "azure_devops"}:
        return explicit
    if _string(
        context.project_config.get("azure_devops_url")
        or context.project_config.get("azure_devops_pat")
        or context.project_config.get("azure_devops_project")
    ):
        return "azure_devops"
    if _string(
        context.project_config.get("gitlab_url")
        or context.project_config.get("gitlab_token")
        or context.project_config.get("gitlab_token_secret_ref")
        or context.project_config.get("gitlab_group")
    ):
        return "gitlab"
    if _string(
        context.project_config.get("github_url")
        or context.project_config.get("github_token")
        or context.project_config.get("github_token_secret_ref")
        or context.project_config.get("github_owner")
    ):
        return "github"
    return ""


class GetCiJobLogsTool:
    name = "get_job_logs"
    description = "Get raw job logs from GitHub Actions or GitLab CI."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _ci_provider(context, params)
        timeout = int(params.get("timeout_sec") or 30)
        if provider == "github":
            owner, repo = _resolve_github_repo(context, params)
            if not owner or not repo:
                return {"error": "repository is required and must be allowed"}
            job_id = _string(params.get("job_id"))
            if not job_id:
                return {"error": "job_id is required"}
            logs = await _http_text(
                "GET",
                f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
                connection=CONNECTION_GITHUB,
                headers=await _github_headers(context),
                timeout=timeout,
            )
            return {"provider": provider, "repository": f"{owner}/{repo}", "job_id": job_id, "logs": logs[:50000]}
        if provider == "gitlab":
            project = _resolve_gitlab_project(context, params)
            if not project:
                return {"error": "project is required and must be allowed"}
            job_id = _string(params.get("job_id"))
            if not job_id:
                return {"error": "job_id is required"}
            logs = await _http_text(
                "GET",
                f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/jobs/{quote(job_id, safe='')}/trace",
                connection=CONNECTION_GITLAB,
                headers=await _gitlab_headers(context),
                timeout=timeout,
            )
            return {"provider": provider, "project": project, "job_id": job_id, "logs": logs[:50000]}
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}


async def _github_pipeline_logs(
    context: ToolContext, params: dict, *, timeout: int, max_jobs: int
) -> dict[str, Any]:
    owner, repo = _resolve_github_repo(context, params)
    run_id = _string(params.get("run_id") or params.get("pipeline_id"))
    if not owner or not repo or not run_id:
        return {"error": "repository and run_id are required"}
    jobs_payload = await _http_json(
        "GET",
        f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
        connection=CONNECTION_GITHUB,
        headers=await _github_headers(context),
        params={"per_page": max_jobs},
        timeout=timeout,
    )
    jobs = jobs_payload.get("jobs") or []
    entries: list[dict[str, Any]] = []
    for job in jobs[:max_jobs]:
        job_id = _string(job.get("id"))
        logs = await _http_text(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            connection=CONNECTION_GITHUB,
            headers=await _github_headers(context),
            timeout=timeout,
        )
        entries.append({"job_id": job_id, "name": job.get("name"), "logs": logs[:20000]})
    return {"provider": "github", "repository": f"{owner}/{repo}", "run_id": run_id, "job_logs": entries}


async def _gitlab_pipeline_logs(
    context: ToolContext, params: dict, *, timeout: int, max_jobs: int
) -> dict[str, Any]:
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
        params={"per_page": max_jobs},
        timeout=timeout,
    )
    entries: list[dict[str, Any]] = []
    for job in jobs[:max_jobs]:
        job_id = _string(job.get("id"))
        logs = await _http_text(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/jobs/{quote(job_id, safe='')}/trace",
            connection=CONNECTION_GITLAB,
            headers=await _gitlab_headers(context),
            timeout=timeout,
        )
        entries.append({"job_id": job_id, "name": job.get("name"), "logs": logs[:20000]})
    return {"provider": "gitlab", "project": project, "pipeline_id": pipeline_id, "job_logs": entries}


async def _azure_devops_pipeline_logs(
    context: ToolContext, params: dict, *, timeout: int, max_jobs: int
) -> dict[str, Any]:
    project = _resolve_azure_devops_project(context, params)
    pipeline_id = _string(params.get("pipeline_id"))
    run_id = _string(params.get("run_id"))
    if not project or not pipeline_id or not run_id:
        return {"error": "project, pipeline_id and run_id are required"}
    run_path = f"{quote(project, safe='')}/_apis/pipelines/{quote(pipeline_id, safe='')}/runs/{quote(run_id, safe='')}"
    logs_payload = await _http_json(
        "GET",
        f"{_azure_devops_base_url(context)}/{run_path}/logs",
        headers=_azure_devops_headers(context),
        params={"api-version": "7.1-preview.1"},
        timeout=timeout,
    )
    entries: list[dict[str, Any]] = []
    for item in (logs_payload.get("value") or [])[:max_jobs]:
        log_id = _string(item.get("id"))
        log_url = _string(item.get("url"))
        if not log_id or not log_url:
            continue
        logs = await _http_text("GET", log_url, headers=_azure_devops_headers(context), timeout=timeout)
        entries.append({"job_id": log_id, "name": item.get("name") or f"log-{log_id}", "logs": logs[:20000]})
    return {
        "provider": "azure_devops",
        "project": project,
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "job_logs": entries,
    }


_PIPELINE_LOG_READERS = {
    "github": _github_pipeline_logs,
    "gitlab": _gitlab_pipeline_logs,
    "azure_devops": _azure_devops_pipeline_logs,
}


class GetCiPipelineLogsTool:
    name = "get_pipeline_logs"
    description = "Aggregate job logs of a GitHub Actions workflow run, GitLab pipeline or Azure DevOps pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _ci_provider(context, params)
        timeout = int(params.get("timeout_sec") or 30)
        max_jobs = _limit(context, params, default=5, maximum=20)
        reader = _PIPELINE_LOG_READERS.get(provider)
        if reader is None:
            return {"error": "No GitHub, GitLab or Azure DevOps CI connector is configured for this project"}
        return await reader(context, params, timeout=timeout, max_jobs=max_jobs)


async def _github_test_results(context: ToolContext, params: dict) -> dict[str, Any]:
    owner, repo = _resolve_github_repo(context, params)
    run_id = _string(params.get("run_id") or params.get("pipeline_id"))
    if not owner or not repo or not run_id:
        return {"error": "repository and run_id are required"}
    data = await _http_json(
        "GET",
        f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
        connection=CONNECTION_GITHUB,
        headers=await _github_headers(context),
        params={"per_page": _limit(context, params, default=50, maximum=100)},
    )
    jobs = data.get("jobs") or []
    summary: dict[str, int] = {}
    for job in jobs:
        key = _string(job.get("conclusion") or job.get("status") or "unknown")
        summary[key] = summary.get(key, 0) + 1
    answer: dict[str, Any] = {
        "provider": "github",
        "repository": f"{owner}/{repo}",
        "run_id": run_id,
        "job_count": len(jobs),
        "summary": summary,
    }
    if params.get("include_cases") is True:
        from .ci_test_reports import github_junit_reports

        # The JUnit files of the run's test-report artifacts: the per-test results (GitHub has no test API).
        answer["junit_reports"] = await github_junit_reports(
            context, owner, repo, run_id, _string(params.get("artifact")))
    return answer


async def _gitlab_test_results(context: ToolContext, params: dict) -> dict[str, Any]:
    project = _resolve_gitlab_project(context, params)
    pipeline_id = _string(params.get("pipeline_id") or params.get("run_id"))
    if not project or not pipeline_id:
        return {"error": "project and pipeline_id are required"}
    if params.get("include_cases") is True:
        from .ci_test_reports import gitlab_test_cases

        cases = await gitlab_test_cases(context, project, pipeline_id)
        return {"provider": "gitlab", "project": project, "pipeline_id": pipeline_id, "cases": cases}
    project_url = f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}"
    pipeline_url = f"{project_url}/pipelines/{quote(pipeline_id, safe='')}"
    try:
        data = await _http_json(
            "GET",
            f"{pipeline_url}/test_report_summary",
            connection=CONNECTION_GITLAB,
            headers=await _gitlab_headers(context),
        )
        return {"provider": "gitlab", "project": project, "pipeline_id": pipeline_id, "summary": data}
    except Exception:
        jobs = await _http_json(
            "GET",
            f"{pipeline_url}/jobs",
            connection=CONNECTION_GITLAB,
            headers=await _gitlab_headers(context),
            params={"per_page": _limit(context, params, default=50, maximum=100)},
        )
        summary: dict[str, int] = {}
        for job in jobs:
            key = _string(job.get("status") or "unknown")
            summary[key] = summary.get(key, 0) + 1
        return {"provider": "gitlab", "project": project, "pipeline_id": pipeline_id, "summary": summary}


class GetCiTestResultsTool:
    name = "get_test_results"
    description = "Summarize test results for a GitHub Actions workflow run or GitLab pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _ci_provider(context, params)
        if provider == "github":
            return await _github_test_results(context, params)
        if provider == "gitlab":
            return await _gitlab_test_results(context, params)
        return {"error": "No GitHub or GitLab CI connector is configured for this project"}
