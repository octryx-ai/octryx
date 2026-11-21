"""Shared helpers for the test_tool_execution_control_contract_* modules."""

from app.tools.definitions import get_all_definitions


def _definition(name: str) -> dict:
    return get_all_definitions()[name]
