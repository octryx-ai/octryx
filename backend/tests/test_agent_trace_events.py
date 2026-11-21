"""Trace capture policy and retention of the ``agent_trace_*`` store.

Runs are read from ``turn_traces`` (tests/test_observability_runs.py); this store has no writer. The capture-policy
helpers and the retention of rows already stored are what remains of it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Project, RetentionPolicy
from app.services.privacy import apply_retention_policies
from app.services.trace_capture import (
    DEFAULT_TRACE_CAPTURE_CONFIG,
    TraceCapturePolicy,
    apply_trace_capture_to_payload,
    decide_trace_capture,
    ensure_default_trace_capture_config,
)
from app.services.trace_events import (
    REDACTED_VALUE,
    create_trace_run,
    create_trace_span,
    finish_trace_run,
    get_trace_run_detail,
)
from app.time_utils import utc_now


def test_trace_capture_policy_defaults_compact_successful_payloads_and_preserves_errors():
    standard_decision = decide_trace_capture(TraceCapturePolicy(), root_status="success", tool_trace=[])
    error_decision = decide_trace_capture(TraceCapturePolicy(), root_status="error", tool_trace=[])
    minimal_decision = decide_trace_capture(TraceCapturePolicy(mode="minimal"), root_status="success", tool_trace=[])
    debug_decision = decide_trace_capture(TraceCapturePolicy(mode="debug"), root_status="success", tool_trace=[])

    assert standard_decision.payload_mode == "compact"
    assert apply_trace_capture_to_payload({"text": "x" * 1000}, standard_decision)["text"].endswith("...[truncated]")
    assert error_decision.payload_mode == "full"
    assert apply_trace_capture_to_payload({"text": "x" * 1000}, error_decision)["text"] == "x" * 1000
    assert minimal_decision.payload_mode == "metadata_only"
    assert apply_trace_capture_to_payload({"text": "x" * 1000}, minimal_decision) == {
        "capture": "metadata_only",
        "reason": "minimal_mode",
    }
    assert debug_decision.payload_mode == "full"


def test_trace_capture_payload_modes_redact_nested_secrets_before_returning_payloads():
    payload = {
        "message": "safe diagnostic detail",
        "api_key": "sk-trace-secret-value",
        "nested": {
            "Authorization": "Bearer abc123456789",
            "items": [{"refresh_token": "refresh-secret"}, {"value": "visible"}],
        },
    }
    standard_decision = decide_trace_capture(TraceCapturePolicy(), root_status="success", tool_trace=[])
    audit_decision = decide_trace_capture(TraceCapturePolicy(mode="audit"), root_status="success", tool_trace=[])
    error_decision = decide_trace_capture(TraceCapturePolicy(), root_status="error", tool_trace=[])
    sensitive_decision = decide_trace_capture(
        TraceCapturePolicy(),
        root_status="success",
        tool_trace=[{"tool_name": "read_secret_value", "result": {"ok": True}}],
    )
    minimal_decision = decide_trace_capture(TraceCapturePolicy(mode="minimal"), root_status="success", tool_trace=[])

    compact_payload = apply_trace_capture_to_payload(payload, standard_decision)
    audit_payload = apply_trace_capture_to_payload(payload, audit_decision)
    error_payload = apply_trace_capture_to_payload(payload, error_decision)
    sensitive_payload = apply_trace_capture_to_payload(payload, sensitive_decision)
    minimal_payload = apply_trace_capture_to_payload(payload, minimal_decision)

    assert standard_decision.payload_mode == "compact"
    assert audit_decision.payload_mode == "full"
    assert error_decision.payload_mode == "full"
    assert sensitive_decision.payload_mode == "full"
    for captured in (compact_payload, audit_payload, error_payload, sensitive_payload):
        assert captured["message"] == "safe diagnostic detail"
        assert captured["api_key"] == REDACTED_VALUE
        assert captured["nested"]["Authorization"] == REDACTED_VALUE
        assert captured["nested"]["items"][0]["refresh_token"] == REDACTED_VALUE
        assert captured["nested"]["items"][1]["value"] == "visible"
        assert "sk-trace-secret-value" not in str(captured)
        assert "abc123456789" not in str(captured)
        assert "refresh-secret" not in str(captured)
    assert minimal_payload == {"capture": "metadata_only", "reason": "minimal_mode"}


def test_trace_capture_default_config_is_visible_and_non_destructive():
    config = ensure_default_trace_capture_config({"managed_repo_root": "var/repos"})

    assert config["managed_repo_root"] == "var/repos"
    assert config["trace_capture"] == DEFAULT_TRACE_CAPTURE_CONFIG

    overridden = ensure_default_trace_capture_config({"trace_capture": {"mode": "debug"}})

    assert overridden["trace_capture"]["mode"] == "debug"
    assert overridden["trace_capture"]["compact_max_string"] == DEFAULT_TRACE_CAPTURE_CONFIG["compact_max_string"]


@pytest.mark.asyncio
async def test_trace_retention_policy_anonymizes_canonical_payloads(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    old_timestamp = utc_now() - timedelta(days=3)
    run = await create_trace_run(db, project_id=project.id, metadata={"api_key": "secret"}, started_at=old_timestamp)
    run.created_at = old_timestamp
    span = await create_trace_span(
        db,
        trace_run_id=run.id,
        span_type="llm",
        name="old model call",
        status="success",
        started_at=old_timestamp,
        input_json={"password": "secret"},
        output_json={"token": "secret"},
        metadata={"client_secret": "secret"},
        error="sensitive error",
    )
    span.created_at = old_timestamp
    await finish_trace_run(db, trace_run_id=run.id, status="success", ended_at=old_timestamp)
    db.add(RetentionPolicy(entity_type="agent_trace_runs", ttl_days=1, action="anonymize", is_active=True))
    await db.commit()

    affected = await apply_retention_policies(db)
    detail = await get_trace_run_detail(db, trace_run_id=run.id)

    assert affected == 2
    assert detail is not None
    assert detail["metadata"] == {"retention": "anonymized"}
    assert detail["error"] is None
    assert detail["spans"][0]["input"] == {"retention": "anonymized"}
    assert detail["spans"][0]["output"] == {"retention": "anonymized"}
    assert detail["spans"][0]["metadata"] == {"retention": "anonymized"}
    assert detail["spans"][0]["error"] is None
