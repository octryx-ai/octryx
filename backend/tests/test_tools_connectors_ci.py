"""GitHub and GitLab CI tools: logs, trigger, retry, cancel, artifacts and test reports."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool


async def _github_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
    assert headers["Authorization"] == "Bearer gh-token"
    if method == "GET" and url == "https://api.github.com/repos/example/octryx/actions/runs/77/jobs":
        return {
            "jobs": [
                {"id": 101, "name": "unit", "status": "completed", "conclusion": "success"},
                {"id": 102, "name": "lint", "status": "completed", "conclusion": "failure"},
            ]
        }
    if (
        method == "POST"
        and url == "https://api.github.com/repos/example/octryx/actions/workflows/ci.yml/dispatches"
    ):
        assert json_body == {"ref": "main", "inputs": {"deploy_env": "prod"}}
        return {}
    if method == "POST" and url == "https://api.github.com/repos/example/octryx/actions/jobs/101/rerun":
        return {}
    if method == "POST" and url == "https://api.github.com/repos/example/octryx/actions/runs/77/cancel":
        return {}
    if method == "GET" and url == "https://api.github.com/repos/example/octryx/actions/runs/77/artifacts":
        return {
            "artifacts": [
                {
                    "id": 501,
                    "name": "reports",
                    "size_in_bytes": 2048,
                    "expired": False,
                    "created_at": "2026-04-01T10:00:00Z",
                }
            ]
        }
    if method == "GET" and url == "https://api.github.com/repos/example/octryx/actions/artifacts/501":
        return {
            "artifact": {
                "id": 501,
                "name": "reports",
                "size_in_bytes": 2048,
                "expired": False,
                "archive_download_url": "https://downloads.example/reports.zip",
            }
        }
    raise AssertionError(f"unexpected json call {method} {url}")


async def _github_http_text(method, url, *, headers=None, timeout=30, connection=None):
    assert headers["Authorization"] == "Bearer gh-token"
    if url == "https://api.github.com/repos/example/octryx/actions/jobs/101/logs":
        return "job-101 logs"
    if url == "https://api.github.com/repos/example/octryx/actions/jobs/102/logs":
        return "job-102 logs"
    raise AssertionError(f"unexpected text call {method} {url}")


def _github_context():
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "github_token": "gh-token",
            "github_allowed_repositories": ["example/octryx"],
            "tool_policy": {"high_risk_grants": ["trigger_workflow", "retry_job", "cancel_pipeline"]},
        },
    )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_github_ci_tools_cover_logs_trigger_retry_cancel_artifacts_and_tests(monkeypatch):
    for module in ("ci_artifacts", "ci_logs", "ci_test_reports"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", _github_http_json)
    monkeypatch.setattr("app.tools.connectors.ci_logs._http_text", _github_http_text)

    context = _github_context()

    job_logs = await execute_tool("get_job_logs", {"job_id": 101}, context)
    assert job_logs["provider"] == "github"
    assert "job-101 logs" in job_logs["logs"]

    pipeline_logs = await execute_tool("get_pipeline_logs", {"run_id": 77}, context)
    assert pipeline_logs["provider"] == "github"
    assert len(pipeline_logs["job_logs"]) == 2

    triggered = await execute_tool(
        "trigger_workflow",
        {"workflow_id": "ci.yml", "ref": "main", "inputs": {"deploy_env": "prod"}},
        context,
    )
    assert triggered["status"] == "triggered"

    retried = await execute_tool("retry_job", {"job_id": 101}, context)
    assert retried["status"] == "retried"

    cancelled = await execute_tool("cancel_pipeline", {"run_id": 77}, context)
    assert cancelled["status"] == "cancelled"

    artifacts = await execute_tool("list_artifacts", {"run_id": 77}, context)
    assert artifacts["count"] == 1
    assert artifacts["artifacts"][0]["id"] == 501

    artifact = await execute_tool("get_artifact", {"artifact_id": 501}, context)
    assert artifact["artifact"]["download_url"] == "https://downloads.example/reports.zip"

    test_results = await execute_tool("get_test_results", {"run_id": 77}, context)
    assert test_results["summary"] == {"success": 1, "failure": 1}


async def _gitlab_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
    assert headers["PRIVATE-TOKEN"] == "gl-token"
    if (
        method == "GET"
        and url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/pipelines/88/jobs"
    ):
        return [
            {
                "id": 201,
                "name": "test",
                "status": "failed",
                "artifacts_file": {"filename": "junit.xml", "size": 1234},
            },
            {
                "id": 202,
                "name": "build",
                "status": "success",
                "artifacts_file": {"filename": "build.zip", "size": 4321},
            },
        ]
    if method == "POST" and url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/pipeline":
        assert json_body == {"ref": "main", "variables": [{"key": "ENV", "value": "prod"}]}
        return {"id": 88}
    if (
        method == "POST"
        and url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/jobs/201/retry"
    ):
        return {"id": 201}
    if (
        method == "POST"
        and url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/pipelines/88/cancel"
    ):
        return {"id": 88}
    if method == "GET" and url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/jobs/201":
        return {
            "id": 201,
            "name": "test",
            "artifacts_file": {"filename": "junit.xml", "size": 1234},
        }
    if (
        method == "GET"
        and url
        == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/pipelines/88/test_report_summary"
    ):
        return {"total": {"count": 12, "success": 11, "failed": 1}}
    raise AssertionError(f"unexpected json call {method} {url}")


async def _gitlab_http_text(method, url, *, headers=None, timeout=30, connection=None):
    assert headers["PRIVATE-TOKEN"] == "gl-token"
    if url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/jobs/201/trace":
        return "job-201 logs"
    if url == "https://gitlab.example.com/api/v4/projects/acme-orders%2Fshop/jobs/202/trace":
        return "job-202 logs"
    raise AssertionError(f"unexpected text call {method} {url}")


def _gitlab_context():
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_token": "gl-token",
            "gitlab_allowed_projects": ["acme-orders/shop"],
            "tool_policy": {"high_risk_grants": ["trigger_workflow", "retry_job", "cancel_pipeline"]},
        },
    )


def _gitlab_args(**extra):
    return {"provider": "gitlab", "project": "acme-orders/shop", **extra}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_gitlab_ci_tools_cover_logs_trigger_retry_cancel_artifacts_and_tests(monkeypatch):
    for module in ("ci_artifacts", "ci_logs", "ci_test_reports"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", _gitlab_http_json)
    monkeypatch.setattr("app.tools.connectors.ci_logs._http_text", _gitlab_http_text)

    context = _gitlab_context()

    job_logs = await execute_tool("get_job_logs", _gitlab_args(job_id=201), context)
    assert job_logs["provider"] == "gitlab"
    assert "job-201 logs" in job_logs["logs"]

    pipeline_logs = await execute_tool("get_pipeline_logs", _gitlab_args(pipeline_id=88), context)
    assert pipeline_logs["provider"] == "gitlab"
    assert len(pipeline_logs["job_logs"]) == 2

    triggered = await execute_tool(
        "trigger_workflow",
        _gitlab_args(ref="main", variables=[{"key": "ENV", "value": "prod"}]),
        context,
    )
    assert triggered["status"] == "triggered"
    assert triggered["pipeline_id"] == 88

    retried = await execute_tool("retry_job", _gitlab_args(job_id=201), context)
    assert retried["status"] == "retried"

    cancelled = await execute_tool("cancel_pipeline", _gitlab_args(pipeline_id=88), context)
    assert cancelled["status"] == "cancelled"

    artifacts = await execute_tool("list_artifacts", _gitlab_args(pipeline_id=88), context)
    assert artifacts["count"] == 2

    artifact = await execute_tool("get_artifact", _gitlab_args(job_id=201), context)
    assert artifact["artifact"]["name"] == "junit.xml"

    test_results = await execute_tool("get_test_results", _gitlab_args(pipeline_id=88), context)
    assert test_results["summary"]["total"]["failed"] == 1
