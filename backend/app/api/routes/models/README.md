# Model routes

The model catalog and Model Policy admin APIs and the inbound model gateway surfaces (Anthropic Messages for
octryx-claude, OpenAI Responses for Codex). The rules live in `services/model_catalog`, `services/model_policy` and
`services/model_gateway/inbound`.

## Invariants

- A Model Policy outside the caller's scope answers like an unknown one (`_model_policy_http.py`,
  `model_policy_not_found`).
