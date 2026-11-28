# Session routes

Approvals, clarifications, the attention queue, call agents, tool approval policies and session transcripts. The
rules live in `services/session`, `services/approval` and `services/tool_approval`.

## Invariants

- An approval is listed and looked up by id under one visibility rule, so out of scope and unknown are the same 404
  (`approvals.py`, `services/approval/access.approval_visibility_clause`).
