"""A turn that a platform content policy refused ends with the content-refusal answer, not a provider failure."""

from __future__ import annotations

from app.agent.core.runtime.runtime_errors import CLASSIFICATION_SOURCE_EXPLICIT, RUNTIME_ERROR_CONTENT_POLICY_DENIED
from app.agent.loops.runtime._loop_runtime_turn_failure import _runtime_unreachable_user_message
from app.services.prompt_catalog import render_prompt


def _attempt(error_class: str, source: str = CLASSIFICATION_SOURCE_EXPLICIT) -> dict:
    return {"status": "error", "error_class": error_class, "error_class_source": source}


def test_a_content_policy_refusal_gets_the_content_refusal_answer():
    message = _runtime_unreachable_user_message([_attempt(RUNTIME_ERROR_CONTENT_POLICY_DENIED)])
    assert message == render_prompt("answer.content.refused")
    assert "content policy" in message


def test_a_refusal_next_to_a_provider_failure_keeps_the_provider_outcome():
    assert _runtime_unreachable_user_message(
        [_attempt(RUNTIME_ERROR_CONTENT_POLICY_DENIED), _attempt("provider_error", "inferred")]) is None
