"""The deviation rules of a connection: which fields of which use a Workspace may narrow, and how.

``knowledge`` and ``tickets``: enabled (on → off), scope (subset per scope key), schedule (same or ``manual``);
``tickets.write_back`` (on → off); ``agent_tools.level`` (``off`` < ``read`` < ``write``). Anything else is no
deviation (``422 deviation_not_narrower``).
"""

from __future__ import annotations

from .effective import FieldRules
from .narrowing import narrow_flag, narrow_level, narrow_schedule, narrow_scope

CONNECTION_RULES: FieldRules = {
    "knowledge": {"enabled": narrow_flag, "scope": narrow_scope, "schedule": narrow_schedule},
    "tickets": {"enabled": narrow_flag, "scope": narrow_scope, "schedule": narrow_schedule,
                "write_back": narrow_flag},
    "agent_tools": {"level": narrow_level},
}

__all__ = ["CONNECTION_RULES"]
