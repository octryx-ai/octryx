# Workspace models

What belongs to one Workspace: its Knowledge (evidence ledger, sources and their ACLs, memory, structured and
temporal graph, retention), its governance assets, per-repository Git tokens and its trusted web sources.

## Invariants

- No Work item, workflow run, Action (Task) or agent chain is inserted into, or moved into, a private Workspace
  (`private_guard.py`, installed on those models in `models/__init__.py`).
- A source revision's content digest is unique per source, so the same bytes are one revision
  (`uq_knowledge_source_revisions_source_digest`, `knowledge_evidence.py`).
- An object key has at most one retention hold per Workspace (`uq_knowledge_object_hold_workspace_key`,
  `knowledge_object_retention.py`).
- A repository Git token row holds the id of a stored secret, never the token (`repository_git_token.py`).
- A trusted web source pattern exists once per scope (`uq_web_trusted_sources_scope_pattern`,
  `web_trusted_sources.py`).
