# Connector authentication

The credential modes of the Confluence, Jira, Bitbucket and ServiceNow connectors, and the OAuth tokens they fetch.

## Invariants

- A missing or unknown auth mode resolves no credential (`atlassian.resolve_credential`,
  `servicenow.resolve_servicenow_auth`).
- A token URL is `https`, or `http` for a loopback host only, and never carries userinfo
  (`oidc_client_credentials.token_url_problem`).
- A token request goes through the connector's egress transport and never follows a redirect (`oidc_token_cache.py`,
  `servicenow_password_grant.py`).
- Tokens are cached in process only, under a key that hashes the secrets; the cache never holds a client secret or a
  password (`oidc_token_cache.py`, `servicenow_password_grant.py`).
- A token failure is an `OidcTokenError` with a closed code and a fixed message (`oidc_client_credentials.py`).
