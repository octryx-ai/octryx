"""Explicit S3-compatible configuration for the Knowledge object boundary. It can never degrade into a host directory,
and credentials are never part of it."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from ..endpoint_rules import base_url, is_allowed_scheme_for_host, is_valid_host, is_valid_port, split_endpoint
from .errors import (
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectOperation,
)
from .source_object import is_valid_bucket_name

ENV_ENDPOINT_URL = "OCTRYX_KNOWLEDGE_OBJECT_ENDPOINT_URL"
ENV_BUCKET = "OCTRYX_KNOWLEDGE_OBJECT_BUCKET"
ENV_REGION = "OCTRYX_KNOWLEDGE_OBJECT_REGION"
ENV_PREFIX = "OCTRYX_KNOWLEDGE_OBJECT_PREFIX"
ENV_TIMEOUT_SECONDS = "OCTRYX_KNOWLEDGE_OBJECT_TIMEOUT_SECONDS"
ENV_AWS_PROFILE = "OCTRYX_KNOWLEDGE_OBJECT_AWS_PROFILE"

DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 0.5
MAX_TIMEOUT_SECONDS = 60.0
MAX_PREFIX_CHARS = 64

# Lower-case, slash-separated segments only: no leading or trailing slash, no
# empty or relative segment, no dot, so a prefix can never escape or be
# reinterpreted as a path.
_PREFIX = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*$")
# AWS region tokens: lower-case letters, digits and hyphens only.
_REGION = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_TIMEOUT = re.compile(r"^[0-9]{1,2}(?:\.[0-9]{1,3})?$")
# Shared-credentials profile names: a bounded token, never a path or an expression.
_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_CONFIGURATION = KnowledgeObjectOperation.CONFIGURATION


def _invalid() -> NoReturn:
    raise KnowledgeObjectInvalidConfigurationError(_CONFIGURATION)


@dataclass(frozen=True, slots=True)
class KnowledgeObjectStoreConfig:
    """Validated S3-compatible target of the Knowledge object boundary."""

    scheme: str
    host: str
    port: int
    bucket: str
    region: str
    prefix: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    credentials_profile: str | None = None

    def __post_init__(self) -> None:
        # Direct construction is revalidated with the same rules as the mapping path.
        if not is_valid_host(self.host) or not is_valid_port(self.port):
            _invalid()
        if not is_allowed_scheme_for_host(self.scheme, self.host):
            _invalid()
        if not is_valid_bucket_name(self.bucket):
            _invalid()
        if type(self.region) is not str or not _REGION.fullmatch(self.region):
            _invalid()
        if self.prefix is not None and (
            type(self.prefix) is not str or len(self.prefix) > MAX_PREFIX_CHARS or not _PREFIX.fullmatch(self.prefix)
        ):
            _invalid()
        if type(self.timeout_seconds) is not float or not (
            MIN_TIMEOUT_SECONDS <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            _invalid()
        if self.credentials_profile is not None and (
            type(self.credentials_profile) is not str or not _PROFILE.fullmatch(self.credentials_profile)
        ):
            _invalid()

    @property
    def endpoint_url(self) -> str:
        """Origin form handed to the S3 client; carries no path or credential."""
        return base_url(self.scheme, self.host, self.port)

    def __repr__(self) -> str:
        # Bucket and prefix are Workspace-independent, but the endpoint is
        # deployment topology; neither belongs in a log line by accident.
        return f"KnowledgeObjectStoreConfig(bucket={self.bucket!r}, prefix={self.prefix!r})"

    __str__ = __repr__


def _value(environ: Mapping[str, str], key: str) -> str | None:
    if not isinstance(environ, Mapping):
        _invalid()
    value = environ.get(key)
    if value is None or value == "":
        return None
    if type(value) is not str:
        _invalid()
    return value


def _required(environ: Mapping[str, str], key: str) -> str:
    value = _value(environ, key)
    if value is None:
        raise KnowledgeObjectNotConfiguredError(_CONFIGURATION)
    return value


def _timeout(environ: Mapping[str, str]) -> float:
    raw = _value(environ, ENV_TIMEOUT_SECONDS)
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    if not _TIMEOUT.fullmatch(raw):
        _invalid()
    return float(raw)


def object_store_config_from_mapping(environ: Mapping[str, str]) -> KnowledgeObjectStoreConfig:
    """Build the object-store configuration; missing values need configuration."""
    parts = split_endpoint(_required(environ, ENV_ENDPOINT_URL))
    if parts is None:
        _invalid()
    scheme, host, port = parts
    return KnowledgeObjectStoreConfig(
        scheme=scheme,
        host=host,
        port=port,
        bucket=_required(environ, ENV_BUCKET),
        region=_required(environ, ENV_REGION),
        prefix=_value(environ, ENV_PREFIX),
        timeout_seconds=_timeout(environ),
        credentials_profile=_value(environ, ENV_AWS_PROFILE),
    )
