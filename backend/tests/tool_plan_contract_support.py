"""Shared tool definition and catalog builders for the tool plan contract tests."""

from app.services.tool_catalog import build_session_tool_catalog
from app.tools.definitions import get_all_definitions


def _definition(name: str) -> dict:
    return get_all_definitions()[name]


def _catalog(*names: str, workflow_contract: dict | None = None) -> dict:
    return build_session_tool_catalog(
        tool_definitions=[_definition(name) for name in names],
        capability_type="admin",
        request_analysis={"requested_domains": ["aws"]},
        workflow_contract=workflow_contract,
    )
