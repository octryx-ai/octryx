from app.services.api_key.service import ALLOWED_API_KEY_SCOPES, normalize_api_key_scopes
from app.services.security_scope_contract import (
    core_role_scopes,
    permission_catalog,
    permission_keys,
    scope_contract_summary,
)


def test_permission_catalog_contains_admin_tool_connector_and_workflow_scopes() -> None:
    catalog = permission_catalog()

    assert {"resource": "users", "action": "read", "enforced": True} in catalog
    assert {"resource": "api_keys", "action": "self_write", "enforced": True} in catalog
    assert {"resource": "auth", "action": "login", "enforced": True} in catalog
    assert {"resource": "tools", "action": "execute", "enforced": False} in catalog
    assert {"resource": "connectors", "action": "read", "enforced": False} in catalog
    assert {"resource": "source_control", "action": "write", "enforced": False} in catalog
    assert {"resource": "database_tools", "action": "read", "enforced": False} in catalog
    assert {"resource": "workflows", "action": "execute", "enforced": False} in catalog
    assert ("tools", "execute") in permission_keys()


def test_api_key_scope_allowlist_uses_security_scope_contract() -> None:
    assert "source_control:read" in ALLOWED_API_KEY_SCOPES
    assert "database:write" in ALLOWED_API_KEY_SCOPES
    assert normalize_api_key_scopes(["SOURCE_CONTROL:READ", "database:write"]) == [
        "source_control:read",
        "database:write",
    ]


def test_core_role_scope_mapping_is_explicit() -> None:
    assert "admin" in core_role_scopes("admin")
    assert "tools:execute" in core_role_scopes("operator")
    assert "source_control:write" in core_role_scopes("technical")
    assert "workflow:read" in core_role_scopes("viewer")
    assert core_role_scopes("unknown") == ()


def test_scope_contract_summary_is_secret_free() -> None:
    summary = scope_contract_summary()

    assert "permissions" in summary
    assert "api_key_scopes" in summary
    assert "core_role_scopes" in summary
    rendered = str(summary).lower()
    assert "password" not in rendered
    assert "token" not in rendered
    assert "secret" not in rendered
