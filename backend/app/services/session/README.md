# Chat sessions

Chat sessions and their turns: one turn preparation for both entry paths (`/chat/api` and
`/api/v1/sessions/{id}/messages`), the execution gate, approvals, stop and settlement, and the per-turn execution
record a trace explains a turn with.

## Invariants

- A prepared turn whose execution profile is missing, has an unknown status or is not `allowed` is held with an
  explicit answer and never handed to a runner (`execution_gate.evaluate_execution_gate`,
  `turn_handoff.held_by_gate`).
- An approval is decided by a user who may write its session (or by a platform admin from the admin panel), and only
  once: a later decision is `approval_already_resolved` (`approval_decision.decide_session_approval`).
- A record that belongs to a session is readable and actionable exactly by those who may read or write the session;
  one they cannot see answers 404 (`resource_access.py`, `collaboration.require_session_access`).
- A repeated send with the same idempotency key from the same user starts no second turn (`send_idempotency.py`).
- A `running` session whose owning process holds no live lease is settled as `interrupted_by_restart`; no other
  status is touched (`turn_interruption.settle_orphaned_running_sessions`).
