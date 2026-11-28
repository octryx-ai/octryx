# Web surface

The chat UI and admin panel routes (`/chat`, `/admin`, the panel APIs, `/m`, `/oauth/authorize`) and their request
helpers.

## Invariants

- A state-changing route whose path has an `admin` or `panel` segment refuses a caller who is not admin-capable
  before it runs; the exceptions are listed in `_helpers/admin_surface_user_routes.py`, and the admin-only mutations
  outside such a path in `_helpers/admin_surface_root_routes.py` (`_helpers/admin_surface_gate.with_admin_surface_gate`,
  put on every included router in `http_setup.py`; `tests/web/test_admin_surface_gate.py` holds both lists exact).
- The web surface authenticates only an active account; nothing is persisted before a refusal
  (`_helpers/cookie_principal.load_active_principal`).
- `/oauth/authorize` renders an error page, never a redirect, for a missing, unknown or inactive client or an
  unregistered `redirect_uri` (`routers/oauth_authorize.py`).
