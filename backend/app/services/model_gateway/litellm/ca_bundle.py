"""CA bundle validation for the gateway transport trust store."""

from __future__ import annotations

import hashlib
import os
import ssl
import stat
from pathlib import Path
from typing import Any

from .transport_codes import (
    MAX_CA_BUNDLE_BYTES,
    TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY,
    TLS_DENIAL_BUNDLE_NO_CERTIFICATE,
    TLS_DENIAL_BUNDLE_NOT_A_FILE,
    TLS_DENIAL_BUNDLE_NOT_LOADABLE,
    TLS_DENIAL_BUNDLE_NOT_READABLE,
    TLS_DENIAL_BUNDLE_PATH_MISSING,
    TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE,
    TLS_DENIAL_BUNDLE_TOO_LARGE,
)

_READ_CHUNK_BYTES = 64 * 1024
_CERTIFICATE_MARKER = "-----BEGIN CERTIFICATE-----"
_CERTIFICATE_END_MARKER = "-----END CERTIFICATE-----"
_PRIVATE_KEY_MARKER = "PRIVATE KEY-----"


# Each context is built from the exact bytes whose digest keys it, so the checked bytes become the trust store.
# Bounded by the distinct admitted bundles (operator configuration, not user input).
_SSL_CONTEXTS: dict[tuple[str, str], ssl.SSLContext] = {}
# Keyed by the ``fstat`` identity of the descriptor the digest and trust store came from, so a hit cannot
# describe a different file than the one validated.
_BUNDLE_VALIDATIONS: dict[tuple[Any, ...], tuple[int, str]] = {}


def _certificate_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    cursor = 0
    while True:
        start = text.find(_CERTIFICATE_MARKER, cursor)
        if start < 0:
            return blocks
        end = text.find(_CERTIFICATE_END_MARKER, start)
        if end < 0:
            return blocks
        cursor = end + len(_CERTIFICATE_END_MARKER)
        blocks.append(text[start:cursor])


def _trust_store_from_cadata(cadata: str) -> ssl.SSLContext | None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_verify_locations(cadata=cadata)
    except (ssl.SSLError, OSError, ValueError):
        # The OpenSSL message can carry internal detail; only a fixed code survives.
        return None
    return context


def _identity_of(path: str, info: os.stat_result) -> tuple[Any, ...]:
    return (path, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, info.st_ctime_ns)


def _read_bounded_regular_file(path: str) -> tuple[bytes, str, tuple[Any, ...]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return b"", TLS_DENIAL_BUNDLE_NOT_READABLE, ()
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return b"", TLS_DENIAL_BUNDLE_NOT_A_FILE, ()
        if info.st_size > MAX_CA_BUNDLE_BYTES:
            return b"", TLS_DENIAL_BUNDLE_TOO_LARGE, ()
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_CA_BUNDLE_BYTES:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
    except OSError:
        return b"", TLS_DENIAL_BUNDLE_NOT_READABLE, ()
    finally:
        os.close(descriptor)
    if total > MAX_CA_BUNDLE_BYTES:
        return b"", TLS_DENIAL_BUNDLE_TOO_LARGE, ()
    return b"".join(chunks), "", _identity_of(path, info)


def _read_certificate_material(path: str) -> tuple[str, int, str, str, tuple[Any, ...]]:
    raw, denial, identity = _read_bounded_regular_file(path)
    if denial:
        return "", 0, "", denial, ()
    text = raw.decode("ascii", errors="replace")
    if _PRIVATE_KEY_MARKER in text:
        # A trust store must not double as a credential store.
        return "", 0, "", TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY, ()
    blocks = _certificate_blocks(text)
    if not blocks:
        return "", 0, "", TLS_DENIAL_BUNDLE_NO_CERTIFICATE, ()
    return "\n".join(blocks) + "\n", len(blocks), hashlib.sha256(raw).hexdigest(), "", identity


def _read_ca_bundle(raw_path: Any) -> tuple[str, int, str, str]:
    candidate = raw_path.strip() if isinstance(raw_path, str) else ""
    if not candidate:
        return "", 0, "", TLS_DENIAL_BUNDLE_PATH_MISSING
    path = Path(candidate)
    if not path.is_absolute():
        # A relative path would resolve against whatever working directory the process happens to have.
        return "", 0, "", TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE
    resolved = path.resolve()
    if not resolved.is_file():
        # Reported here for an accurate code; the authoritative kind and size checks run on the descriptor the bytes
        # are read from (``_read_bounded_regular_file``), where nothing can be swapped in between.
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_A_FILE
    try:
        probe = _identity_of(str(resolved), os.stat(resolved))
    except OSError:
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_READABLE
    # Readiness runs on the turn path, so re-validating every time is avoidable; the identity key makes any rewrite
    # (even one restoring size and mtime) miss the cache instead of returning the retired anchor.
    validated = _BUNDLE_VALIDATIONS.get(probe)
    if validated is not None and (str(resolved), validated[1]) in _SSL_CONTEXTS:
        return str(resolved), validated[0], validated[1], ""
    cadata, count, digest, denial, identity = _read_certificate_material(str(resolved))
    if denial:
        return "", 0, "", denial
    context = _trust_store_from_cadata(cadata)
    if context is None:
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_LOADABLE
    _SSL_CONTEXTS[(str(resolved), digest)] = context
    _BUNDLE_VALIDATIONS[identity] = (count, digest)
    return str(resolved), count, digest, ""
