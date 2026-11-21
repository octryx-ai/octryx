"""The phase answer a confirmation shows keeps the question round when a later pass only refers back to it."""
from types import SimpleNamespace

from app.services.workflow_runs.octryx.stop_answers import phase_answer, question_round_phase

QUESTIONS = "Here is the one question round.\n1. Who uses it? Proposed: families.\n" + "\n".join(
    f"{n}. Question {n}? Proposed: yes." for n in range(2, 13)) + "\n\nDefaults I will use\nD1. Euro prices."
BACK_REFERENCE = "The read checks are done. My question round above stands as the final answer for this phase."


def _run(entry=1):
    return SimpleNamespace(context={}, node_state={"entry": entry})


def test_a_short_back_reference_keeps_the_earlier_question_round():
    # A card that shows only the back reference would hide all 12 questions.
    run = _run()
    phase_answer(run, "interview", None, QUESTIONS)
    shown = phase_answer(run, "interview", None, BACK_REFERENCE)
    assert "12. Question 12?" in shown and "D1. Euro prices." in shown
    assert shown.endswith(BACK_REFERENCE)


def test_a_restated_full_answer_supersedes_the_earlier_one():
    run = _run()
    phase_answer(run, "readiness", None, "T1. old task - proof test_a")
    restated = "T1. new task - proof test_a\nT2. second task - proof test_b"
    assert phase_answer(run, "readiness", None, restated) == restated


def test_a_new_entry_of_the_phase_starts_fresh():
    run = _run(entry=1)
    phase_answer(run, "interview", None, QUESTIONS)
    run.node_state = {"entry": 2}
    assert phase_answer(run, "interview", None, BACK_REFERENCE) == BACK_REFERENCE


def _node(workflow_class):
    return SimpleNamespace(config={"workflow_contract": {"workflow_class": workflow_class}})


def test_only_the_spec_interview_keeps_earlier_answers():
    assert question_round_phase(_node("spec_interview"))
    # Any other question phase (a readiness check) keeps "last answer wins": a shorter corrected task
    # list must not get the old list back in front of it.
    assert not question_round_phase(_node("readiness_check"))
    assert not question_round_phase(_node("coding_change"))
