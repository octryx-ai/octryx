"""A synthesized AWS evidence report after a stuck tool error loop."""

import pytest

from app.agent.loops.outcome._loop_post_tool import handle_post_tool_outcome
from app.agent.loops.outcome._loop_post_tool_inputs import PostToolInputs
from tests.loop_post_tool_support import _build_kwargs, _noop_async


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_synthesizes_aws_stuck_error_evidence_report() -> None:
    synthesized: list[dict[str, object]] = []

    async def _capture_synthesized_message(**kwargs):  # type: ignore[no-untyped-def]
        synthesized.append(kwargs)
        return None

    result = await handle_post_tool_outcome(PostToolInputs(
        **_build_kwargs(
            wrapup_forced=False,
            persist_traced_assistant_message=_noop_async,
            persist_synthesized_tool_assistant=_capture_synthesized_message,
            current_user_message="Validate AWS EKS and CloudWatch state. Do not change anything.",
            tool_results=[
                {
                    "tool_name": "aws_read_operation",
                    "result": {"error": "AWS circuit breaker is open"},
                }
            ],
            turn_tool_history=[
                {
                    "tool_name": "aws_read_operation",
                    "params": {"service": "eks", "operation": "describe-cluster"},
                    "result": {
                        "service": "eks",
                        "operation": "describe-cluster",
                        "result": {
                            "cluster": {
                                "name": "demo-nonprod-eks",
                                "resourcesVpcConfig": {
                                    "endpointPublicAccess": False,
                                    "endpointPrivateAccess": True,
                                },
                            }
                        },
                    },
                }
            ],
            active_steps=[],
            current_step={},
            stuck_loop_kind="repetitive_tool_error_loop",
        )
    ))

    assert result["action"] == "return"
    assert "endpoint private only" in result["yield_content"]
    assert "AWS calls that did not complete" in result["yield_content"]
    assert synthesized[0]["source"] == "aws_diagnosis_stuck_evidence_report"
