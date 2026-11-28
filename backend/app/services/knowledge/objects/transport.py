"""The S3 transport boundary: one client builder and one failure mapping. Nothing from an original exception is
retained."""

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
    # Code-chosen identifiers only, never a message, endpoint, key or body, so the token is safe to log.
    code = error_code(error)
    if code:
        return code
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "other"


def mapped_error(error: BaseException, operation: KnowledgeObjectOperation) -> KnowledgeObjectError:
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
