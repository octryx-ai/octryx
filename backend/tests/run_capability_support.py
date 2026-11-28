"""Session metadata for tests that drive ``run_agent`` directly as a programmatic caller."""

from __future__ import annotations

from app.services.run_capability.declared import (
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_SCHEDULE_DEFINITION,
    SOURCE_UNDECLARED_READ_ONLY,
)

DECLARED_CHANGE_RUN = {DECLARED_RUN_CAPABILITY_METADATA_KEY: {"class": "change", "source": SOURCE_SCHEDULE_DEFINITION}}
UNDECLARED_READ_ONLY_RUN = {
    DECLARED_RUN_CAPABILITY_METADATA_KEY: {"class": "read_only", "source": SOURCE_UNDECLARED_READ_ONLY}
}

__all__ = ["DECLARED_CHANGE_RUN", "UNDECLARED_READ_ONLY_RUN"]
