"""The ``platform_model_call`` fixture: a test that calls a provider driver directly runs as the platform.

Every driver call needs a model call scope (``content_security.model_call_scope``); an unscoped call is refused.
Production callers set the scope at their dispatch site (``tests/content_security/test_model_call_scope_guard.py``).
A driver test with no caller in front of it requests this fixture (``pytestmark = pytest.mark.usefixtures(...)``)
and runs as a session without a Workspace, so the shipped defaults apply.

``fresh_report_evidence`` (autouse): the wrapper records a report once per text and scope in a process
(``model_call_fields.REPORTED``); every test starts without that evidence.
"""

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
