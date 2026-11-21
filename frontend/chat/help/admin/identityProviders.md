---
title: Sign-in
---

Let people sign in with your company identity provider (OIDC). Accounts are created on first sign-in when auto-provisioning is on.

### What you do here
- Register a provider with **Register OIDC provider**.
- Open a provider's row to change it in the side panel: its claims, how new users are created, default roles and groups, and external groups mapped to local roles and groups. **Save changes** is at the bottom right; **Refresh** reloads the list.
- Decide whether people may still sign in with a password.

### Next steps
- [Manage user accounts](/chat?area=admin&tab=users)
- [Check who can do what](/chat?area=admin&tab=identityAccess)

### Set up single sign-on
1. **Register an app at your identity provider** (for example Microsoft Entra ID, Okta or Keycloak) and allow the redirect URI shown in **Register OIDC provider**. It is the address as seen by this browser; behind a proxy, use the public address people open.
2. **Register the provider here** with the issuer URL, client ID and client secret from that app, then map claims, roles and groups.
3. **Test sign-in** in a private browser window: the sign-in page lists every active provider.
4. **Optionally allow sign-in only through SSO** under Password sign-in on this page. It applies to the web sign-in and the API; no account keeps a password while it is on.
