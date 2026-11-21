"""Combined dispatch mixin."""

from __future__ import annotations

from .backend import SchedulerDispatchBackendMixin
from .loop import SchedulerDispatchLoopMixin


class SchedulerDispatchMixin(SchedulerDispatchBackendMixin, SchedulerDispatchLoopMixin):
    """Combined queue dispatch mixin."""

    pass
