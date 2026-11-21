"""A step keeps going while it makes progress and stops on a loop (a fixed call count would stop a server chat
that creates six work items after four)."""

from app.services.elastic_iteration import compute_elastic_step_iteration_limit
from app.services.elastic_iteration.service import MAX_PROGRESS_EXTENSION, loop_detected, recent_progress

STEP = {"name": "Answer", "stepType": "chat"}
SETTINGS = {"elastic_iteration_enabled": True}


def _limit(history, base=8):
    return compute_elastic_step_iteration_limit(step=STEP, base_limit=base, step_tool_history=history,
                                                wrapup_forced=False, runtime_settings=SETTINGS)


def _create(n):
    return {"tool_name": "work_item_create", "params": {"title": f"Ticket {n}"}, "result": {"source_key": f"OCX-{n}"}}


def test_new_successful_calls_at_the_limit_extend_it():
    history = [{"tool_name": "knowledge_projects", "params": {}, "result": {}}] + [_create(n) for n in range(1, 8)]
    assert recent_progress(history) and not loop_detected(history)
    result = _limit(history)
    assert result["reason"] == "progress" and result["effective_limit"] == len(history) + 2


def test_the_same_call_three_times_is_a_loop_and_gets_no_extension():
    history = [_create(1), _create(2), _create(1), _create(3), _create(1), _create(4), _create(5)]
    assert loop_detected(history)
    assert _limit(history) == {"base_limit": 8, "bonus": 0, "effective_limit": 8, "reason": "loop_detected"}


def test_four_errors_in_a_row_is_a_loop():
    failing = [{"tool_name": "work_item_create", "params": {"title": f"T{n}"}, "result": {"error": "403"}}
               for n in range(4)]
    assert loop_detected([_create(1), *failing])


def test_the_extension_has_a_hard_ceiling():
    history = [_create(n) for n in range(1, 60)]
    assert _limit(history)["effective_limit"] == 8 + MAX_PROGRESS_EXTENSION


def test_no_new_successful_call_in_the_last_calls_gets_no_progress_extension():
    error = [{"tool_name": "read_workspace_file", "params": {"path": f"x{n}"}, "result": {"error": "missing"}}
             for n in range(2)]
    history = [_create(1), _create(2), _create(3), _create(1), _create(2), _create(3), *error]
    assert not loop_detected(history) and not recent_progress(history)
    assert _limit(history)["reason"] != "progress"
