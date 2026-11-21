"""The evidence-grounding policy comes from explicit settings only, never from prompt keywords."""


import pytest
from fastapi import HTTPException

from app.agent.core.context.evidence_grounding import (
    render_evidence_grounding_prompt,
    resolve_evidence_grounding_policy,
)
from app.services.evidence_grounding_settings import (
    EvidenceGroundingPolicyError,
    normalize_evidence_grounding_policy,
)


def test_a_selected_workflow_that_requires_sources_applies_the_contract():
    policy = resolve_evidence_grounding_policy(
        workflow_contract={"workflow_id": "knowledge_request", "requires_sources": True},
        agent_type="chat",
        project_id="project-1",
    )

    assert policy.applies is True
    assert policy.triggers == ("workflow_requires_sources",)
    assert policy.evidence_available is False
    assert policy.reason == "grounding_without_retrieved_context"
    prompt = render_evidence_grounding_prompt(policy)
    assert "Evidence-Grounded Answer Contract" in prompt
    assert "the selected workflow requires sources" in prompt
    assert "do not fill the gap with plausible invented details" in prompt


def test_live_evidence_workflows_and_available_sources_are_recorded():
    policy = resolve_evidence_grounding_policy(
        workflow_contract={"workflow_id": "aws_infrastructure_lookup", "requires_live_evidence": True},
        agent_type="diagnosis",
        project_id="project-1",
        has_engineering_knowledge=True,
        has_repo_knowledge=True,
        has_runtime_engineering_pack=True,
    )

    assert policy.triggers == ("workflow_requires_live_evidence",)
    assert policy.evidence_sources == ("engineering_knowledge", "engineering_pack_runtime", "repository_context")
    assert policy.reason == "grounding_with_retrieved_context"
    assert "live cloud/platform/operations" in render_evidence_grounding_prompt(policy)


def test_configured_high_risk_agent_types_apply_the_contract():
    seeded = resolve_evidence_grounding_policy(workflow_contract=None, agent_type="knowledge", project_id="p1")
    configured = resolve_evidence_grounding_policy(
        workflow_contract=None,
        agent_type="payments_analyst",
        project_id="p1",
        high_risk_agent_types=["payments_analyst"],
    )
    narrowed = resolve_evidence_grounding_policy(
        workflow_contract=None, agent_type="knowledge", project_id="p1", high_risk_agent_types=["payments_analyst"]
    )

    assert seeded.triggers == ("high_risk_agent_type",)
    assert configured.triggers == ("high_risk_agent_type",)
    assert narrowed.applies is False


def test_the_workspace_setting_decides_plain_chat_and_fails_closed_on_an_invalid_value():
    required = resolve_evidence_grounding_policy(
        workflow_contract=None,
        agent_type="chat",
        project_id="p1",
        project_config={"evidence_grounding_policy": {"mode": "required"}},
    )
    workflow_only = resolve_evidence_grounding_policy(
        workflow_contract=None,
        agent_type="chat",
        project_id="p1",
        project_config={"evidence_grounding_policy": {"mode": "workflow"}},
    )
    invalid = resolve_evidence_grounding_policy(
        workflow_contract=None,
        agent_type="chat",
        project_id="p1",
        project_config={"evidence_grounding_policy": {"mode": "sometimes"}},
    )

    assert required.triggers == ("workspace_setting_required",)
    assert required.workspace_setting == "configured"
    assert workflow_only.applies is False
    assert invalid.applies is True
    assert invalid.triggers == ("workspace_setting_needs_configuration",)
    assert invalid.workspace_setting == "needs_configuration"


def test_no_explicit_source_means_no_contract_whatever_the_prompt():
    policy = resolve_evidence_grounding_policy(workflow_contract={}, agent_type="chat", project_id="p1")

    assert policy.applies is False
    assert policy.reason == "no_explicit_grounding_source"
    assert render_evidence_grounding_prompt(policy) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, {}), ({}, {}), ({"mode": None}, {}), ({"mode": "required"}, {"mode": "required"})],
)
def test_the_workspace_section_validates(value, expected):
    assert normalize_evidence_grounding_policy(value) == expected


@pytest.mark.parametrize("value", ["required", {"mode": "always"}, {"mode": "required", "domains": []}])
def test_the_workspace_section_refuses_unsupported_values(value):
    with pytest.raises(EvidenceGroundingPolicyError) as refused:
        normalize_evidence_grounding_policy(value)
    assert refused.value.code == "unsupported_evidence_grounding_mode"


@pytest.mark.asyncio
async def test_the_global_setting_is_data_and_the_retired_keywords_are_refused(db):
    from app.services.system_config.evidence_domains import (
        get_evidence_grounding_config,
        set_evidence_grounding_config,
    )

    config = await get_evidence_grounding_config(db)
    assert config["high_risk_agent_types_source"] == "default"
    assert "stable_jira_worker" in config["high_risk_agent_types"]

    for payload, code in [
        ({"domain_keywords": {"payments": ["chargeback"]}}, "unknown_setting"),
        ({"intent_keywords": []}, "unknown_setting"),
        ({"high_risk_agent_types": []}, "invalid_high_risk_agent_types"),
        ({"high_risk_agent_types": "knowledge"}, "invalid_high_risk_agent_types"),
    ]:
        with pytest.raises(HTTPException) as refused:
            await set_evidence_grounding_config(db, payload)
        assert refused.value.status_code == 422
        assert refused.value.detail["code"] == code
        assert refused.value.detail["errors"][0]["code"] == code

    config = await set_evidence_grounding_config(db, {"high_risk_agent_types": ["Payments_Analyst", "knowledge"]})
    assert config["high_risk_agent_types_source"] == "configured"
    assert config["high_risk_agent_types"] == frozenset({"payments_analyst", "knowledge"})

    config = await set_evidence_grounding_config(db, {"high_risk_agent_types": None})
    assert config["high_risk_agent_types_source"] == "default"
