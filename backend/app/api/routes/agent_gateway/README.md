# Agent gateway routes

The control plane the octryx-claude launcher and its hooks call (registration, tool checks, repository, skills,
handoff, transcripts, mobile pairing) and the Workspace settings pages for them. The rules live in
`services/agent_gateway` and the services each route names.

## Invariants

- A tool check without a usable gateway identity or session, with an unreadable body or without a valid Workspace
  policy, answers `decision: "deny"` (`agent_gateway.tool_check`).
- A session's hook key is set once; a later registration is refused with `hook_key_already_registered`
  (`services/agent_gateway/hook_key.register_hook_key`).
- A skill blob is served only when it is in the requester's own manifest (`agent_gateway_skills.py`,
  `skill_blob_not_in_manifest`).
