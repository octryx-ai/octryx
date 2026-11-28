"""Contract: every browser automation tool has an explicit risk class."""

from __future__ import annotations

import pytest

from app.tools.capability_requirements import CAPABILITY_DELIVER, CAPABILITY_READ_ONLY, tool_required_capability
from app.tools.definitions import get_all_definitions, get_tool_definition_metadata
from app.tools.definitions.write_risk import (
    BROWSER_READ_DEFINITION_NAMES,
    BROWSER_WRITE_DEFINITION_NAMES,
    BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
)
from app.tools.registry import TOOL_REGISTRY_ENTRIES

_BROWSER_TOOL_CLASSES = {
    "browser_open_url": "read",
    "browser_snapshot": "read",
    "browser_take_screenshot": "read",
    "browser_close": "read",
    "browser_click": "write",
    "browser_type": "write",
    "browser_press": "write",
}


def _browser_tool_names() -> set[str]:
    registered = {name for name in TOOL_REGISTRY_ENTRIES if name.startswith("browser_")}
    defined = {name for name in get_all_definitions() if name.startswith("browser_")}
    return registered | defined


def test_every_browser_tool_is_listed_and_classified_exactly_once():
    assert _browser_tool_names() == set(_BROWSER_TOOL_CLASSES)
    assert BROWSER_READ_DEFINITION_NAMES.isdisjoint(BROWSER_WRITE_DEFINITION_NAMES)
    assert BROWSER_READ_DEFINITION_NAMES | BROWSER_WRITE_DEFINITION_NAMES == set(_BROWSER_TOOL_CLASSES)
    assert BROWSER_WRITE_DEFINITION_NAMES <= BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES


@pytest.mark.parametrize(("tool_name", "risk_class"), sorted(_BROWSER_TOOL_CLASSES.items()))
def test_browser_tool_governance_follows_its_class(tool_name, risk_class):
    metadata = get_tool_definition_metadata(tool_name)
    assert metadata.owner_type == "built_in"
    assert metadata.risk == risk_class
    if risk_class == "write":
        assert (metadata.approval_required, metadata.mutates_state, metadata.audit_required) == (True, True, True)
        assert tool_required_capability(tool_name) == CAPABILITY_DELIVER
    else:
        assert (metadata.approval_required, metadata.mutates_state) == (False, False)
        assert tool_required_capability(tool_name) == CAPABILITY_READ_ONLY
