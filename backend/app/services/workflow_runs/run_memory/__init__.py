"""Run memory per repository and app, stage 1.

A colleague who keeps doing the same work and starts from zero is not a good colleague: what a run learns
and the platform verified is kept on the repository record per app and given to the next run's phase brief as
information (never a permission): the commands that ran green in the platform's own pipeline, the environment errors
that paused a run and what ran past them, and the refused calls with the call that worked next. The kinds, bounds and
reasons are data (``run_memory.json``); the code only captures at event time and reads at a phase's entry.
"""

from .capture import denial_answered, environment_failed, large_outputs, pipeline_green
from .store import entered, for_brief

__all__ = ["denial_answered", "entered", "environment_failed", "for_brief", "large_outputs", "pipeline_green"]
