"""Combined queue mixin for the scheduler."""

from __future__ import annotations

from .mixins import SchedulerDispatchMixin
from .registration import SchedulerRegistrationMixin


class SchedulerQueueMixin(SchedulerRegistrationMixin, SchedulerDispatchMixin):
    """Combined mixin used by the scheduler implementation."""

    pass
