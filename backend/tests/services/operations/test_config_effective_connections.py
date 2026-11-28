"""``services/config_effective``: availability and the per-field "narrower" rules of a connection."""

from __future__ import annotations

import pytest

from app.services.config_effective import (
    CONNECTION_RULES,
    DeviationNotNarrowerError,
    Subject,
    available,
    check_deviation,
    effective,
)

BASE = {
    "knowledge": {"enabled": True, "scope": {"projects": ["BRD", "OPS"]}, "schedule": "hourly",
                  "schedule_cron": None},
    "tickets": {"enabled": True, "scope": {"projects": ["BRD"]}, "schedule": "custom",
                "schedule_cron": "*/30 * * * *", "write_back": {"enabled": True, "transitions": []}},
    "agent_tools": {"level": "read"},
}
SELECTED = Subject(available_in="selected", workspace_ids=frozenset({"ws-a"}), owner_workspace_id="ws-own")


def test_availability_follows_all_selected_and_owner() -> None:
    assert available(Subject(available_in="all"), "anything")
    assert available(SELECTED, "ws-a") and available(SELECTED, "ws-own")
    assert not available(SELECTED, "ws-b")
    assert effective(SELECTED, "ws-b", BASE, None, CONNECTION_RULES).as_dict() == {
        "available": False, "effective": None, "deviation": None}


@pytest.mark.parametrize("deviation, expected", [
    ({"knowledge": {"scope": {"projects": ["brd"]}}}, ("knowledge", "scope", {"projects": ["brd"]})),
    ({"knowledge": {"schedule": "off"}}, ("knowledge", "schedule", "manual")),
    ({"knowledge": {"schedule": "hourly"}}, ("knowledge", "schedule", "hourly")),
    ({"tickets": {"schedule": "custom", "schedule_cron": "*/30  * * * *"}}, ("tickets", "schedule_cron", "*/30 * * * *")),
    ({"tickets": {"write_back": False}}, ("tickets", "write_back", {"enabled": False, "transitions": []})),
    ({"tickets": {"enabled": False}}, ("tickets", "enabled", False)),
    ({"agent_tools": {"level": "off"}}, ("agent_tools", "level", "off")),
    ({"agent_tools": {"level": "read"}}, ("agent_tools", "level", "read")),
])
def test_each_field_accepts_a_narrower_value(deviation, expected) -> None:
    use, field, value = expected
    assert check_deviation(BASE, deviation, CONNECTION_RULES)[use][field] == value
    result = effective(SELECTED, "ws-a", BASE, deviation, CONNECTION_RULES)
    assert result.available and result.effective[use][field] == value and result.deviation == deviation


@pytest.mark.parametrize("deviation, field", [
    ({"knowledge": {"scope": {"projects": ["BRD", "NEW"]}}}, "knowledge.scope.projects"),
    ({"knowledge": {"scope": {"spaces": ["SALES"]}}}, "knowledge.scope.spaces"),
    ({"knowledge": {"schedule": "every_15_min"}}, "knowledge.schedule"),
    ({"tickets": {"schedule": "custom", "schedule_cron": "*/15 * * * *"}}, "tickets.schedule"),
    ({"agent_tools": {"level": "write"}}, "agent_tools.level"),
    ({"agent_tools": {"level": "admin"}}, "agent_tools.level"),
    ({"tickets": {"write_back": "yes"}}, "tickets.write_back"),
    ({"tickets": {"filter": "project = X"}}, "tickets.filter"),
    ({"models": {"allowed": ["a"]}}, "models"),
    ({"tickets": {"schedule_cron": "*/30 * * * *"}}, "tickets.schedule_cron"),
])
def test_anything_wider_or_unknown_is_refused_with_its_field(deviation, field) -> None:
    with pytest.raises(DeviationNotNarrowerError) as refused:
        check_deviation(BASE, deviation, CONNECTION_RULES)
    assert refused.value.field == field and refused.value.code == "deviation_not_narrower"


def test_switching_write_back_or_a_disabled_use_on_is_wider() -> None:
    base = {**BASE, "tickets": {**BASE["tickets"], "enabled": False, "write_back": {"enabled": False}}}
    for deviation, field in (({"tickets": {"write_back": True}}, "tickets.write_back"),
                             ({"tickets": {"enabled": True}}, "tickets.enabled")):
        with pytest.raises(DeviationNotNarrowerError) as refused:
            check_deviation(base, deviation, CONNECTION_RULES)
        assert refused.value.field == field


def test_an_unrestricted_scope_admits_any_subset() -> None:
    base = {"knowledge": {**BASE["knowledge"], "scope": None}}
    assert check_deviation(base, {"knowledge": {"scope": {"projects": ["ANY"]}}}, CONNECTION_RULES)[
        "knowledge"]["scope"] == {"projects": ["ANY"]}


def test_a_stored_deviation_that_became_wider_is_clamped_on_read() -> None:
    stored = {"knowledge": {"scope": {"projects": ["BRD", "OPS"]}, "schedule": "hourly"},
              "agent_tools": {"level": "read"}}
    narrowed = {**BASE, "knowledge": {**BASE["knowledge"], "scope": {"projects": ["BRD"]}, "schedule": "daily_0600"},
                "agent_tools": {"level": "off"}}
    result = effective(SELECTED, "ws-a", narrowed, stored, CONNECTION_RULES)
    assert result.effective["knowledge"]["scope"] == {"projects": ["BRD"]}
    assert result.effective["knowledge"]["schedule"] == "daily_0600"
    assert result.effective["agent_tools"]["level"] == "off"
    assert result.deviation == stored, "the stored deviation is reported as it is"
