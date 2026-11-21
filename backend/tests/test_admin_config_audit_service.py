from __future__ import annotations

from app.services.admin.governance.admin_config_audit_service import (
    build_admin_config_audit_details,
    sanitize_admin_audit_value,
)


def test_admin_config_audit_redacts_secret_bearing_values_recursively():
    sanitized = sanitize_admin_audit_value(
        {
            "api_key": "sk-secret",
            "nested": {
                "password": "pw",
                "public": "value",
                "items": [{"token": "tok"}, {"name": "safe"}],
            },
            "long": "x" * 400,
        }
    )

    assert sanitized["api_key"] == "[redacted]"
    assert sanitized["nested"]["password"] == "[redacted]"
    assert sanitized["nested"]["items"][0]["token"] == "[redacted]"
    assert sanitized["nested"]["items"][1]["name"] == "safe"
    assert sanitized["long"].endswith("...")
    assert len(sanitized["long"]) == 303


def test_admin_config_audit_details_include_safe_changed_keys():
    details = build_admin_config_audit_details(
        before={"enabled": False, "password": "old", "same": "value"},
        after={"enabled": True, "password": "new", "same": "value"},
        extra={"reason": "admin_update", "secret_ref": "secret-id"},
    )

    assert details["changed_keys"] == ["enabled"]
    assert details["before"]["password"] == "[redacted]"
    assert details["after"]["password"] == "[redacted]"
    assert details["reason"] == "admin_update"
    assert details["secret_ref"] == "[redacted]"
