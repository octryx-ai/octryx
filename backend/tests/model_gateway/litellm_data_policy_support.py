"""Alias sections and the excessive classifications shared by the test_litellm_data_policy_* modules."""

from __future__ import annotations

from typing import Any

from tests.model_gateway.conftest import ALIAS, gateway_section

EXCESSIVE_CLASSIFICATIONS = ("confidential", "restricted", "secret")


def _alias_section(data_policy_class: str) -> dict[str, Any]:
    section = gateway_section()
    section["aliases"][ALIAS]["data_policy_class"] = data_policy_class
    return {"litellm_gateway": section}
