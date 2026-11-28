# Agent Gateway

The control plane for external coding clients started through the `octryx-claude` launcher: their identity, shadow
session, presence, tool decisions, execution evidence, verification and Workspace policy.

## Invariants

- A gateway token is accepted only for the `octryx-model-gateway` audience, with the `model:invoke` scope and an
  active user (`identity.resolve_gateway_login`).
- A call acts only in a Workspace the user can access at call time and the token's grant allows (`identity.py`,
  `seat_credential.resolve_seat_identity`).
- A launcher session key presented by another user or for another Workspace is refused (`sessions.py`).
- A session's hook key is registered once and stored encrypted (`hook_key.register_hook_key`).
- The issuance row of a confirmation or decision ticket stores the ticket's SHA-256 digest, not the ticket
  (`confirmation.ask_for_confirmation`, `decision_confirmation.ask_for_decision`).
- A confirmation or decision ticket is redeemed at most once (`confirmation.consume_ticket`).
- A seat registration stores the credential's SHA-256 digest, not the credential (`presence.register_session`,
  `seat_credential.mint_credential`).
- The self-protection rules decide before any Workspace rule, and no Workspace setting turns them off
  (`self_protection.py`, `tool_decision.decide_tool_check`).
- A tool no rule names is refused in a read-only session or run phase; in a working session or run phase it follows
  the Workspace's unknown_tools setting (allow and log, or deny), except tools listed in allowed_tools
  (`capability.unknown_tool_decision`, `workflow_runs/octryx/tool_policy`).
