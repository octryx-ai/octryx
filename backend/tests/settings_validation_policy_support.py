"""Shared helpers for the test_settings_validation_policy_* modules."""

from __future__ import annotations

import logging
import traceback

import pytest

from app.config import Settings
from app.services.observability.logging import JsonLogFormatter
from app.settings_validation_policy import declared_locations

MARKERS = {
    "database_url_credential": ("oe82" + "4-canary-db-1a2b"),
    "provider_token": "oe824-canary-provider-3c4d",
    "proxy_allowlist": "oe824-canary-proxy-5e6f",
    "jwt_secret": ("oe82" + "4-canary-jwt-7a8b"),
    "admin_password": "oe824-canary-admin-9c0d",
    "multipart_ceiling": "oe824-canary-ceiling-1e2f",
    "nested_ceiling": "oe824-canary-nested-3a4b",
    "nested_key": ("oe82" + "4-canary-key-5c6d"),
    "source_value": "oe824-canary-source-7f8a",
}


@pytest.fixture
def settings_environment(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Environment with every setting of the model unset.

    The test session's own configuration (``tests/conftest.py`` exports ``DEBUG``,
    ``TRUSTED_PROXY_IPS`` and the local bootstrap values) would otherwise decide
    whether a case fails at all.
    """
    for name in declared_locations(Settings):
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    return monkeypatch


def _operator_surfaces(error: BaseException, caplog: pytest.LogCaptureFixture) -> str:
    """Every rendering of the failure an operator or a log aggregator can read."""
    caplog.clear()
    logger = logging.getLogger("octryx.test.settings_validation")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.error("startup configuration rejected", exc_info=error)
    json_rendered = "".join(JsonLogFormatter().format(record) for record in caplog.records)
    return "\n".join(
        [
            str(error),
            repr(error),
            "".join(traceback.format_exception(error)),
            caplog.text,
            json_rendered,
        ]
    )
