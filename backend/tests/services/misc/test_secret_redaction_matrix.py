from __future__ import annotations

from app.services.admin.governance.admin_config_audit_service import sanitize_admin_audit_value
from app.services.provider.redaction import REDACTED_PROVIDER_SECRET, redact_provider_public_metadata
from app.services.redaction_policy import REDACTED_SECRET, redact_secret_payload, redaction_matrix
from app.tools.results import safe_tool_error_message


def test_redaction_matrix_documents_required_surfaces() -> None:
    matrix = redaction_matrix()

    assert {
        "admin_api",
        "chat_ui",
        "provider_metadata",
        "tool_results",
        "source_control_evidence",
        "logs",
    }.issubset(matrix)
    for entry in matrix.values():
        assert entry["owner"]
        assert entry["entry_point"]
        assert entry["rule"]
    assert matrix["logs"]["entry_point"] == "JsonLogFormatter"
    assert "structured extra metadata" in matrix["logs"]["rule"]


def test_shared_payload_redaction_covers_admin_provider_and_trace_surfaces() -> None:
    payload = {
        "safe": "visible",
        "api_key": "sk-secret-value",
        "nested": {
            "Authorization": "Bearer provider-token",
            "note": "failed with github_pat_very-secret-token",
        },
        "items": [{"private_key": ("-----BEGIN PRIVATE " + "KEY-----\nabc\n-----END PRIVATE " + "KEY-----")}],
    }

    admin_payload = sanitize_admin_audit_value(payload)
    provider_payload = redact_provider_public_metadata(payload)
    trace_payload = redact_secret_payload(payload)

    for redacted in (admin_payload, provider_payload, trace_payload):
        redacted_text = str(redacted)
        assert redacted["safe"] == "visible"
        assert redacted["api_key"] == REDACTED_SECRET
        assert redacted["nested"]["Authorization"] == REDACTED_SECRET
        assert redacted["nested"]["note"] == REDACTED_SECRET
        assert redacted["items"][0]["private_key"] == REDACTED_SECRET
        assert "sk-secret-value" not in redacted_text
        assert "provider-token" not in redacted_text
        assert "github_pat_very-secret-token" not in redacted_text
        assert "BEGIN PRIVATE KEY" not in redacted_text

    assert provider_payload["api_key"] == REDACTED_PROVIDER_SECRET


def test_tool_error_redaction_removes_credential_text_before_model_visibility() -> None:
    message = safe_tool_error_message(
        "clone failed for https://user:super-secret@example.test/scm/repo.git "
        "with Authorization: Bearer abcdefghijklmnop and private_key=-----BEGIN PRIVATE KEY-----abc-----END PRIVATE KEY-----"
    )

    assert "super-secret" not in message
    assert "abcdefghijklmnop" not in message
    assert "BEGIN PRIVATE KEY" not in message
    assert "https://[redacted]@example.test/scm/repo.git" in message
    assert "Bearer [redacted]" in message
    assert "private_key=[redacted]" in message
