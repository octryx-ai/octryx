"""Thread usage stats compare a workflow run's ROI against its matching baseline."""

import uuid
from decimal import Decimal

import pytest

from app.models import Session, ToolCall, UsageEvent, WorkflowCheckResult
from app.web._helpers._serialization_ext import _serialize_thread_stats
from app.web._helpers.thread_usage_stats import _load_thread_usage_stats


def _thread(admin_id, status, metadata):
    return Session(id=str(uuid.uuid4()), user_id=admin_id, status=status, metadata_=metadata)


def _sonnet_usage(session_id, admin_id, tokens_in, tokens_out, cost):
    return UsageEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=admin_id,
        provider="bedrock",
        model="sonnet",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=Decimal(cost),
    )


def _routing_check(session_id, state):
    return WorkflowCheckResult(
        id=str(uuid.uuid4()),
        session_id=session_id,
        workflow_key="aws-topology-diagram-routing",
        runtime="chat",
        state=state,
        results_json=[],
    )


@pytest.mark.asyncio
async def test_thread_usage_stats_include_workflow_roi_against_matching_baseline(db, auth_user):
    workflow_metadata = {
        "workflow_contract": {
            "workflow_id": "aws_topology_report",
            "workflow_class": "aws_topology_diagram_request",
        }
    }
    current_session = _thread(auth_user.id, "active", workflow_metadata)
    baseline_one = _thread(auth_user.id, "archived", workflow_metadata)
    baseline_two = _thread(auth_user.id, "archived", workflow_metadata)
    unrelated = _thread(auth_user.id, "archived", {"workflow_contract": {"workflow_id": "different_workflow"}})
    db.add_all([current_session, baseline_one, baseline_two, unrelated])
    db.add_all(
        [
            _sonnet_usage(current_session.id, auth_user.id, 100, 10, "0.010000"),
            _sonnet_usage(baseline_one.id, auth_user.id, 200, 20, "0.020000"),
            _sonnet_usage(baseline_two.id, auth_user.id, 300, 30, "0.030000"),
            _sonnet_usage(unrelated.id, auth_user.id, 1000, 100, "0.100000"),
            ToolCall(id=str(uuid.uuid4()), session_id=current_session.id, tool_name="aws_topology_snapshot"),
            ToolCall(id=str(uuid.uuid4()), session_id=baseline_one.id, tool_name="aws_topology_snapshot"),
            ToolCall(id=str(uuid.uuid4()), session_id=baseline_one.id, tool_name="aws_exposure_map"),
            ToolCall(id=str(uuid.uuid4()), session_id=baseline_two.id, tool_name="aws_topology_snapshot"),
            ToolCall(id=str(uuid.uuid4()), session_id=baseline_two.id, tool_name="aws_exposure_map"),
            ToolCall(id=str(uuid.uuid4()), session_id=baseline_two.id, tool_name="aws_config_query"),
            _routing_check(current_session.id, "passed"),
            _routing_check(baseline_one.id, "not_verified"),
            _routing_check(baseline_two.id, "passed"),
        ]
    )
    await db.flush()

    stats = await _load_thread_usage_stats(db, session_ids=[current_session.id])
    payload = _serialize_thread_stats(stats)

    assert payload is not None
    roi = payload["workflowRoi"]
    assert roi["status"] == "baseline_available"
    assert roi["workflowId"] == "aws_topology_report"
    assert roi["baselineSampleCount"] == 2
    assert roi["current"]["totalTokens"] == 110
    assert roi["baseline"]["totalTokens"] == 275
    assert roi["savings"]["tokenDelta"] == 165
    assert roi["savings"]["costDelta"] == pytest.approx(0.015)
    assert roi["savings"]["toolCallDelta"] == 2
    assert roi["quality"]["status"] == "measured"
    assert roi["quality"]["current"]["passRate"] == 1.0
    assert roi["quality"]["baseline"]["passRate"] == 0.5
