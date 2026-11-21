"""A change of plan goes back with the work of its time (``workflow_runs.wip_reset``): back in reproduce, the fix
phase's code must not stay and hide the bug."""

from types import SimpleNamespace

from app.services.workflow_runs.wip_reset import (
    note_phase_entry,
    pending_reset,
    request_reset,
    reset_reported,
)
from app.services.workflow_runs.workspace.gateway import _clean

A, B, C = "a" * 40, "b" * 40, "c" * 40
PHASES = ["intake", "reproduce", "fix"]


def test_the_checkpoint_of_the_phase_after_the_plan_node_is_the_reset_and_the_report_clears_it():
    run = SimpleNamespace(context={"wip": {"sha": A}})
    note_phase_entry(run, "reproduce")
    run.context = {**run.context, "wip": {"sha": B}}
    note_phase_entry(run, "fix")  # the work as reproduce left it
    run.context = {**run.context, "wip": {"sha": C}}  # the fix's work
    assert request_reset(run, "reproduce", PHASES) == B and pending_reset(run) == B
    report = _clean({"wip_reset": {"state": "done", "sha": B, "files": 2, "backup": ".git/octryx-reset-backup/bbbb"}})
    assert reset_reported(run, report)["files"] == 2 and pending_reset(run) == ""


def test_without_a_checkpoint_or_with_another_reset_nothing_happens():
    run = SimpleNamespace(context={})
    assert request_reset(run, "reproduce", PHASES) == "" and pending_reset(run) == ""
    run = SimpleNamespace(context={"wip_at_entry": {"fix": B}, "wip_reset": {"sha": B}})
    assert reset_reported(run, {"wip_reset": {"state": "done", "sha": A}}) is None and pending_reset(run) == B
    assert reset_reported(run, {"wip_reset": {"state": "failed", "sha": B}}) is None
