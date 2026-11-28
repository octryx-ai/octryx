"""The ``platform_model_call`` fixture: a test that calls a provider driver directly runs as the platform."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services.content_security.model_call_fields import REPORTED
from app.services.content_security.model_call_scope import model_call_scope, session_call


@pytest.fixture
def platform_model_call() -> Iterator[None]:
    with model_call_scope(session_call(None)):
        yield


@pytest.fixture(autouse=True)
def fresh_report_evidence() -> Iterator[None]:
    REPORTED.clear()
    yield
    REPORTED.clear()


__all__ = ["fresh_report_evidence", "platform_model_call"]
