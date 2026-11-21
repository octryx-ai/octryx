import uuid

from app.models import Session, ToolCall
from app.services.sub_agent_group.evidence import (
    determine_sub_agent_evidence_profile,
    summarize_sub_agent_evidence_quality,
)


def _successful_tool_call(tool_name: str) -> ToolCall:
    return ToolCall(
        id=str(uuid.uuid4()),
        session_id="child-1",
        tool_name=tool_name,
        parameters={},
        result={"ok": True},
        status="success",
    )


def test_operations_profile_comes_from_explicit_parent_state_only():
    # Prompt-derived domains and a keyword AWS plan no longer pick the profile.
    keyword_parent = Session(
        id="parent-1",
        user_id="user-1",
        agent_type="diagnosis",
        metadata_={
            "request_analysis": {
                "requested_domains": ["aws"],
                "aws_diagnosis_plan": {"kind": "aws_diagnosis_budget"},
            }
        },
    )
    explicit_parent = Session(
        id="parent-2",
        user_id="user-1",
        agent_type="diagnosis",
        metadata_={"routing_intent": "operations"},
    )

    assert determine_sub_agent_evidence_profile(keyword_parent) == "generic"
    assert determine_sub_agent_evidence_profile(explicit_parent) == "operations"


def test_operations_child_rejects_generic_tool_evidence():
    quality = summarize_sub_agent_evidence_quality(
        profile="operations",
        topic="AWS platform analysis",
        status="completed",
        final_response="The AWS environment appears healthy based on the available context.",
        tool_calls=[_successful_tool_call("knowledge_search")],
    )

    assert quality["accepted"] is False
    assert quality["is_operations_grounded"] is False
    assert "missing_operations_evidence_tools" in quality["rejection_reasons"]


def test_operations_child_accepts_aws_tool_evidence():
    quality = summarize_sub_agent_evidence_quality(
        profile="operations",
        topic="AWS platform analysis",
        status="completed",
        final_response="The AWS environment has one inspected CodePipeline and no denied read calls.",
        tool_calls=[_successful_tool_call("aws_read_operation")],
    )

    assert quality["accepted"] is True
    assert quality["is_operations_grounded"] is True
    assert quality["rejection_reasons"] == []
