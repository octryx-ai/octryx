"""A CI/CD provider's pipeline trace webhook normalizes stages, failure context and the failure taxonomy."""

from __future__ import annotations

from sqlalchemy import select

from app.models import WorkCicdPipelineTrace
from tests.secure_work_cicd_providers_support import _create_provider, _work_item


async def test_pipeline_trace_normalizes_stages_and_failure_context(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(source_key="OCX-337", title="Normalize pipeline traces")
    db.add(item)
    await db.commit()
    long_log = (
        "Checking out branch\n"
        "token=plain-secret-should-not-leak\n"
        "Running compile\n"
        + ("maven compiler failure at SourceFile.java:42\n" * 180)
    )

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-pipeline-traces",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "provider_type": "jenkins",
            "job_name": "acme-orders/api-main",
            "build_number": "19",
            "build_url": "https://jenkins/job/acme-orders/job/api-main/19/",
            "status": "failed",
            "branch_name": "feature/corp-337-traces",
            "commit_sha": "def456",
            "trigger_actor": "admin",
            "deployment_target": "nonprod",
            "logs": long_log,
            "artifacts": [
                {
                    "file_name": "surefire.xml",
                    "relative_path": "target/surefire-reports/TEST-runtime.xml",
                    "url": "https://jenkins/artifact/surefire.xml",
                    "size_bytes": 2048,
                }
            ],
            "test_reports": [{"name": "unit", "total_count": 42, "fail_count": 0}],
            "coverage": {"line": 81.3, "branch": 72.0},
            "scan_reports": [{"tool": "trivy", "critical": 0, "high": 1}],
            "stages": [
                {"key": "checkout", "label": "Checkout", "status": "success", "logs": "checkout ok"},
                {
                    "key": "compile",
                    "label": "Compile",
                    "status": "failed",
                    "logs": long_log,
                    "artifacts": [{"file_name": "compile.log", "relative_path": "logs/compile.log"}],
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["status"] == "failed"
    assert trace["provider_type"] == "jenkins"
    assert trace["deployment_target"] == "nonprod"
    assert trace["failure_summary"]["primary_failure_type"] == "compile_failure"
    assert trace["failure_summary"]["failed_stage_count"] == 1
    assert trace["stages"][1]["failure_type"] == "compile_failure"
    assert trace["log_excerpt"]["truncated"] is True
    assert "plain-secret-should-not-leak" not in trace["log_excerpt"]["text"]
    assert "token=[redacted]" in trace["log_excerpt"]["text"]
    assert trace["artifacts"][0]["relative_path"] == "target/surefire-reports/TEST-runtime.xml"
    assert trace["coverage"]["line"] == 81.3
    assert trace["scan_reports"][0]["tool"] == "trivy"
    assert trace["agent_context"]["failed_stages"][0]["failure_type"] == "compile_failure"

    list_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-pipeline-traces",
        headers=auth_headers,
    )
    assert list_response.status_code == 200, list_response.text
    listed = list_response.json()
    assert listed["items"][0]["job_name"] == "acme-orders/api-main"
    assert listed["agent_failure_context"]["failure_count"] == 1
    assert listed["agent_failure_context"]["failed_stages"][0]["stage_key"] == "compile"

    feedback_response = await client.get(
        f"/api/v1/secure-work/work-items/{item.id}/agent-feedback-context",
        headers=auth_headers,
    )
    assert feedback_response.status_code == 200, feedback_response.text
    assert feedback_response.json()["cicd_failure_context"]["failed_stages"][0]["failure_type"] == "compile_failure"

    persisted = (
        await db.execute(select(WorkCicdPipelineTrace).where(WorkCicdPipelineTrace.work_item_id == item.id))
    ).scalar_one()
    assert persisted.failure_summary_json["primary_failure_type"] == "compile_failure"


async def test_pipeline_trace_failure_taxonomy_variants(client, auth_headers, db):
    provider = await _create_provider(client, auth_headers)
    item = _work_item(source_key="OCX-337B", title="Classify pipeline failures")
    db.add(item)
    await db.commit()

    response = await client.post(
        f"/api/v1/secure-work/work-items/{item.id}/cicd-pipeline-traces",
        headers=auth_headers,
        json={
            "provider_config_id": provider["id"],
            "job_name": "acme-orders/api-main",
            "status": "failed",
            "stages": [
                {
                    "key": "unit",
                    "label": "Unit tests",
                    "status": "failed",
                    "test_report": {"total_count": 120, "fail_count": 2},
                    "logs": "JUnit failed in RuntimeTest",
                },
                {
                    "key": "security",
                    "label": "Trivy scan",
                    "status": "failed",
                    "scan_report": {"tool": "trivy", "critical": 1},
                    "logs": "CVE-2026-0001 critical vulnerability",
                },
                {
                    "key": "deploy",
                    "label": "Helm deploy",
                    "status": "failed",
                    "logs": "kubectl rollout failed during deploy",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    stages = {stage["stage_key"]: stage for stage in response.json()["stages"]}
    assert stages["unit"]["failure_type"] == "unit_test_failure"
    assert stages["security"]["failure_type"] == "security_finding"
    assert stages["deploy"]["failure_type"] == "deployment_failure"
