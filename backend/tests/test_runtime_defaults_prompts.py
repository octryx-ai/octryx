"""The runtime mode baseline and the prompt builder: externalized instructions and thinking defaults, section order and cache sections."""

from app.agent.runtime_defaults import (
    DEFAULT_AGENT_MODE_KEY,
    DEFAULT_AGENT_MODES,
    get_system_agent_mode_definition,
)
from app.services.agent_mode import normalize_capability_type

MIGRATED_STATIC_PROMPT_MARKERS = (
    "For project-specific presentation, PowerPoint, deck, or slide requests",
    "For Word, DOCX, report, or business-document generation requests",
    "For Excel, XLSX, workbook, spreadsheet, dashboard",
    "For research-style Word reports",
    "For uploaded PDFs, Office files, images, or research URLs",
    "For Bitbucket requests that ask for recent commits",
    "For repository change tasks",
    "For coding changes in local workspaces",
    "For ANY diagram, flowchart, or architecture request",
    "For Jira time-window queries",
    "When the user asks to configure the platform",
)


def test_runtime_defaults_export_expected_mode_baseline() -> None:
    default_keys = {item["key"] for item in DEFAULT_AGENT_MODES}

    assert DEFAULT_AGENT_MODE_KEY == "diagnosis"
    assert {"diagnosis", "change", "plan", "admin"}.issubset(default_keys)
    assert normalize_capability_type("unsupported") == DEFAULT_AGENT_MODE_KEY




def test_system_agent_mode_definition_lookup_uses_governed_registry() -> None:
    change_mode = get_system_agent_mode_definition("change")

    assert change_mode is not None
    assert change_mode.key == "change"
    assert change_mode.capability_type == "change"
    assert change_mode.as_record()["prompt_instructions"].startswith("Make controlled changes")
    assert get_system_agent_mode_definition("missing-mode") is None










