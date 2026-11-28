# Identity routes

Login, the OAuth 2.1 authorization-server endpoints (metadata, register, token, revoke; the interactive consent is
`web/routers/oauth_authorize.py`) and a user's linked external accounts.

## Invariants

- A user reads and changes only their own linked accounts; a global admin those of any user
  (`linked_accounts.py`).
