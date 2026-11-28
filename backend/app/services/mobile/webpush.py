"""Web Push to a paired phone (Octryx Mobile): RFC 8291 message encryption (aes128gcm, RFC 8188) and RFC 8292 VAPID,
with the platform's existing ``cryptography`` (no extra dependency)."""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Apple (Safari / Home Screen apps), Google (Chrome, Android), Mozilla, Microsoft.
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")
RECORD_SIZE = 4096
MAX_PAYLOAD = 3000
SEND_TIMEOUT = 10.0
JWT_LIFETIME = 12 * 3600

SENT = "sent"
GONE = "gone"
FAILED = "failed"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def endpoint_allowed(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    if any(ord(char) < 33 or ord(char) == 127 for char in endpoint):  # no line break or space slips through
        return False
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or port not in (None, 443) or parts.username or parts.password:
        return False
    return host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES)


def load_vapid_key(text: str | None) -> ec.EllipticCurvePrivateKey | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("-----BEGIN"):
            key = serialization.load_pem_private_key(raw.encode(), password=None)
        else:
            key = ec.derive_private_key(int.from_bytes(unb64url(raw), "big"), ec.SECP256R1())
    except (ValueError, TypeError):
        return None
    return key if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1) else None


def public_key_b64(key: ec.EllipticCurvePrivateKey) -> str:
    return b64url(key.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint))


def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str, *, now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + JWT_LIFETIME),
              "sub": subject}
    signing_input = (b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={public_key_b64(key)}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    ua_public = unb64url(p256dh)
    auth_secret = unb64url(auth)
    if len(ua_public) != 65 or len(auth_secret) < 16:
        raise ValueError("subscription keys are invalid")
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    sender = sender_key or ec.generate_private_key(ec.SECP256R1())
    as_public = sender.public_key().public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


@dataclass(frozen=True, slots=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


async def send(http: httpx.AsyncClient, subscription: Subscription, message: dict[str, Any], *,
               key: ec.EllipticCurvePrivateKey, subject: str, ttl: int = 3600, urgency: str = "normal") -> str:
    if not endpoint_allowed(subscription.endpoint):
        return GONE
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode()[:MAX_PAYLOAD]
    try:
        body = encrypt(payload, subscription.p256dh, subscription.auth)
    except (ValueError, TypeError):
        return GONE
    headers = {"Authorization": vapid_header(key, subscription.endpoint, subject), "TTL": str(ttl),
               "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "Urgency": urgency}
    try:
        response = await http.post(subscription.endpoint, content=body, headers=headers, timeout=SEND_TIMEOUT)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return FAILED
    if response.status_code in (404, 410):
        return GONE
    return SENT if 200 <= response.status_code < 300 else FAILED


__all__ = ["FAILED", "GONE", "PUSH_HOSTS", "SENT", "Subscription", "encrypt", "endpoint_allowed", "load_vapid_key",
           "public_key_b64", "send", "vapid_header"]
