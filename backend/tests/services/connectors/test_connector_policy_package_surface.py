"""The connector policy package exports its service surface; the normalisation contract."""

from app.services import connector_policy as connector_policy_package
from app.services.connector_policy import service as connector_policy_package_service


def test_connector_policy_package_exports_its_service_surface() -> None:
    exported_names = [
        "get_connector_policy",
        "list_connector_policies",
        "normalize_connector_policy",
        "upsert_connector_policy",
    ]

    assert connector_policy_package.__all__ == exported_names

    for name in exported_names:
        assert getattr(connector_policy_package, name) is getattr(connector_policy_package_service, name)

    assert connector_policy_package.get_connector_policy is connector_policy_package_service.get_connector_policy
    assert connector_policy_package.list_connector_policies is connector_policy_package_service.list_connector_policies
    assert connector_policy_package.upsert_connector_policy is connector_policy_package_service.upsert_connector_policy


def test_normalize_connector_policy_contract_is_stable() -> None:
    normalized = connector_policy_package.normalize_connector_policy(
        {
            "tool_instructions": "  use least privilege  ",
            "extra_tools": " foo, bar ,, baz ",
            "disabled_tools": [" alpha ", "", "beta", 3],
        }
    )

    assert normalized == {
        "tool_instructions": "use least privilege",
        "extra_tools": ["foo", "bar", "baz"],
        "disabled_tools": ["alpha", "beta", "3"],
    }
