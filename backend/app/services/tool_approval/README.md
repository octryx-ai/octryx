# Tool approval

Which tool calls need a person's approval, and the gate that enforces it when a tool is dispatched.

## Invariants

- An outbound message needs a person's approval whatever the approval policy says (`rules.tool_approval_requirement`).
- A Workspace policy can only add approval rules: exemptions and the tools allowed in unattended runs come from the
  platform default only (`policy.effective_policy`).
- An exemption waives only the policy identity it names, so a capability subject never lowers the dispatched tool's
  rule (`rules.py`).
- A required approval is denied when the call has no database session or no user (`gate.py`).
- A granted approval is bound to the approval subject and its arguments (`gate.py`, through
  `services/change_preview`).
- A standing rule never answers a per-call rule or a write to an external system (`gate.py`).
