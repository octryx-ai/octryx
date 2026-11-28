# Knowledge routes

The Workspace Knowledge transport: evidence sources and originals, search and answers, source sync, bindings,
memory, feedback, the graphs, packages, retention and the read-only Knowledge MCP endpoints. The rules live in
`services/knowledge` and `services/knowledge_evidence`.

## Invariants

- An unknown Workspace, one the caller has no role in and a malformed id answer the same 404; a 403 only reaches a
  caller who can read the Workspace but lacks the authoring role (`services/knowledge/access/authorization.authorize_workspace`).
- An evidence state maps to one status in one place, its detail is a fixed text and the state travels in the
  `X-Knowledge-State` header (`_knowledge_evidence_http.py`).
- The retention routes need a global admin and cannot start an inventory or a deletion
  (`knowledge_object_retention.py`).
