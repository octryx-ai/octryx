"""Tests for exec policy, bash tool approval, run_cli_command guardrails, and security analysis."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, ChangePreview, Session
from app.services.security_analyzer import analyze_security_risk
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_exec_policy_allows_read_only_git_in_a_read_only_run():
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
    )

    decision = await analyze_security_risk("bash", "git status", context)

    assert decision.action == "allow"
    assert decision.risk_level == "low"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_exec_policy_denies_destructive_shell_command():
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
    )

    decision = await analyze_security_risk("bash", "rm -rf /", context)

    assert decision.action == "deny"
    assert decision.risk_level == "critical"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_refuses_a_guarded_command_in_a_read_only_run():
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
        workspace_root="/tmp",
    )

    result = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    assert result["capability_refusal"]["run_capability"] == "read_only"
    assert result["capability_refusal"]["required_capability"] == "change"
    assert "approval_id" not in result


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_includes_security_analysis_for_secret_access_review(db, auth_user):
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id="security-analysis-secret",
        project_config={"security_analyzer_chain": ["secret_access"]},
        run_capability={"enforced": True, "class": "change"},
        workspace_root="/tmp",
        db=db,
    )

    result = await execute_tool("bash", {"command": "cat .env"}, context)

    assert "Execution blocked by policy" in result["error"]
    assert result["exec_policy_action"] == "review"
    assert result["approval_required"] is True
    assert result["security_analysis"]["analyzer_chain"] == ["secret_access"]
    assert result["security_analysis"]["findings"][0]["analyzer"] == "secret_access"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_cli_command_blocks_via_llm_risk_score(monkeypatch, db, auth_user):
    async def fake_run_llm_risk_model(tool_name, command_text, context, *, runtime_settings):
        return {
            "score": 88,
            "recommended_action": "review",
            "risk_level": "high",
            "reason": "This command applies infrastructure changes.",
            "signals": ["terraform", "apply"],
            "confidence": 0.91,
            "provider_name": "openrouter",
            "provider_display_name": "OpenRouter",
            "model": "security-model-v1",
        }

    monkeypatch.setattr(
        "app.services.security_analyzer.llm_risk._run_llm_risk_model",
        fake_run_llm_risk_model,
    )
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id="security-analysis-llm-risk",
        project_config={"security_analyzer_chain": ["llm_risk"]},
        run_capability={"enforced": True, "class": "change"},
        workspace_root="/tmp",
        db=db,
    )

    result = await execute_tool("run_cli_command", {"command": "terraform apply -auto-approve"}, context)

    assert "Execution blocked by policy" in result["error"]
    assert result["exec_policy_action"] == "deny"
    assert result["security_analysis"]["analyzer_chain"] == ["llm_risk"]
    assert result["security_analysis"]["findings"][0]["details"]["score"] == 88


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_creates_deduplicated_session_approval_in_a_change_run(db, llm_risk_review, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={"security_analyzer_chain": ["llm_risk"]},
        run_capability={"enforced": True, "class": "change"},
        workspace_root="/tmp",
        db=db,
    )

    first = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)
    second = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    approvals = (
        (
            await db.execute(
                select(Approval).where(Approval.session_id == session.id).order_by(Approval.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    assert first["approval_required"] is True
    assert first["approval_status"] == "pending"
    assert first["approval_id"] == second["approval_id"]
    assert len(approvals) == 1
    assert approvals[0].task_run_id is None
    assert approvals[0].session_id == session.id
    await db.refresh(session)
    assert session.status == "pending_approval"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_review_result_contains_change_preview_and_persists_it(db, llm_risk_review, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={"security_analyzer_chain": ["llm_risk"]},
        run_capability={"enforced": True, "class": "change"},
        workspace_root="/tmp",
        db=db,
    )

    result = await execute_tool("bash", {"command": "terraform apply -auto-approve"}, context)

    assert result["approval_required"] is True
    assert result["change_preview"]["kind"] == "terraform"
    assert "terraform apply -auto-approve" in result["change_preview"]["command"]
    preview = (
        await db.execute(select(ChangePreview).where(ChangePreview.approval_id == result["approval_id"]))
    ).scalar_one()
    assert preview.tool_name == "bash"
    assert "terraform apply -auto-approve" in preview.preview_json


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_kubectl_allows_read_only_get_in_a_read_only_run(monkeypatch):
    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"pods", b"")

    async def fake_exec(*args, **kwargs):
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
        workspace_root="/tmp",
    )

    result = await execute_tool("run_kubectl", {"args": ["get", "pods"]}, context)

    assert result["exit_code"] == 0
    assert result["stdout"] == "pods"
    assert "exec_policy_action" not in result


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.fixture
def llm_risk_review(monkeypatch):
    async def fake_run_llm_risk_model(tool_name, command_text, context, *, runtime_settings):
        return {
            "score": 55,
            "recommended_action": "review",
            "risk_level": "medium",
            "reason": "This command changes state.",
            "signals": ["write"],
            "confidence": 0.9,
            "provider_name": "openrouter",
            "provider_display_name": "OpenRouter",
            "model": "security-model-v1",
        }

    monkeypatch.setattr("app.services.security_analyzer.llm_risk._run_llm_risk_model", fake_run_llm_risk_model)
