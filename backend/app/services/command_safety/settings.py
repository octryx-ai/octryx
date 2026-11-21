"""Command safety: one contract for the command risk gate (Settings → Security → Command safety).

The gate checks every shell, kubectl and script command an agent wants to run; the strictest check wins (allow, ask a
person, block). This module is the one read/write contract of its configuration:

- the checks (the analyzer chain ``agent.security_analyzer_chain``; order does not matter, the strictest wins) and the
  AI risk review (timeout, ask-a-person and block thresholds; ``0`` is a value) in ``system_config``;
- the command lists (always blocked patterns, the read-only lists of diagnosis runs, shell risk operators) and the
  agent guard rules (on/off per rule) in the global ``exec_policy_configs`` row;
- per Workspace, *Inherit* or *Override*: the checks and thresholds in the Workspace's ``runtime_policy.default_bundle``
  (the existing runtime override path) and the command lists in one Workspace exec-policy row that holds only the
  overriding keys, so later platform edits still reach every other key.

Both stores are written in the caller's transaction (one commit). The review *model* is the platform's security
review task model, shown read-only with a link (Runtime owns model choice).
"""

from __future__ import annotations

__all__ = []
