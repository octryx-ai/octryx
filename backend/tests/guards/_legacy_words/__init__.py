"""The approved occurrences of the legacy words, one file per concept; each is bound to its file, its enclosing
definition and its whole line."""

from __future__ import annotations

from tests.guards._legacy_words.deprecated import DEPRECATED_FACT, DEPRECATED_STATE
from tests.guards._legacy_words.formats import CUSTOMER_LEGACY_FILES, EXTERNAL_FORMAT, VENDOR_TEXT
from tests.guards._legacy_words.retired_state_backend import RETIRED_STATE_BACKEND
from tests.guards._legacy_words.retired_state_frontend import RETIRED_STATE_FRONTEND
from tests.guards._legacy_words.shadow_decision import SHADOW_DECISION
from tests.guards._support import Accepted

ALLOWED_WORDS: tuple[Accepted, ...] = (
    *RETIRED_STATE_BACKEND, *RETIRED_STATE_FRONTEND, *DEPRECATED_FACT, *DEPRECATED_STATE, *VENDOR_TEXT,
    *SHADOW_DECISION, *EXTERNAL_FORMAT, *CUSTOMER_LEGACY_FILES,
)
