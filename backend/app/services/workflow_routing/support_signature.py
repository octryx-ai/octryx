"""Support-request error-signature classifier (the one allowed matcher).

The explicit-workflow-selection plan removes every keyword-intent guess from
routing. The single deliberate exception is this classifier: it recognizes
**factual error signatures** in the user message (stack traces, exception
names, timeout/error phrasings, incident wording) and classifies the turn's
*intent* as ``support_request``. It never selects a workflow, never widens
the toolset beyond the knowledge-style read-only path, and has its own
config switch so operators can disable it independently of the routing mode.

Config key ``support_request_signature_classifier``: ``enabled`` (default) |
``disabled``. Unknown values report and use the default.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config.values import get_system_config_value

logger = logging.getLogger(__name__)

SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY = "support_request_signature_classifier"
SUPPORT_REQUEST_SIGNATURE_ENABLED = "enabled"
SUPPORT_REQUEST_SIGNATURE_DISABLED = "disabled"
_KNOWN_SWITCH_VALUES = {SUPPORT_REQUEST_SIGNATURE_ENABLED, SUPPORT_REQUEST_SIGNATURE_DISABLED}

# Factual error signatures only — no product names, no topic guessing.
SUPPORT_REQUEST_SIGNATURE_PATTERN = re.compile(
    (
        r"\b("
        r"support request|support ticket|support case|we have the following support request|"
        r"error message|caught exception|read timed out|timed out|stack trace|stacktrace|"
        r"sql server exception|sqlserverexception|simul(?:ate|ation)|incident|simulation failed|"
        r"error during|got an error|got a timeout|i am seeing"
        r")\b"
    ),
    re.IGNORECASE,
)


async def support_request_signature_enabled(db: AsyncSession | None) -> bool:
    """Read the classifier switch; without a db handle the default applies."""
    if db is None:
        return True
    raw_value = (
        str(await get_system_config_value(db, SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY) or "").strip().lower()
    )
    if raw_value in _KNOWN_SWITCH_VALUES:
        return raw_value == SUPPORT_REQUEST_SIGNATURE_ENABLED
    if raw_value:
        logger.warning(
            "%s config value %r is not one of %s; using %r",
            SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
            raw_value,
            sorted(_KNOWN_SWITCH_VALUES),
            SUPPORT_REQUEST_SIGNATURE_ENABLED,
        )
    return True


def match_support_request_signature(text: str) -> bool:
    return bool(SUPPORT_REQUEST_SIGNATURE_PATTERN.search(str(text or "")))


__all__ = [
    "SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY",
    "SUPPORT_REQUEST_SIGNATURE_DISABLED",
    "SUPPORT_REQUEST_SIGNATURE_ENABLED",
    "SUPPORT_REQUEST_SIGNATURE_PATTERN",
    "match_support_request_signature",
    "support_request_signature_enabled",
]
