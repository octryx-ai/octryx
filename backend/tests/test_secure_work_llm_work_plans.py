from __future__ import annotations

import json

from sqlalchemy import select

from app.models import AuditLog, User, WorkItem
from app.services.secure_work.plans.llm_work_plan import generate_llm_work_plan

# The plan the planning model returns for ACME-615.
_LLM_PLAN = {
    "plan_type": "configuration_change",
    "title": "ACME-615 Terraform and Helm cleanup plan",
    "understood_request": "ACME-615 asks to clean Terraform and Helm config after pipeline split.",
    "affected_repositories": [
        {
            "repository_name": "aws-shop-infrastructure",
            "repository_url": (
                "https://scm.example.test/bitbucket/projects/SHOP/"
                "repos/aws-shop-infrastructure/browse"
            ),
            "provider": "bitbucket",
            "scope": "Terraform and Helm base pipeline cleanup.",
            "confidence": "high",
            "evidence": "Repository URL is present in the Jira description.",
        }
    ],
    "proposed_branches": [
        {
            "repository_name": "aws-shop-infrastructure",
            "branch_name": "feature/acme-615-clean-terraform-helm",
            "reason": "Branch name derived from Jira key and title.",
        }
    ],
    "planned_files": [
        {
            "repository_name": "aws-shop-infrastructure",
            "paths": ["terraform/", "helm/"],
            "confidence": "medium",
        }
    ],
    "validation_plan": [
        {"command": "terraform validate", "reason": "Terraform cleanup.", "source": "llm_inference"},
        {"command": "helm lint", "reason": "Helm cleanup.", "source": "llm_inference"},
    ],
    "security_risks": [{"severity": "medium", "risk": "Infrastructure change.", "evidence": "Terraform"}],
    "required_approvals": [{"type": "work_plan", "required": True, "reason": "Review before execution."}],
    "expected_prs": [
        {
            "repository_name": "aws-shop-infrastructure",
            "target_branch": "main",
            "source_branch": "feature/acme-615-clean-terraform-helm",
            "status": "expected",
        }
    ],
    "open_questions": [],
    "assumptions": ["The pipeline split has already happened."],
    "rollback_plan": "Close the PR or revert the infrastructure config commit.",
    "trace_refs": [{"source": "jira", "key": "source_key", "value": "ACME-615"}],
}


def _jira_work_item() -> WorkItem:
    return WorkItem(
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        source_project_key="ACME",
        source_url="https://jira.example.test/browse/ACME-615",
        title="Cleaning Terraform and Helm Config",
        description=(
            "We need to clean first terraform after we have split the pipeline. "
            "Repository: https://scm.example.test/bitbucket/projects/SHOP/"
            "repos/aws-shop-infrastructure/browse"
        ),
        issue_type="Task",
        source_status="Open",
        work_state="ready_for_plan",
        sync_state="imported",
        labels_json=["octryx"],
    )


async def test_generate_llm_work_plan_uses_jira_evidence_without_deterministic_fallback(db):
    actor = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    item = _jira_work_item()
    db.add(item)
    await db.flush()

    async def fake_runtime_resolver(_db, *, runtime_target_id=None):
        return [
            {
                "target_id": "runtime-1",
                "provider_id": "provider-1",
                "provider_name": "bedrock",
                "model": "planning-model",
                "priority": 1,
            }
        ]

    async def fake_chat(runtimes, *, messages, tools, max_tokens, reasoning_effort, request_timeout_seconds):
        assert tools is None
        assert "ACME-615" in messages[1]["content"]
        assert "aws-shop-infrastructure" in messages[1]["content"]
        return (
            {"content": json.dumps(_LLM_PLAN), "usage": {"prompt_tokens": 10, "completion_tokens": 20}},
            runtimes[0],
            [{"runtime_target_id": "runtime-1", "status": "ok"}],
        )

    plan = await generate_llm_work_plan(
        db,
        work_item_id=item.id,
        current_user=actor,
        payload={"approval_base_url": "http://localhost:8000/chat"},
        chat_func=fake_chat,
        runtime_resolver_func=fake_runtime_resolver,
    )

    assert plan["status"] == "ready_for_review"
    assert plan["evidence"]["author"] == "llm"
    assert plan["evidence"]["plan_type"] == "configuration_change"
    assert plan["evidence"]["runtime"]["provider"] == "bedrock"
    assert plan["evidence"]["usage_summary"]["tokens_in"] == 10
    assert plan["evidence"]["usage_summary"]["tokens_out"] == 20
    assert plan["evidence"]["usage_summary"]["total_tokens"] == 30
    assert plan["affected_repositories"][0]["repository_name"] == "aws-shop-infrastructure"
    assert plan["jira_sync_preview"]["will_mutate_jira"] is False
    assert "Review and approve here: http://localhost:8000/chat?area=work" in plan["jira_sync_preview"]["comment_body"]
    assert plan["validation_plan"][0]["command"] == "terraform validate"

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == item.id,
                AuditLog.action == "secure_work.llm_work_plan_generated",
            )
        )
    ).scalar_one()
    assert audit.details["usage"]["total_tokens"] == 30
