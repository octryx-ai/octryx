"""The S3 transport boundary: one client builder and one failure mapping.

Extracted so the immutable ingestion store (``store.py``) and the operator-owned
maintenance capability (``maintenance.py``) cannot drift apart on either of the two
things that decide how this boundary behaves on the wire and how it fails:

- the client is always path-style, SigV4, and bounded by explicit connect/read timeouts,
  so a bucket name can never influence which host is contacted and no call can hang;
- a transport or S3 failure is reduced to a *fixed* error state and nothing from the
  original exception is retained — no endpoint, key, credential, signed request or server
  error body — so a mapped error is safe to raise, log and render.

Credentials are never passed in: boto3 resolves them from its default chain, so the
process that runs a client decides which identity it holds. That is what lets the API
process keep a ``PutObject``/``GetObject`` identity while an operator process runs the
inventory/delete identity.
"""

from __future__ import annotations

from typing import Any

from .config import KnowledgeObjectStoreConfig
from .errors import (
    KnowledgeObjectContractError,
    KnowledgeObjectError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectOperation,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_UNAUTHORIZED_CODES = frozenset(
    {"401", "403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}
)
_ABSENT_BUCKET_CODES = frozenset({"NoSuchBucket"})


def build_s3_client(config: KnowledgeObjectStoreConfig) -> Any:
    """Build the synchronous S3 client both capabilities of this package use."""
    import boto3
    from botocore.config import Config

    # A named profile keeps the object-store keys apart from any AWS_* environment
    # credentials of this process; boto3 ignores the environment chain for it.
    factory = boto3.session.Session(profile_name=config.credentials_profile) if config.credentials_profile else boto3
    return factory.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        config=Config(
            signature_version="s3v4",
            # Path style keeps the bucket out of the host name, so a bucket can never
            # influence which host is contacted.
            s3={"addressing_style": "path"},
            connect_timeout=config.timeout_seconds,
            read_timeout=config.timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def error_code(error: BaseException) -> str:
    """The S3 error code as a bare token, used only to pick a fixed state."""
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return ""
    details = response.get("Error")
    code = details.get("Code") if isinstance(details, dict) else None
    if type(code) is str and code.isalnum():
        return code
    metadata = response.get("ResponseMetadata")
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    return str(status) if type(status) is int else ""


def failure_cause(error: BaseException) -> str:
    """A fixed token naming what failed: the S3 error code, else the client exception class.

    Both are identifiers chosen by code (``InternalError``, ``503``, ``ReadTimeoutError``,
    ``ConnectionClosedError``), never a message, endpoint, key or body, so the token is safe to
    log. It tells a timeout from a server refusal, which the mapped state does not.
    """
    code = error_code(error)
    if code:
        return code
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "other"


def mapped_error(error: BaseException, operation: KnowledgeObjectOperation) -> KnowledgeObjectError:
    """Map a transport or S3 failure onto a fixed error, retaining nothing from it."""
    code = error_code(error)
    if code in _NOT_FOUND_CODES:
        return KnowledgeObjectNotFoundError(operation)
    if code in _UNAUTHORIZED_CODES:
        return KnowledgeObjectUnauthorizedError(operation)
    if code in _ABSENT_BUCKET_CODES:
        return KnowledgeObjectNotConfiguredError(operation)
    if code.isdigit() and 500 <= int(code) <= 599:
        return KnowledgeObjectUnavailableError(operation)
    if code.isdigit() and 400 <= int(code) <= 499:
        return KnowledgeObjectContractError(operation)
    # Connection errors, timeouts, and anything else the client raised.
    return KnowledgeObjectUnavailableError(operation)
