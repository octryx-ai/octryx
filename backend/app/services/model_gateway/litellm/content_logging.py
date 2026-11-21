"""Content-logging and callback posture contract for the LiteLLM gateway.

A LiteLLM deployment can be configured to persist request and response bodies and
to forward them to observability callbacks. If that is on, every prompt this
platform sends — and every credential a prompt happens to contain — is retained
outside the Octryx audit boundary. The gateway's own configuration is
readable only with the master key, which this platform deliberately never holds
so the posture cannot be sniffed at runtime. It is therefore *declared*,
validated deny-by-default here, and carries the source of its verification:

``config_json["litellm_gateway"]["content_logging"]``::

    {
      "mode": "no_content_retention",
      "prompt_retention": "disabled",
      "response_retention": "disabled",
      "key_metadata_retention": "disabled",
      "header_retention": "disabled",
      "success_callbacks": [],
      "failure_callbacks": [],
      "attestation_reference": "litellm-posture-2026-09-27",
      "attested_on": "2026-09-27",
      "verified_against": "live_gateway_configuration"
    }

Prompts are not the only thing a LiteLLM deployment can retain, and the other two
surfaces are the ones that hold the *credential*:

``header_retention``
    Request headers. This is how ``Authorization: Bearer <virtual key>`` gets
    captured by a deployment that logs no request body at all — through proxy
    access logs or a callback that forwards headers.
``key_metadata_retention``
    The key's own identity in spend logs, audit logs and callback metadata
    (LiteLLM's ``redact_user_api_key_info`` / ``store_audit_logs`` surface).

Both are separate operator statements about separate settings. ``header_retention``
must be ``disabled``: a posture that retains no prompt but stores the bearer token
has not protected the credential boundary.

``key_metadata_retention`` admits one honest exception besides ``disabled``:
``retained_by_internal_platform_gateway``. It states that the *identity* of the
virtual key (its alias / hashed token, never the bearer value) is kept in the
spend logs of an internal, platform-operated gateway — the data platform's shared
LiteLLM, which needs it for budget enforcement and cannot switch it off. It is
admitted only when nothing else can carry the key out of that gateway: mode
``no_content_retention``, prompt / response / header retention all ``disabled``,
both callback lists *empty* (not even the content-free ``prometheus``), and the
attestation reference every posture carries. Prompts, responses and headers stay
forbidden; the value is recorded verbatim in the evidence and the qualification
report so no reader mistakes it for ``disabled``.

Neither field is named after a credential marker on purpose. The gateway section
is scanned for credential-looking keys at admission and readiness
(``alias_catalog.config_contains_credential_material``), and that scan is
deliberately broad — a field called ``credential_retention`` would make every
correctly configured provider look like it had a key pasted into its config.

``verified_against`` is the honesty field. ``declared_configuration`` means an
operator asserted the posture but nobody has read the running gateway's
configuration; the qualification report then keeps the live gate open. Only
``live_gateway_configuration`` records that the running deployment was inspected.
Both are admitted for dispatch — a declaration is the operator's accountable
statement — but only one of them can close the activation gate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

CONTENT_LOGGING_MODE_NO_RETENTION = "no_content_retention"
RETENTION_DISABLED = "disabled"
KEY_METADATA_RETAINED_BY_INTERNAL_PLATFORM_GATEWAY = "retained_by_internal_platform_gateway"
KEY_METADATA_RETENTION_STATES = frozenset({RETENTION_DISABLED, KEY_METADATA_RETAINED_BY_INTERNAL_PLATFORM_GATEWAY})

VERIFIED_AGAINST_DECLARED = "declared_configuration"
VERIFIED_AGAINST_LIVE = "live_gateway_configuration"
VERIFICATION_SOURCES = frozenset({VERIFIED_AGAINST_DECLARED, VERIFIED_AGAINST_LIVE})

# Callbacks that provably carry no prompt or response content. Deny-by-default:
# a callback name that is not on this list is refused, because LiteLLM's
# content-forwarding callbacks (langfuse, langsmith, s3, gcs, datadog,
# otel with content, athina, braintrust, custom handlers, ...) all retain
# request/response payloads, and a new one must be reviewed before it is trusted.
CONTENT_FREE_CALLBACKS = frozenset({"prometheus"})

CONTENT_LOGGING_DENIAL_CONTRACT_MISSING = "content_logging_contract_missing"
CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED = "content_logging_mode_not_admitted"
CONTENT_LOGGING_DENIAL_PROMPT_RETENTION = "content_logging_prompt_retention_not_disabled"
CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION = "content_logging_response_retention_not_disabled"
CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION = "content_logging_key_metadata_retention_not_disabled"
CONTENT_LOGGING_DENIAL_HEADER_RETENTION = "content_logging_header_retention_not_disabled"
CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS = (
    "content_logging_key_metadata_retention_requires_no_callbacks"
)
CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED = "content_logging_callbacks_malformed"
CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN = "content_logging_callback_may_retain_content"
CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING = "content_logging_attestation_reference_missing"
CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID = "content_logging_attested_on_invalid"
CONTENT_LOGGING_DENIAL_VERIFICATION_UNKNOWN = "content_logging_verification_source_unknown"

# An attestation reference is a governance record id, not free text: it ends up in
# stored evidence, so its charset is bounded.
_ATTESTATION_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_CALLBACK_NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


@dataclass(frozen=True, slots=True)
class ContentLoggingPosture:
    mode: str
    prompt_retention: str
    response_retention: str
    key_metadata_retention: str
    header_retention: str
    success_callbacks: tuple[str, ...]
    failure_callbacks: tuple[str, ...]
    attestation_reference: str
    attested_on: str
    verified_against: str

    @property
    def key_metadata_retained(self) -> bool:
        """True when the key's identity is kept by the internal platform gateway."""

        return self.key_metadata_retention != RETENTION_DISABLED

    @property
    def live_confirmed(self) -> bool:
        """True only when the running gateway configuration was inspected."""

        return self.verified_against == VERIFIED_AGAINST_LIVE

    def evidence(self) -> dict[str, Any]:
        return {
            "content_logging_mode": self.mode,
            "content_logging_prompt_retention": self.prompt_retention,
            "content_logging_response_retention": self.response_retention,
            "content_logging_key_metadata_retention": self.key_metadata_retention,
            "content_logging_header_retention": self.header_retention,
            "content_logging_callbacks": sorted({*self.success_callbacks, *self.failure_callbacks}),
            "content_logging_attestation_reference": self.attestation_reference,
            "content_logging_attested_on": self.attested_on,
            "content_logging_verified_against": self.verified_against,
        }


def _normalized_callbacks(raw: Any) -> tuple[tuple[str, ...] | None, str]:
    if raw is None:
        # Absent is not empty: an operator who did not state the callback list has
        # not verified it.
        return None, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        return None, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED
        name = item.strip().lower()
        if not _CALLBACK_NAME_RE.match(name):
            return None, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED
        if name not in CONTENT_FREE_CALLBACKS:
            return None, CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN
        names.append(name)
    return tuple(sorted(set(names))), ""


def resolve_content_logging_posture(section: Any) -> tuple[ContentLoggingPosture | None, str]:
    """Resolve the declared posture, or a fixed denial code."""

    raw = section.get("content_logging") if isinstance(section, Mapping) else None
    if not isinstance(raw, Mapping):
        return None, CONTENT_LOGGING_DENIAL_CONTRACT_MISSING
    if str(raw.get("mode") or "").strip().lower() != CONTENT_LOGGING_MODE_NO_RETENTION:
        return None, CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED
    if str(raw.get("prompt_retention") or "").strip().lower() != RETENTION_DISABLED:
        return None, CONTENT_LOGGING_DENIAL_PROMPT_RETENTION
    if str(raw.get("response_retention") or "").strip().lower() != RETENTION_DISABLED:
        return None, CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION
    # Deny-by-default like the two above: an absent field is an unverified field,
    # and the credential boundary is the one this platform cannot re-establish
    # after the fact. The one admitted alternative to ``disabled`` is the
    # internal platform gateway's own spend log, gated on empty callbacks below.
    key_metadata_retention = str(raw.get("key_metadata_retention") or "").strip().lower()
    if key_metadata_retention not in KEY_METADATA_RETENTION_STATES:
        return None, CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION
    if str(raw.get("header_retention") or "").strip().lower() != RETENTION_DISABLED:
        return None, CONTENT_LOGGING_DENIAL_HEADER_RETENTION
    success, success_denial = _normalized_callbacks(raw.get("success_callbacks"))
    if success is None:
        return None, success_denial
    failure, failure_denial = _normalized_callbacks(raw.get("failure_callbacks"))
    if failure is None:
        return None, failure_denial
    if key_metadata_retention != RETENTION_DISABLED and (success or failure):
        # A callback is a path out of the gateway; with the key's identity in the
        # spend log, the only admitted posture is one with no path out at all.
        return None, CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS
    reference = str(raw.get("attestation_reference") or "").strip()
    if not _ATTESTATION_REFERENCE_RE.match(reference):
        return None, CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING
    attested_on = str(raw.get("attested_on") or "").strip()
    try:
        date.fromisoformat(attested_on)
    except ValueError:
        return None, CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID
    verified_against = str(raw.get("verified_against") or "").strip().lower()
    if verified_against not in VERIFICATION_SOURCES:
        return None, CONTENT_LOGGING_DENIAL_VERIFICATION_UNKNOWN
    return (
        ContentLoggingPosture(
            mode=CONTENT_LOGGING_MODE_NO_RETENTION,
            prompt_retention=RETENTION_DISABLED,
            response_retention=RETENTION_DISABLED,
            key_metadata_retention=key_metadata_retention,
            header_retention=RETENTION_DISABLED,
            success_callbacks=success,
            failure_callbacks=failure,
            attestation_reference=reference,
            attested_on=attested_on,
            verified_against=verified_against,
        ),
        "",
    )


__all__ = [
    "CONTENT_FREE_CALLBACKS",
    "CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING",
    "CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID",
    "CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED",
    "CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN",
    "CONTENT_LOGGING_DENIAL_CONTRACT_MISSING",
    "CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION",
    "CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS",
    "CONTENT_LOGGING_DENIAL_HEADER_RETENTION",
    "CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED",
    "CONTENT_LOGGING_DENIAL_PROMPT_RETENTION",
    "CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION",
    "CONTENT_LOGGING_DENIAL_VERIFICATION_UNKNOWN",
    "CONTENT_LOGGING_MODE_NO_RETENTION",
    "KEY_METADATA_RETAINED_BY_INTERNAL_PLATFORM_GATEWAY",
    "KEY_METADATA_RETENTION_STATES",
    "RETENTION_DISABLED",
    "VERIFICATION_SOURCES",
    "VERIFIED_AGAINST_DECLARED",
    "VERIFIED_AGAINST_LIVE",
    "ContentLoggingPosture",
    "resolve_content_logging_posture",
]
