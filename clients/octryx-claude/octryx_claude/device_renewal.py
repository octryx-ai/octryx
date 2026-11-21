"""Renew the device credential with the device key (D1): the background service never needs a human login.

The device grant's refresh token rotates on every refresh; one lost on the way (a platform restart mid-refresh)
is a replay on the next refresh and the platform kills the grant, and the grant ends after 90 days anyway. Then
the service signs ``octryx-device-renew:v1:{device_id}:{issued_at}`` with ``device-key.pem`` and posts it to
``/api/v1/devices/self/renew``; the platform checks the registered key and that the device is not revoked, and
answers with a new device credential, stored like the one ``device enable`` wrote.

Failures are fixed ``TokenUnavailableError`` codes: ``device_revoked`` (enable the device again),
``renewal_rejected`` (needs login: a foreign or missing key, an inactive owner), ``renewal_stale`` (a clock off
by more than five minutes; retried) and ``platform_unreachable``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import httpx

from . import device_state
from .state import CREDENTIAL_SET_DEVICE, LocalState
from .tokens import TOKEN_TIMEOUT_SECONDS, TokenUnavailableError

RENEW_PATH = "/api/v1/devices/self/renew"
# What a refused refresh looks like; only these are worth a renewal.
RENEWABLE_CODES = frozenset({"refresh_rejected", "not_logged_in"})
CODE_REVOKED = "device_revoked"
CODE_REJECTED = "renewal_rejected"
CODE_STALE = "renewal_stale"
# The platform's answer to a revoke signal (``confirm_revocation``).
VERDICT_REVOKED = "revoked"
VERDICT_ACTIVE = "active"
VERDICT_NEEDS_LOGIN = "needs_login"
VERDICT_UNCONFIRMED = "unconfirmed"


def renewal_payload(device_id: str, issued_at: int) -> bytes:
    return f"octryx-device-renew:v1:{device_id}:{issued_at}".encode()


def _refusal(response: httpx.Response) -> str:
    try:
        reason = response.json().get("reason")
    except (ValueError, AttributeError):
        reason = None
    if reason == "device_revoked":
        return CODE_REVOKED
    if reason == "device_renewal_stale":
        return CODE_STALE
    return CODE_REJECTED


# One renewal at a time in this service: without it the token provider and a revoke confirmation renew concurrently,
# and the losing answer can persist ``revoked`` right before the winning renewal succeeds.
_RENEW_LOCK = threading.Lock()


def renew_credential(state: LocalState, *, http: httpx.Client, clock: Callable[[], float] = time.time,
                     recheck: bool = False) -> None:
    """Replace the device credential through a key-signed renewal; raises ``TokenUnavailableError``.

    ``recheck``: ask the platform although ``revoked`` is persisted (that flag is what is being verified)."""
    with _RENEW_LOCK:
        _renew_credential(state, http=http, clock=clock, recheck=recheck)


def _renew_credential(state: LocalState, *, http: httpx.Client, clock: Callable[[], float],
                      recheck: bool = False) -> None:
    device = device_state.load_device(state)
    device_id, base_url = str(device.get("device_id") or ""), str(device.get("base_url") or "").rstrip("/")
    usable = bool(device_id) if recheck else device_state.registered(device)
    if not usable or not base_url:
        raise TokenUnavailableError(CODE_REVOKED if device.get("revoked") and not recheck else CODE_REJECTED)
    issued_at = int(clock())
    try:
        signature = device_state.sign(state, renewal_payload(device_id, issued_at))
    except device_state.DeviceStateError as exc:
        raise TokenUnavailableError(CODE_REJECTED) from exc
    try:
        response = http.post(f"{base_url}{RENEW_PATH}", timeout=TOKEN_TIMEOUT_SECONDS,
                             json={"device_id": device_id, "issued_at": issued_at, "signature": signature})
    except httpx.HTTPError as exc:
        raise TokenUnavailableError("platform_unreachable") from exc
    if response.status_code in (401, 403):
        raise TokenUnavailableError(_refusal(response))
    if response.status_code != 200:
        raise TokenUnavailableError("token_endpoint_error")
    try:
        credential = response.json().get("credential")
    except (ValueError, AttributeError) as exc:
        raise TokenUnavailableError("invalid_token_response") from exc
    if not isinstance(credential, dict) or not isinstance(credential.get("refresh_token"), str) \
            or not credential["refresh_token"] or not isinstance(credential.get("client_id"), str):
        raise TokenUnavailableError("invalid_token_response")
    device_creds = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    with device_creds.credentials_lock():
        device_creds.write_credentials({
            "base_url": base_url, "client_id": credential["client_id"],
            "refresh_token": credential["refresh_token"], "scopes": list(credential.get("scopes") or []),
            "tokens": {},
        })
    # The platform just renewed this device with its own key: it is active, so a ``revoked`` persisted meanwhile is
    # stale. A real revocation answers ``device_revoked`` and never reaches this line.
    current = device_state.load_device(state)
    if current.get("revoked"):
        current.pop("revoked", None)
        device_state.save_device(state, current)


def confirm_revocation(state: LocalState, *, http: httpx.Client, recheck: bool = False) -> str:
    """The platform's authoritative answer to a revoke signal, asked before the device persists ``revoked``.

    A channel close 4410 or a ``device_revoked`` answer can be transient: during a redeploy a refresh replay ends
    the device *grant* and the channel's recheck closes as ``revoke`` although the device itself is active. The
    key-signed renewal checks the registered key and the device's own status, so only its ``device_revoked`` is a
    revocation (``revoked``). A successful renewal means the device is active and holds a new credential
    (``active``); a refused one needs a login (``needs_login``); anything else (unreachable, 5xx, a clock off) is
    ``unconfirmed`` and never revokes.

    ``recheck``: the same question for a ``revoked`` already persisted: an
    active answer clears it, so a false positive never strands an active device.
    """
    try:
        renew_credential(state, http=http, recheck=recheck)
    except TokenUnavailableError as exc:
        if exc.code == CODE_REVOKED:
            return VERDICT_REVOKED
        if exc.code == CODE_REJECTED:
            return VERDICT_NEEDS_LOGIN
        return VERDICT_UNCONFIRMED
    return VERDICT_ACTIVE


__all__ = ["CODE_REJECTED", "CODE_REVOKED", "CODE_STALE", "RENEWABLE_CODES", "VERDICT_ACTIVE",
           "VERDICT_NEEDS_LOGIN", "VERDICT_REVOKED", "VERDICT_UNCONFIRMED", "confirm_revocation",
           "renew_credential", "renewal_payload"]
