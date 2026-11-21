"""Standing approvals: "Always for this Workspace" on the one governed approval record.

A pending session approval is decided once ("Allow once" / "Deny") or, by a Workspace admin or
owner, *for good* ("Always for this Workspace"). "Always" records a revocable, audited standing
rule in the Workspace config and then approves the same record: a **tool approval** records
``standing_tool_approvals.rules``: Workspace + tool, plus the exec-policy argument class for command
tools (``tool_rules``, ``argument_class``).

``permission`` decides who may grant (and therefore who sees the button); ``decision`` is the one
entry point every surface uses (the chat card, ``/chat/api/approvals/{id}/always``,
``/api/v1/approvals/{id}/always``, the Claude Code gateway).
"""
