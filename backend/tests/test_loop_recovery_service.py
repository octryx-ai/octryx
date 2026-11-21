from app.services.loop_recovery import plan_loop_recovery
from app.services.loop_recovery import plan_loop_recovery as package_plan_loop_recovery


def test_plan_loop_recovery_root_shim_matches_package_export():
    assert plan_loop_recovery is package_plan_loop_recovery


def test_plan_loop_recovery_moves_to_next_step_when_followups_exist():
    recovery = plan_loop_recovery(
        event={"kind": "repetitive_tool_loop", "message": "Step is stuck."},
        step={"name": "Investigate"},
        has_followup_steps=True,
        wrapup_forced=False,
    )

    assert recovery["action"] == "move_to_next_step"
    assert "Move to the next step now." in recovery["system_message"]


def test_plan_loop_recovery_stops_duplicate_no_tool_response():
    recovery = plan_loop_recovery(
        event={"kind": "duplicate_no_tool_response", "message": "Same response repeated."},
        step={"name": "Summarize"},
        has_followup_steps=False,
        wrapup_forced=False,
    )

    assert recovery["action"] == "stop_run"
    assert "same no-tool response" in recovery["final_content"]


def test_plan_loop_recovery_forces_wrapup_on_final_step():
    recovery = plan_loop_recovery(
        event={"kind": "repetitive_tool_loop", "message": "Step is stuck."},
        step={"name": "Final analysis"},
        has_followup_steps=False,
        wrapup_forced=False,
    )

    assert recovery["action"] == "force_wrapup"
    assert "Stop researching and conclude the current step now" in recovery["system_message"]
