# Runtime models

The platform's working state: governed registries (Model Policies, prompt templates), connections, the agent
coordination board, workflow runs and Product Runs, scheduler and process leases, plugins and REST connectors.

## Invariants

- A governed revision that is published changes only by its move to `retired`, a retired one never changes, and
  neither is deleted (`governed_revision.install_immutability_guard`; installed on Model Policy revisions, prompt
  template versions, policy-set and classification-policy versions and skill versions).
- A prompt template has at most one published version (`uq_prompt_template_versions_one_published`,
  `prompt_template.py`).
- A Work Item has at most one active claim (`uq_work_item_claim_active`, `work_item_claim.py`), and a decision
  request on the agent board at most one decision (`uq_agent_board_one_decision`, `agent_board.py`).
- A named connection's name is unique per connector and scope, ignoring case
  (`uq_connector_named_connections_name_ci`, `named_connection.py`).
- A seat session's credential is stored as a SHA-256 hash only (`AgentPresence.seat_credential_hash`,
  `agent_presence.py`).
