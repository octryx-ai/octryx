
import pytest

from app.services.security_analyzer import (
    analyze_security_risk,
    list_security_analyzer_options,
    normalize_security_analyzer_chain,
)
from app.tools.context import ToolContext


def test_normalize_security_analyzer_chain_filters_unknown_values():
    assert normalize_security_analyzer_chain(["secret_access", "SECRET_ACCESS", "unknown", "exec_policy"]) == [
        "secret_access",
        "exec_policy",
    ]
    assert normalize_security_analyzer_chain("") == ["exec_policy", "secret_access", "command_guardrail"]


def test_list_security_analyzer_options_includes_builtin_chain():
    options = list_security_analyzer_options()

    assert [item["key"] for item in options] == [
        "exec_policy",
        "secret_access",
        "command_guardrail",
        "llm_risk",
    ]


@pytest.mark.asyncio
async def test_analyze_security_risk_reviews_secret_access(db, auth_user):
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id="secret-review-session",
        project_config={"security_analyzer_chain": ["secret_access"]},
        capability_type="change",
        db=db,
    )

    report = await analyze_security_risk("bash", "cat .env.production", context)

    assert report.action == "review"
    assert report.risk_level == "high"
    assert report.analyzer_chain == ["secret_access"]
    assert report.findings[0].analyzer == "secret_access"
    assert "Secret-bearing files" in report.reason


@pytest.mark.asyncio
async def test_command_guardrail_sends_a_command_with_a_credential_for_review(db, auth_user):
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id="content-policy-session",
        project_config={"security_analyzer_chain": ["command_guardrail"]},
        db=db,
    )

    report = await analyze_security_risk("run_cli_command", "deploy --password=Hunter2024x --host 10.1.2.3", context)

    assert report.action == "review"
    assert report.risk_level == "high"
    assert report.analyzer_chain == ["command_guardrail"]
    details = report.findings[0].details
    assert details["policies"] == ["platform:credentials-masked", "platform:internal-ip-reported"]
    assert details["found"] == {"credential_assignment": 1, "internal_ip": 1}
    assert "Hunter2024x" not in str(details) and "10.1.2.3" not in str(details)


@pytest.mark.asyncio
async def test_analyze_security_risk_uses_llm_risk_score_thresholds(monkeypatch, db, auth_user):
    async def fake_run_llm_risk_model(tool_name, command_text, context, *, runtime_settings):
        assert tool_name == "run_cli_command"
        assert "terraform apply" in command_text
        assert runtime_settings["llm_security_analyzer_review_threshold"] == 45
        return {
            "score": 91,
            "recommended_action": "review",
            "reason": "This mutates infrastructure with broad blast radius.",
            "signals": ["terraform", "infrastructure mutation"],
            "confidence": 0.93,
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
        session_id="llm-risk-session",
        project_config={"security_analyzer_chain": ["llm_risk"]},
        capability_type="change",
        db=db,
    )
    from app.models import SystemConfig

    db.add(SystemConfig(key="agent.llm_security_analyzer_review_threshold", value="45"))
    db.add(SystemConfig(key="agent.llm_security_analyzer_deny_threshold", value="80"))
    db.add(SystemConfig(key="agent.llm_security_analyzer_timeout_seconds", value="9"))
    await db.commit()

    report = await analyze_security_risk("run_cli_command", "terraform apply -auto-approve", context)

    assert report.action == "deny"
    assert report.risk_level == "critical"
    assert report.findings[0].details["score"] == 91
    assert report.findings[0].details["threshold_action"] == "deny"
    assert report.findings[0].details["model"] == "security-model-v1"


@pytest.mark.asyncio
async def test_analyze_security_risk_fails_closed_for_llm_risk_errors(monkeypatch, db, auth_user):
    async def fake_run_llm_risk_model(tool_name, command_text, context, *, runtime_settings):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "app.services.security_analyzer.llm_risk._run_llm_risk_model",
        fake_run_llm_risk_model,
    )
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id="llm-risk-error-session",
        project_config={"security_analyzer_chain": ["llm_risk"]},
        capability_type="change",
        db=db,
    )

    report = await analyze_security_risk("run_cli_command", "terraform apply -auto-approve", context)

    assert report.action == "review"
    assert report.risk_level == "medium"
    assert "manual review is required" in report.reason.lower()
