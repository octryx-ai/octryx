"""Closed per-key value grammars for the gateway evidence payload (Issue)."""

from __future__ import annotations

import re
from datetime import date

from ...redaction_policy import looks_like_secret_value
from .alias_catalog import DATA_POLICY_CLASSES
from .content_logging import CONTENT_FREE_CALLBACKS
from .evidence_host_shape import (
    HOP_RULE_EVIDENCE_KEYS,
    HOST_EVIDENCE_KEYS,
    is_admissible_host_evidence,
)

# Closed evidence keys whose value is an operator- or cluster-supplied
# identifier: an alias, the upstream model group, a governance record id, a
# callback name, an attestation date, a bundle digest (``evidence.py``).
IDENTIFIER_EVIDENCE_KEYS = frozenset(
    {
        "alias",
        "model_group",
        "data_policy_class",
        "cost_contract_reference",
        "content_logging_attestation_reference",
        "content_logging_attested_on",
        "content_logging_callbacks",
        "tls_ca_bundle_sha256",
        "tls_attestation_reference",
        "tls_attested_on",
    }
)
# Closed evidence keys whose value is a request path derived from the validated
# endpoint base path and the pinned probe path (``network_path.py``).
PATH_EVIDENCE_KEYS = frozenset(
    {
        "endpoint_base_path",
        "probe_models_path",
        "network_path_allowed_request_paths",
    }
)

# Long enough for a real upstream model group
# (``bedrock-converse-eu-anthropic-claude-3-7-sonnet-20250219-v1-0``) and a
# sha256 digest; short enough that no document or log line fits.
MAX_IDENTIFIER_LENGTH = 128
MAX_PATH_LENGTH = 128

# ``/`` is admitted inside an identifier because upstream model groups are
# routinely prefixed (``azure/gpt-4o``). ``:`` is not: ``redaction_policy``'s
# secret-assignment rule needs ``[:=]``, and excluding both keeps every one of
# its rules structurally unable to match an admitted value.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]*[A-Za-z0-9])?$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# These are the two concrete lexical false positives reproduced by the target
# deployment. Mask only a complete ``desk-`` or ``task-`` token at the start of
# a name component, then run the unchanged shared secret detector. This is much
# narrower than allowing every mid-string ``sk-``: ``xsk-live-...`` and
# ``desk-sk-live-...`` remain secret-shaped.
_KNOWN_SAFE_SK_TOKEN = re.compile(r"(^|[-/._])(desk|task)-", re.IGNORECASE)


def _mask_known_safe_sk_tokens(value: str) -> str:
    return _KNOWN_SAFE_SK_TOKEN.sub(lambda match: f"{match.group(1)}{match.group(2)[:-2]}zz-", value)


def carries_credential_shape(value: str) -> bool:
    normalized = value.strip().lower()
    return looks_like_secret_value(_mask_known_safe_sk_tokens(normalized))


def is_identifier_shaped(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_IDENTIFIER_LENGTH:
        return False
    if not _IDENTIFIER_RE.match(candidate):
        return False
    return not carries_credential_shape(candidate)


def is_request_path_shaped(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_PATH_LENGTH:
        return False
    if not _PATH_RE.match(candidate):
        return False
    return not carries_credential_shape(candidate)


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_callback_name(value: object) -> bool:
    return isinstance(value, str) and value in CONTENT_FREE_CALLBACKS


def _is_data_policy_class(value: object) -> bool:
    return isinstance(value, str) and value in DATA_POLICY_CLASSES


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def has_declared_grammar(key: str) -> bool:
    return (
        key in HOST_EVIDENCE_KEYS
        or key in HOP_RULE_EVIDENCE_KEYS
        or key in IDENTIFIER_EVIDENCE_KEYS
        or key in PATH_EVIDENCE_KEYS
    )


def is_admissible_evidence_value(key: str, value: object) -> bool:
    if key in HOST_EVIDENCE_KEYS or key in HOP_RULE_EVIDENCE_KEYS:
        return is_admissible_host_evidence(key, value)
    if key in {
        "alias",
        "model_group",
        "cost_contract_reference",
        "content_logging_attestation_reference",
        "tls_attestation_reference",
    }:
        return is_identifier_shaped(value)
    if key == "data_policy_class":
        return _is_data_policy_class(value)
    if key == "content_logging_callbacks":
        return _is_callback_name(value)
    if key in {"content_logging_attested_on", "tls_attested_on"}:
        return _is_iso_date(value)
    if key == "tls_ca_bundle_sha256":
        return _is_sha256(value)
    if key in PATH_EVIDENCE_KEYS:
        return is_request_path_shaped(value)
    return False


__all__ = [
    "IDENTIFIER_EVIDENCE_KEYS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_PATH_LENGTH",
    "PATH_EVIDENCE_KEYS",
    "carries_credential_shape",
    "has_declared_grammar",
    "is_admissible_evidence_value",
    "is_identifier_shaped",
    "is_request_path_shaped",
]
