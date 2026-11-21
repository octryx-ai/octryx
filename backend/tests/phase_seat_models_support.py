"""The phase's model on the seat: a seat that may take the turn and a Workspace that admits chosen models."""

from __future__ import annotations

import pytest

from app.services.devices.dispatch_gate import DispatchDecision

HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"


@pytest.fixture
def seat_admitted(monkeypatch):
    """The seat may take the turn (the Workspace's seat decision is not what these tests are about) and the
    Workspace admits the models in ``admitted``."""
    from app.services.devices import chat_turn

    admitted = {"models": {"", HAIKU, OPUS}}

    async def dispatch(*_a, **_k):
        return DispatchDecision(True)

    async def model_check(*_a, model: str = "", **_k):
        return None if model in admitted["models"] else ("denied", "device_model_not_allowed")

    monkeypatch.setattr(chat_turn, "check_device_dispatch", dispatch)
    monkeypatch.setattr(chat_turn, "check_device_model", model_check)
    return admitted
