"""``python -m octryx_claude.logout``: revoke the platform login and forget it locally.

``uninstall --purge`` runs this before it deletes the state directory, so the refresh token does
not stay valid on the platform. The revoke is best effort (RFC 7009 answers 200 for unknown
tokens); the local credentials are removed either way. Prints fixed reason codes only.
"""

from __future__ import annotations

import contextlib
import sys

import httpx

from .state import LocalState

REVOKE_TIMEOUT_SECONDS = 10.0


def revoke(state: LocalState, http: httpx.Client) -> str:
    """``revoked``, ``not_logged_in`` or ``revoke_failed``."""
    credentials = state.credentials()
    base_url = str(credentials.get("base_url") or "").rstrip("/")
    token = str(credentials.get("refresh_token") or "")
    client_id = str(credentials.get("client_id") or "")
    if not base_url or not token:
        return "not_logged_in"
    form = {"token": token, "token_type_hint": "refresh_token"}
    if client_id:
        form["client_id"] = client_id
    try:
        response = http.post(f"{base_url}/oauth/revoke", data=form, timeout=REVOKE_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return "revoke_failed"
    return "revoked" if response.status_code == 200 else "revoke_failed"


def logout(state: LocalState, http: httpx.Client) -> str:
    with state.credentials_lock():
        outcome = revoke(state, http)
        with contextlib.suppress(FileNotFoundError):
            state.credentials_path.unlink()
    return outcome


def main() -> int:
    state = LocalState()
    with httpx.Client(follow_redirects=False) as http:
        outcome = logout(state, http)
    sys.stderr.write(f"octryx-claude: logout: {outcome}; local login removed\n")
    return 0 if outcome in ("revoked", "not_logged_in") else 1


if __name__ == "__main__":
    sys.exit(main())
