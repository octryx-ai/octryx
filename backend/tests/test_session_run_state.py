from app.services.session.run_state import infer_completion_reason_from_content


def test_infer_completion_reason_marks_agent_stop_as_stopped():
    assert (
        infer_completion_reason_from_content(
            "Agent stopped because the selected runtime kept producing transition text."
        )
        == "agent_stopped"
    )


def test_infer_completion_reason_keeps_normal_answer_completed():
    assert infer_completion_reason_from_content("The deployment is healthy.") == "completed"
