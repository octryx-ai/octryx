"""The device channel's credentials: its access token from the device credential (renewed with the device key when
refused) and the platform's word on a revoke signal (``device_runtime``)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from . import device_renewal
from .state import CREDENTIAL_SET_DEVICE, LocalState
from .tokens import DEVICE_AUDIENCE, TokenUnavailableError, get_access_token


def channel_token(state: LocalState, force: bool, *, http_factory: Callable[[], httpx.Client] = httpx.Client) -> str:
    # A refused refresh renews the credential with the device key; only a refused renewal reaches the channel.
    device_creds = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    if force:
        with device_creds.credentials_lock():
            credentials = device_creds.credentials()
            tokens = credentials.get("tokens") if isinstance(credentials.get("tokens"), dict) else {}
            tokens.pop(DEVICE_AUDIENCE, None)
            credentials["tokens"] = tokens
            device_creds.write_credentials(credentials)
    with http_factory() as http:
        try:
            return get_access_token(device_creds, DEVICE_AUDIENCE, http=http)
        except TokenUnavailableError as exc:
            if exc.code not in device_renewal.RENEWABLE_CODES:
                raise
            logger = logging.getLogger("octryx_claude.device")
            logger.warning("device credential refused (%s); renewing it with the device key", exc.code)
            device_renewal.renew_credential(state, http=http)
            logger.info("device credential renewed")
            return get_access_token(device_creds, DEVICE_AUDIENCE, http=http)


def revocation_check(state: LocalState, *, http_factory: Callable[[], httpx.Client] = httpx.Client,
                     recheck: bool = False) -> str:
    with http_factory() as http:
        return device_renewal.confirm_revocation(state, http=http, recheck=recheck)
