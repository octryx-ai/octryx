"""How an inbound call proves it knows the webhook's secret, and that it is not a replay.

Default (timestamped), constant-time and on bytes:

* ``X-Webhook-Timestamp: <unix seconds>`` and ``X-Webhook-Signature: sha256=<hex>`` = HMAC-SHA256 of
  ``"<timestamp>.<raw body>"`` with the secret; the timestamp must be within 5 minutes of now.

Only on a webhook explicitly set to ``accept_untimestamped`` (tools that cannot sign a timestamp):

* ``X-Webhook-Signature`` (or ``X-Hub-Signature-256``) = HMAC-SHA256 of the raw body;
* ``Authorization: Bearer <secret>`` (Alertmanager ``authorization.credentials``, Grafana);
* ``X-Webhook-Secret: <secret>`` (or GitLab's ``X-Gitlab-Token: <secret>``).

Every accepted call yields a delivery key (the sender's delivery id when it sends one, else a hash of
timestamp + body); the trigger refuses a key it has already seen (``rejected_replay``).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass

# ``x-hub-signature``: Bitbucket Data Center and Bitbucket Cloud sign ``sha256=<hmac of the body>`` there (S4b SCM
# webhooks); Bitbucket Cloud names each delivery in ``x-request-uuid``.
SIGNATURE_HEADERS = ("x-webhook-signature", "x-hub-signature-256", "x-hub-signature")
TIMESTAMP_HEADER = "x-webhook-timestamp"
DELIVERY_ID_HEADERS = ("x-webhook-delivery", "x-delivery-id", "x-request-id", "x-github-delivery",
                       "x-gitlab-event-uuid", "x-request-uuid")
TIMESTAMP_TOLERANCE_SECONDS = 300

REJECT_BAD_SIGNATURE = "bad_signature"
REJECT_STALE_TIMESTAMP = "stale_timestamp"
REJECT_TIMESTAMP_REQUIRED = "timestamp_required"


@dataclass(frozen=True)
class CallCheck:
    method: str | None  # hmac_timestamped | hmac | bearer | header; None when refused
    reason: str | None = None
    delivery_key: str | None = None

    @property
    def ok(self) -> bool:
        return self.method is not None


def sign_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def sign_timestamped(secret: str, timestamp: str, body: bytes) -> str:
    return sign_body(secret, timestamp.encode() + b"." + body)


def _same(left: str, right: str) -> bool:
    # Bytes, so a non-ASCII header can never raise inside compare_digest (it is simply unequal).
    return hmac.compare_digest(left.encode("utf-8", "surrogatepass"), right.encode("utf-8", "surrogatepass"))


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return str(value or "").strip()
    return ""


def _delivery_key(headers: Mapping[str, str], timestamp: str, body: bytes) -> str:
    for name in DELIVERY_ID_HEADERS:
        value = _header(headers, name)
        if value:
            return "id:" + hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()
    return "body:" + hashlib.sha256(timestamp.encode() + b"." + body).hexdigest()


def verify_call(
    headers: Mapping[str, str],
    body: bytes,
    secret: str | None,
    *,
    accept_untimestamped: bool = False,
    now: float | None = None,
) -> CallCheck:
    if not secret:
        return CallCheck(None, REJECT_BAD_SIGNATURE)
    signature = next((_header(headers, name) for name in SIGNATURE_HEADERS if _header(headers, name)), "")
    timestamp = _header(headers, TIMESTAMP_HEADER)
    if timestamp:
        if not signature or not _same(signature.lower(), sign_timestamped(secret, timestamp, body)):
            return CallCheck(None, REJECT_BAD_SIGNATURE)
        try:
            skew = abs((now if now is not None else time.time()) - float(timestamp))
        except ValueError:
            return CallCheck(None, REJECT_BAD_SIGNATURE)
        if skew > TIMESTAMP_TOLERANCE_SECONDS:
            return CallCheck(None, REJECT_STALE_TIMESTAMP)
        return CallCheck("hmac_timestamped", delivery_key=_delivery_key(headers, timestamp, body))

    method: str | None = None
    if signature:
        method = "hmac" if _same(signature.lower(), sign_body(secret, body)) else None
    else:
        authorization = _header(headers, "authorization")
        # ``X-Gitlab-Token`` is GitLab's shared secret header (S4b SCM and CI webhooks).
        shared = _header(headers, "x-webhook-secret") or _header(headers, "x-gitlab-token")
        if authorization.lower().startswith("bearer "):
            method = "bearer" if _same(authorization[7:].strip(), secret) else None
        elif shared:
            method = "header" if _same(shared, secret) else None
    if method is None:
        return CallCheck(None, REJECT_BAD_SIGNATURE)
    if not accept_untimestamped:
        return CallCheck(None, REJECT_TIMESTAMP_REQUIRED)
    return CallCheck(method, delivery_key=_delivery_key(headers, "", body))


__all__ = [
    "REJECT_BAD_SIGNATURE",
    "REJECT_STALE_TIMESTAMP",
    "REJECT_TIMESTAMP_REQUIRED",
    "TIMESTAMP_TOLERANCE_SECONDS",
    "CallCheck",
    "sign_body",
    "sign_timestamped",
    "verify_call",
]
