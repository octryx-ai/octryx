"""Session metadata for tests that drive ``run_agent`` directly as a programmatic caller.

A ``run_agent`` caller must declare its profile origin: a turn without a workflow, parent run,
declaration, agent definition or chat routing resolution is ``needs_configuration``.

- ``DECLARED_CHANGE_RUN``: the coding loop the way a schedule that declares
  ``capability_class: change`` starts it.
- ``UNDECLARED_READ_ONLY_RUN``: a caller whose declaration record declares no class, which runs
  ``read_only`` (``source: undeclared_read_only``). Tests of loop mechanics use it to run exactly
  as they did before an origin was mandatory.
"""

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
