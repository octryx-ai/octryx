"""The Octryx pet without a tray."""

from __future__ import annotations

from datetime import timedelta

import pytest

from octryx_claude.pet import settings as pet_settings
from octryx_claude.pet.display import OFFLINE, SIGNED_OUT, Notifier, present
from octryx_claude.pet.model import PetItem, PetState, parse
from octryx_claude.pet.schedule import Schedule
from tests.pet_support import NOON, _pet

# --- model -----------------------------------------------------------------------------------------------------


def test_parse_never_raises_and_keeps_only_safe_values():
    assert parse(None).state == "unknown" and parse([]).state == "unknown"
    assert parse({"state": "dancing"}).state == "unknown"
    pet = parse({
        "state": "problem", "reason": "Loop limit!", "count": "3", "headline": "a\nb" + "x" * 200,
        "items": [{"id": "run:1", "kind": "problem", "title": 5, "url": "javascript:alert(1)"},
                  {"id": "", "title": "no id"}, "junk",
                  {"id": "done:2", "kind": "Bad Kind", "title": "ok", "url": "//evil.example/x"}],
        "panel_url": "ftp://x", "poll_after_seconds": True, "quiet": {"active": "yes", "until": "x"},
    })
    assert pet.reason is None and pet.count == 2 and pet.headline.startswith("a b") and len(pet.headline) == 80
    assert [(item.id, item.kind, item.title, item.url) for item in pet.items] == [
        ("run:1", "problem", "5", None), ("done:2", "", "ok", None)]
    assert pet.panel_url == "/chat" and pet.poll_after_seconds is None and not pet.quiet_active
    assert parse({"state": "needs_you", "reason": "loop_limit"}).reason is None
    assert parse({"state": "done", "items": {"id": "x"}}).items == ()


# --- schedule --------------------------------------------------------------------------------------------------


def test_the_schedule_follows_the_hint_and_backs_off():
    schedule = Schedule(rand=lambda: 0.5)  # jitter factor 1.0
    assert schedule.after_answer("needs_you", 30) == 30
    assert schedule.after_answer("working", None) == 30 and schedule.after_answer("resting", None) == 60
    assert schedule.after_answer("unknown", None) == 60
    assert schedule.after_answer("done", 1) == 5 and schedule.after_answer("done", 10_000) == 900
    assert [schedule.after_failure() for _ in range(7)] == [15, 30, 60, 120, 240, 300, 300]
    assert schedule.after_answer("done", None) == 60 and schedule.failures == 0
    assert Schedule(rand=lambda: 0.0).after_failure() == 7.5
    assert schedule.after_signed_out() == 300


# --- settings --------------------------------------------------------------------------------------------------


def test_no_quiet_hours_by_default_and_the_person_sets_them(tmp_path):
    current = pet_settings.load(tmp_path)
    assert current.notifications and not current.quiet_hours.enabled
    assert not current.quiet_hours.active(NOON.replace(hour=23))
    evening = pet_settings.with_quiet_hours(current, enabled=True, window=pet_settings.parse_window("19:00-08:00"))
    pet_settings.save(tmp_path, evening)
    loaded = pet_settings.load(tmp_path)
    assert loaded.quiet_hours.enabled and loaded.quiet_hours.label() == "19:00–08:00"
    assert [loaded.quiet_hours.active(NOON.replace(hour=hour)) for hour in (7, 8, 12, 18, 19, 23)] == [
        True, False, False, False, True, True]
    lunch = pet_settings.QuietHours(enabled=True, start="12:00", end="13:00")
    assert lunch.active(NOON) and not lunch.active(NOON.replace(hour=13))
    assert pet_settings.parse_window("25:00-08:00") is None and pet_settings.parse_window("08:00-08:00") is None
    (tmp_path / "pet.json").write_text("{broken", encoding="utf-8")
    assert pet_settings.load(tmp_path) == pet_settings.PetSettings()


# --- display and notifications ---------------------------------------------------------------------------------


def test_present_states_and_connections():
    assert present(None, SIGNED_OUT).status == SIGNED_OUT
    assert present(None, OFFLINE).status == OFFLINE and present(None, "ok").status == "resting"
    needs = present(_pet("needs_you", "a", "b"), "ok")
    assert needs.header == "Needs you (2)" and needs.tooltip == "Octryx: Needs you (2)\nTitle a"
    offline = present(_pet("needs_you", "a"), OFFLINE)
    assert offline.status == OFFLINE and offline.items and offline.header.startswith("Offline, retrying (last:")
    assert present(_pet("resting"), "ok").header == "All quiet"


def test_only_new_actions_and_results_notify():
    notifier, quiet = Notifier(), pet_settings.PetSettings()
    assert notifier.after(_pet("needs_you", "a"), quiet, now=NOON) == []  # first answer: remember only
    [one] = notifier.after(_pet("needs_you", "a", "b"), quiet, now=NOON)
    assert (one.title, one.message, one.url) == ("Octryx: Needs you", "Title b", "/chat?session_id=b")
    assert notifier.after(_pet("needs_you", "a", "b"), quiet, now=NOON) == []
    [many] = notifier.after(_pet("done", "c", "d"), quiet, now=NOON)
    assert many.message == "2 new: Title c" and many.url == "/chat"
    working = PetState("working", items=(PetItem("running:r", "run", "Run", None),), count=1)
    assert notifier.after(working, quiet, now=NOON) == []
    assert notifier.after(_pet("resting"), quiet, now=NOON) == []


@pytest.mark.parametrize("case", ["off", "paused", "own_quiet", "platform_quiet"])
def test_no_notification_while_off_paused_or_quiet(case):
    notifier = Notifier(started=True)
    current = pet_settings.PetSettings(notifications=case != "off")
    if case == "own_quiet":
        current = pet_settings.with_quiet_hours(current, enabled=True, window=("11:00", "13:00"))
    pet = _pet("problem", "x", quiet_active=case == "platform_quiet")
    paused = NOON + timedelta(minutes=30) if case == "paused" else None
    assert notifier.after(pet, current, now=NOON, paused_until=paused) == []
    assert notifier.after(_pet("problem", "y"), pet_settings.PetSettings(), now=NOON)  # seen "x" anyway
