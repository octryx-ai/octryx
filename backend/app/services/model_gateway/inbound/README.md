# Inbound model gateway

Model routes of launcher-started coding agents. Governed routes (`service`, `openai_service`) relay to the LiteLLM
gateway; seat routes (`seat`, `codex_seat`) relay to the person's own subscription.

## Invariants

- Governed calls authenticate upstream with the provider's virtual key; of the client's request headers only
  `anthropic-version` and `anthropic-beta` are forwarded (`upstream.py`).
- Seat relays forward only allowlisted request headers, over clients with `trust_env=False` and no redirects
  (`seat_upstream.py`, `codex_seat_upstream.py`).
- The content decision these routes use, `content_security.enforcement_inbound.enforce_inbound`, applies the
  Workspace's content handling as on the platform's own model calls: refuse, mask, reroute to the governance alias
  (a Claude Code seat request then goes to the company route; a ChatGPT seat refuses), or send unchanged and record.
