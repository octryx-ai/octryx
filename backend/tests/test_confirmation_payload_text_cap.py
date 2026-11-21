"""A long interview card is never cut silently (e.g. at 4000 of 7327 characters)."""

from types import SimpleNamespace

from app.services.workflow_runs.confirmation_payloads import MAX_PAYLOAD_TEXT, _last_answer, capped


def _run(answer: str) -> SimpleNamespace:
    return SimpleNamespace(context={"answers": {"interview": answer}, "last_phase": "interview"})


def test_a_real_interview_answer_reaches_the_card_whole():
    answer = "Q1 ...\n" + "x" * 7300 + "\n12. last question\nDefaults:\n- a\n- b"
    assert _last_answer(_run(answer), "interview") == answer


def test_a_cut_is_never_silent():
    answer = "y" * (MAX_PAYLOAD_TEXT + 1234)
    shown = _last_answer(_run(answer), "interview")
    assert shown.startswith("y" * MAX_PAYLOAD_TEXT)
    assert shown.endswith("(truncated, 1,234 more characters)")
    assert capped("short", 10) == "short"
