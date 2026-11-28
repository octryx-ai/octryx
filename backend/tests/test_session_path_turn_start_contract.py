"""Both session entry paths start a turn through ``services/session/turn_start`` with the same start facts;
only the refusal body differs."""

from __future__ import annotations

import pytest

from app.api.routes.sessions._sessions_turn_routes import api_refusal_http_exception
from app.services.session.turn_refusals import REFUSAL_HTTP_STATUS, TurnRefusal, TurnRefusalState
from app.web._helpers.chat_turn_prepare import chat_refusal_http_exception

PROMPT = "What time is it?"
PATHS = ("api-v1", "chat-api")


@pytest.mark.parametrize("state", list(TurnRefusalState))
def test_each_refusal_state_maps_to_one_status_on_both_adapters(state):
    refusal = TurnRefusal(state=state, detail="operator detail")

    chat = chat_refusal_http_exception(refusal)
    api = api_refusal_http_exception(refusal)

    assert chat.status_code == api.status_code == REFUSAL_HTTP_STATUS[state]
    assert chat.detail == "operator detail"
    assert api.detail == {"code": state.value, "detail": "operator detail"}
