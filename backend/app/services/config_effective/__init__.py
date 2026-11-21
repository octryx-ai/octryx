"""``effective(object, workspace)`` and the per-field "narrower" rules.

Pure: no database access. The connections API (``services/connections``) reads what applies in a Workspace
through this function.
"""

from .connection_rules import CONNECTION_RULES
from .effective import (
    AVAILABLE_ALL,
    AVAILABLE_SELECTED,
    Effective,
    Subject,
    available,
    check_deviation,
    effective,
)
from .narrowing import CODE_DEVIATION_NOT_NARROWER, LEVELS, DeviationNotNarrowerError

__all__ = [
    "AVAILABLE_ALL",
    "AVAILABLE_SELECTED",
    "CODE_DEVIATION_NOT_NARROWER",
    "CONNECTION_RULES",
    "LEVELS",
    "DeviationNotNarrowerError",
    "Effective",
    "Subject",
    "available",
    "check_deviation",
    "effective",
]
