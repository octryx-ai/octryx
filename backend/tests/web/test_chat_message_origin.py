"""The platform's message that continues a workflow run is marked as such (it must not show under the person's
name); every other message carries no origin."""

from types import SimpleNamespace

from app.web._helpers.workspace import message_origin


def test_a_workflow_continuation_is_marked_and_nothing_else():
    def message(role, key):
        return SimpleNamespace(role=role, idempotency_key=key, model=None)

    assert message_origin(message("user", "workflow_continuation:run-1:implement")) == "workflow"
    assert message_origin(message("user", None)) is None
    assert message_origin(message("user", "send-abc")) is None
    assert message_origin(message("assistant", "workflow_continuation:run-1:implement")) is None


def test_a_device_answer_is_marked_also_when_it_names_its_model():
    def answer(key, model):
        return SimpleNamespace(role="assistant", idempotency_key=key, model=model)

    assert message_origin(answer("device_job:dj_1:t1", "claude-haiku-5-5")) == "device"
    assert message_origin(answer(None, "device:seat")) is None  # only the device answer key marks it
    assert message_origin(answer(None, "gemma-4-31b")) is None


def test_the_platform_git_turn_of_a_team_run_is_marked_platform():
    def message(role, key):
        return SimpleNamespace(role=role, idempotency_key=key, model=None)

    assert message_origin(message("user", "teamwork:git:run-1:3")) == "platform"
    assert message_origin(message("user", "teamwork:other:run-1")) is None
