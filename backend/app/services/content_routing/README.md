# Content routing

Turns a content examination into one decision for a model request or a tool result: go on, refuse, or repair it as a
custom Cedar policy asks.

## Invariants

- An unfinished examination is refused (`content_scan_unfinished`) before any Cedar query, and its partial findings
  are dropped (`decision.py`).
- Only custom Cedar policies can repair instead of refuse; a deciding policy without an obligation blocks, and a tool
  result can only be masked (`obligations.resolve`).
- A repaired chat request or tool result goes on only when Cedar answers its second decision with allow (`chat.py`,
  `tool_results.py`).
- The coding-agent gateway plan applies the Workspace's content handling like the platform's own calls: Cedar decides
  on the content as found, then the kinds to mask are masked (`content_security/format_request_body.py`) and the masked body is read
  again; a reroute (the setting's, or a policy's) returns the alias the route admits and plans again
  (`content_security/enforcement_inbound.py`, `model_gateway/inbound/content_reroute.py`).
