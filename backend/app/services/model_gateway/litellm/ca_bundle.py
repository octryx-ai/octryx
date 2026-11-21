"""CA bundle validation for the gateway transport trust store.

A bundle is read once through a bounded descriptor read, digested, and the trust store is built from exactly
the validated bytes (see ``transport_policy`` for the trust contract).
"""

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


# Validated trust stores, keyed by path and content digest. Each context is built
# from the exact bytes whose digest keys it, and it is populated during validation,
# so the bytes that were checked are the bytes that become the trust store.
# Bounded by the number of distinct admitted bundles, which is operator
# configuration, not user input.
_SSL_CONTEXTS: dict[tuple[str, str], ssl.SSLContext] = {}
# Bundle validation results, keyed by the filesystem identity of the bytes that
# produced them (``_BundleIdentity``). The stored key always comes from the
# ``fstat`` of the descriptor the digest and the trust store were built from, so
# a cache hit cannot describe a different file than the one that was validated.
_BUNDLE_VALIDATIONS: dict[tuple[Any, ...], tuple[int, str]] = {}


def _certificate_blocks(text: str) -> list[str]:
    """Return the complete ``BEGIN``/``END`` certificate blocks of ``text``.

    Only complete blocks count, so a truncated bundle is "no certificate" rather
    than a silently shorter trust store, and a human-readable preamble (which
    real root-program bundles carry) is dropped instead of handed to OpenSSL.
    """

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
    """Build the client context from in-memory PEM material, or ``None``.

    ``cadata`` rather than ``cafile``: the trust store must be the material the
    caller already validated, not whatever the path holds at load time.
    """

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_verify_locations(cadata=cadata)
    except (ssl.SSLError, OSError, ValueError):
        # The OpenSSL message can carry internal detail; only a fixed code
        # survives, so the caller maps ``None`` to its own denial reason.
        return None
    return context


def _identity_of(path: str, info: os.stat_result) -> tuple[Any, ...]:
    """The filesystem identity of one bundle, as a cache key.

    Device and inode pin *which* object, ``st_mtime_ns``/``st_size`` catch an
    ordinary edit, and ``st_ctime_ns`` catches the one this key exists to catch:
    a replacement of the same size whose mtime was restored (``cp -p``,
    ``rsync -a``, ``install -p``, an explicit ``utime``). ``st_ctime_ns`` is set
    by the kernel on every inode change and cannot be written from user space, so
    a rewrite that looks identical in every other field still misses the cache.
    """

    return (path, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, info.st_ctime_ns)


def _read_bounded_regular_file(path: str) -> tuple[bytes, str, tuple[Any, ...]]:
    """Read at most ``MAX_CA_BUNDLE_BYTES`` from a regular file, or refuse.

    Returns the bytes, a denial code, and the filesystem identity taken from the
    very ``fstat`` that bounded the read — so the identity a validation is cached
    under always describes the bytes that validation saw.

    The read guarantees three properties, all of which matter because this is
    also the reload path and the file is attacker-writable in the threat model
    the digest re-verification addresses:

    - the kind and the size are taken from ``fstat`` on the *same* descriptor the
      bytes are read from, so nothing can be swapped between the check and the
      read;
    - a FIFO, device, socket or directory is refused rather than read: its
      ``st_size`` is meaningless, so a size bound taken from it bounds nothing,
      and ``O_NONBLOCK`` keeps an unconnected FIFO from blocking the open;
    - the read itself stops one chunk past the bound, so a file that grows while
      it is being read costs bounded memory instead of however much it reached.

    ``O_NOFOLLOW`` applies to the final component only; callers pass an already
    resolved path, so a symlink appearing there is a swap, not a configuration.
    """

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
    """Read one bundle. Returns ``(cadata, count, sha256, denial, identity)``.

    The digest covers the whole file while ``cadata`` covers only its certificate
    blocks, which is what makes the pair usable as a change detector: any edit to
    the file changes the digest, including one that leaves the blocks intact. The
    identity comes from the same descriptor as the bytes, so it describes exactly
    the material this digest was computed over.
    """

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
    """Validate a CA bundle file. Returns ``(path, count, sha256, denial)``.

    On success the validated trust store is already cached under
    ``(path, digest)``, so ``TlsTrustPolicy.ssl_context`` never has to read the
    file again to get the bytes this call approved.
    """

    candidate = raw_path.strip() if isinstance(raw_path, str) else ""
    if not candidate:
        return "", 0, "", TLS_DENIAL_BUNDLE_PATH_MISSING
    path = Path(candidate)
    if not path.is_absolute():
        # A relative path would resolve against whatever working directory the
        # API, a worker, or a CLI happens to have.
        return "", 0, "", TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE
    resolved = path.resolve()
    if not resolved.is_file():
        # Absent, a directory, a FIFO, a device. Reported here so the operator
        # gets the accurate code for a path that never was a bundle; the
        # *authoritative* kind and size checks happen on the descriptor the bytes
        # are read from (``_read_bounded_regular_file``), where nothing can be
        # swapped in between.
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_A_FILE
    try:
        probe = _identity_of(str(resolved), os.stat(resolved))
    except OSError:
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_READABLE
    # Readiness runs on the turn path (runtime selection evaluates every candidate
    # target), so re-reading and re-parsing the trust bundle every time is
    # avoidable work. The cached entry is keyed by the identity of the bytes that
    # produced it, so any rewrite of the file — including one that restores the
    # previous size and mtime — misses the cache and is validated again instead of
    # returning the retired anchor.
    validated = _BUNDLE_VALIDATIONS.get(probe)
    if validated is not None and (str(resolved), validated[1]) in _SSL_CONTEXTS:
        return str(resolved), validated[0], validated[1], ""
    cadata, count, digest, denial, identity = _read_certificate_material(str(resolved))
    if denial:
        return "", 0, "", denial
    context = _trust_store_from_cadata(cadata)
    if context is None:
        return "", 0, "", TLS_DENIAL_BUNDLE_NOT_LOADABLE
    # Cache the context built from these exact bytes, keyed by their digest, and
    # the validation under the identity the read itself observed.
    _SSL_CONTEXTS[(str(resolved), digest)] = context
    _BUNDLE_VALIDATIONS[identity] = (count, digest)
    return str(resolved), count, digest, ""
