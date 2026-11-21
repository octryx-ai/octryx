"""Storage-neutral reference to an S3-compatible source object.

The reference names *what* was read (bucket, key, optional version and content
digest), never *how* to reach it: endpoint, region, credentials, and presigned
URLs stay inside the object-store adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..retrieval.errors import InvalidRetrievalRequestError

MAX_OBJECT_KEY_BYTES = 1024
MAX_VERSION_ID_CHARS = 1024

# S3 bucket naming rules: 3-63 chars, lower-case letters, digits, dots and
# hyphens, starting and ending with a letter or digit.
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IPV4_LIKE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_VERSION_ID = re.compile(r"^[\x21-\x7e]+$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_valid_bucket_name(bucket: object) -> bool:
    """S3 bucket-name rules. Public: the object-store configuration shares them."""
    if type(bucket) is not str:
        return False
    return (
        bool(_BUCKET.fullmatch(bucket))
        and ".." not in bucket
        and ".-" not in bucket
        and "-." not in bucket
        and not _IPV4_LIKE.fullmatch(bucket)
    )


def _is_valid_key(key: str) -> bool:
    # Lone surrogates cannot be UTF-8 encoded; reject them before encoding so
    # the failure stays a typed contract error instead of a UnicodeEncodeError.
    if not key or any(0xD800 <= ord(char) <= 0xDFFF for char in key):
        return False
    if len(key.encode("utf-8")) > MAX_OBJECT_KEY_BYTES:
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
        return False
    # No absolute keys, empty segments, or relative path segments: a key must
    # map to exactly one object and never be reinterpreted as a path.
    return all(segment not in ("", ".", "..") for segment in key.split("/"))


@dataclass(frozen=True, slots=True)
class SourceObjectRef:
    """Immutable pointer to one object revision in S3-compatible storage."""

    bucket: str
    key: str
    version_id: str | None = None
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        # Exact ``str`` only: a subclass could override the methods the checks use.
        if type(self.bucket) is not str or not is_valid_bucket_name(self.bucket):
            raise InvalidRetrievalRequestError()
        if type(self.key) is not str or not _is_valid_key(self.key):
            raise InvalidRetrievalRequestError()
        if self.version_id is not None and (
            type(self.version_id) is not str
            or len(self.version_id) > MAX_VERSION_ID_CHARS
            or not _VERSION_ID.fullmatch(self.version_id)
        ):
            raise InvalidRetrievalRequestError()
        if self.content_sha256 is not None and (
            type(self.content_sha256) is not str or not _SHA256_HEX.fullmatch(self.content_sha256)
        ):
            raise InvalidRetrievalRequestError()
