# Content security

The Workspace's content handling (what to do per kind of finding) and its enforcement: a platform model call
(`enforcement_call.enforce_call`) and a coding agent's gateway request (`enforcement_inbound.enforce_inbound`). The
two share one detector pass, one masker (`transport.py`, the walkers in `format_chat_messages.py` and
`format_request_body.py`) and one obligation resolution; where they differ on purpose is named in `enforcement.py`.

## Invariants

- The `chat` of every `BaseLLMProvider` subclass runs through `enforced_chat` (`agent/providers/base.py`,
  `model_call.py`).
- A model call without a bound `ModelCallScope` is refused (`content_handling_scope_missing`, `enforcement_call.py`).
- `final_body` and `final_arguments` refuse outside that wrapper (`content_final_check_unbound`,
  `model_call_outbound.py`).
- Masks apply to a copy of the messages; the caller's messages stay unchanged (`format_chat_messages.py`).
- Untrusted text goes into a prompt between markers carrying a random token (`untrusted_fence.new_fence`). A fence is
  defence in depth, not a guarantee.
