"""The explicit tool surface of an Agent Definition.

An agent declares whether its turns work with tools at all:

``governed`` (default)
    Today's behaviour, unchanged: the turn's tool surface comes from the explicit sources in
    ``agent/core/context/turn_tool_surface.py`` (selected workflow, the agent's steps, Workspace
    policy, governed default set). Every activation, approval and policy gate applies.
``none``
    Text only. This is a deny boundary, not a hint. The turn offers no tool definitions and no
    workflow capability catalog. Tool dispatch refuses every call, including model-fabricated,
    text-derived and platform-forced calls. The turn never widens the surface on its own:
    - a turn that would select a workflow surface stops as ``needs_configuration`` before any
      model call;
    - so does an agent with steps that need tools.

Key mapping (the one contract every layer uses):

- database column and revision snapshot / export package: ``tool_surface``;
- canonical runtime payload and panel read payload: ``toolSurface``;
- panel write body: ``tool_surface``.

Missing versus present is the one distinction every adapter keeps:

- Missing key: it means ``governed`` (snapshots and exports omit it for ``governed``). This applies only to
  a snapshot, export package, write body or runtime payload that has no key at all.
- Present key: taken verbatim. ``null``, ``""``, ``" none"`` or any other value outside the enum
  is never coerced to ``governed``:
  - writes, import and restore refuse it;
  - projections (runtime payload, snapshot) carry it unchanged, so publication validation
    refuses it and the runtime fails closed. The turn offers no tools, dispatch refuses, and
    the execution gate stops the turn as ``needs_configuration``.

Snapshots and exports omit the key for ``governed``, the default tool surface, so a governed revision's
checksum does not depend on the field. The column is NOT NULL with default ``governed``; ``None`` exists
only on an unflushed object before the column default applies, and it is read as ``governed``. A persisted row
can never hold ``None``, and a persisted empty or unknown string fails closed.
"""

from __future__ import annotations

__all__ = []
