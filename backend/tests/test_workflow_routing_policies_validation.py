"""Phase validation of a phased workflow: mutating tools, allow rules, contract and source step tools."""

from __future__ import annotations

from app.services.workflow_runs.phase_validation import validate_phase_payload


def _phase_payload() -> dict[str, object]:
    return {
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "workflow_contract": {
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "capability_class": "read_only",
            "when_to_use": "Answer from the project knowledge.",
        },
        "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read"], "denylist": []},
        "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
    }


def _codes(items: list[dict[str, str]]) -> set[str]:
    return {item["code"] for item in items}


def test_phase_validation_rejects_unsafe_mutating_tools() -> None:
    report = validate_phase_payload({**_phase_payload(), "tool_policy": {"allowlist": ["bash", "edit_workspace_file"]}})

    assert report["valid"] is False
    assert "unsafe_mutating_tools" in _codes(report["errors"])


def test_phase_validation_accepts_a_read_only_diagnosis_phase() -> None:
    report = validate_phase_payload(_phase_payload())

    assert report["valid"] is True
    assert report["errors"] == []


def test_phase_validation_accepts_pattern_and_read_only_allow_rules() -> None:
    report = validate_phase_payload(
        {
            **_phase_payload(),
            "tool_policy": {
                "allowlist": [],
                "denylist": [],
                "allow_patterns": ["knowledge_search*"],
                "deny_patterns": ["*_secret*"],
                "allow_read_only": True,
            },
        }
    )

    assert report["valid"] is True, report["errors"]
    assert "empty_tool_allowlist" not in _codes(report["warnings"])


def test_phase_validation_warns_when_contract_tools_are_not_allowed() -> None:
    payload = _phase_payload()
    payload["workflow_contract"] = {**payload["workflow_contract"], "allowed_tools": ["knowledge_read", "web_search"]}

    report = validate_phase_payload(payload)

    assert report["valid"] is True
    assert "workflow_contract_tools_not_allowed" in _codes(report["warnings"])


def test_phase_validation_warns_when_source_step_tools_are_not_allowed() -> None:
    payload = _phase_payload()
    payload["workflow_contract"] = {
        **payload["workflow_contract"],
        "source_steps": [{"tool": "knowledge_search"}, {"tool": "search_confluence"}],
    }

    report = validate_phase_payload(payload)

    assert report["valid"] is True
    assert "workflow_contract_tools_not_allowed" in _codes(report["warnings"])


def test_phase_validation_rejects_mutating_allow_pattern_in_diagnosis_mode() -> None:
    report = validate_phase_payload(
        {**_phase_payload(), "tool_policy": {"allowlist": [], "denylist": [], "allow_patterns": ["*file"]}}
    )

    assert report["valid"] is False
    assert "unsafe_mutating_tools" in _codes(report["errors"])


def test_phase_validation_warns_on_an_empty_tool_policy_and_refuses_overlaps() -> None:
    empty = validate_phase_payload({**_phase_payload(), "tool_policy": {"allowlist": [], "denylist": []}})
    assert empty["valid"] is True
    assert "empty_tool_allowlist" in _codes(empty["warnings"])

    overlap = validate_phase_payload(
        {**_phase_payload(), "tool_policy": {"allowlist": ["knowledge_search"], "denylist": ["knowledge_search"]}}
    )
    assert "allowlist_denylist_overlap" in _codes(overlap["errors"])
