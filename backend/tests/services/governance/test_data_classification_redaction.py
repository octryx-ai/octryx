from __future__ import annotations

from app.models.security.data_classification import (
    PII_EMAIL,
    PII_IP_ADDRESS,
    PII_SSN,
)
from app.services.data_classification.pii import detect_and_redact_pii, pii_redact_text

# ---------------------------------------------------------------------------
# PII detection and redaction
# ---------------------------------------------------------------------------


def test_pii_redact_text_email():
    text = "Contact us at john.doe@example.com for support."
    redacted, found = pii_redact_text(text)
    assert "[EMAIL]" in redacted
    assert "john.doe@example.com" not in redacted
    assert PII_EMAIL in found


def test_pii_redact_text_ssn():
    text = "SSN: 123-45-6789 on file."
    redacted, found = pii_redact_text(text)
    assert "[SSN]" in redacted
    assert "123-45-6789" not in redacted
    assert PII_SSN in found


def test_pii_redact_text_ip_address():
    text = "Request from 192.168.1.100 blocked."
    redacted, found = pii_redact_text(text)
    assert "[IP]" in redacted
    assert "192.168.1.100" not in redacted
    assert PII_IP_ADDRESS in found


def test_pii_redact_text_no_pii():
    text = "The meeting is on Monday at 10am."
    redacted, found = pii_redact_text(text)
    assert redacted == text
    assert found == []


def test_pii_redact_text_selective_types():
    text = "Email: test@example.com, Phone: +41441234567"
    redacted, found = pii_redact_text(text, pii_types=[PII_EMAIL])
    assert "[EMAIL]" in redacted
    assert PII_EMAIL in found
    # Phone should NOT be redacted when only EMAIL requested
    assert "+41441234567" in redacted


def test_detect_and_redact_pii_nested_dict():
    payload = {
        "user": {"email": "jane@example.com", "role": "admin"},
        "summary": "call from 10.0.0.1",
    }
    result, detected, paths = detect_and_redact_pii(payload)
    assert "[EMAIL]" in result["user"]["email"]
    assert "[IP]" in result["summary"]
    assert PII_EMAIL in detected
    assert PII_IP_ADDRESS in detected
    assert any("email" in p for p in paths)


def test_detect_and_redact_pii_list():
    payload = [
        {"note": "Contact alice@example.org"},
        {"note": "No sensitive data here"},
    ]
    result, detected, paths = detect_and_redact_pii(payload)
    assert "[EMAIL]" in result[0]["note"]
    assert result[1]["note"] == "No sensitive data here"
    assert PII_EMAIL in detected
