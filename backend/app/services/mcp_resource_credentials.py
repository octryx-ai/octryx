"""Whether a URI or a provider-controlled text field carries a credential.

The findings are a closed vocabulary: a narrow-charset fact about a value, never
the value itself, so a finding is safe to report and persist. ``mcp_resource_arguments``
keeps such values out of persisted arguments, the mirror refuses them, and the
decision denies a binding that still holds one.

**A credential-bearing URI denies, it is not redacted and forwarded.**
``mcp_resource_uri_credential_finding`` names why a URI carries a credential
from a closed vocabulary. The mirror refuses such a URI, so it never becomes
addressable, and the decision judges every stored binding again with the rules in
force when it is used, so a binding that holds one fails closed.

**Every provider-controlled field is held to the same rule, not just the URI.**
A resource or prompt name, a description, a media type, and a prompt argument's
description are all written by the remote server and all reach the model, the
admin catalog, the mirror report, and — for identities — the audit record.
``mcp_resource_text_credential_finding`` applies the three findings to free text,
so a ``postgres://`` userinfo or an S3 presign query pasted into a description is
refused by the mirror and denied by the decision instead of surviving the generic
redactor.

**The two rules are field-aware, and the free-text one is anchored.** A URI field
is parsed as a URI: userinfo in the authority, and credential query parameters
from the parsed query string. A free-text field is *wording* first and a
credential carrier second, so it is never matched by substring. Every free-text
rule is either structured (an embedded URI is extracted and then parsed as a URI)
or anchored (a key prefix must start a token) or exact (an AWS access key
identifier is ``AKIA``/``ASIA`` plus sixteen uppercase alphanumerics, nothing
else). Where a rule recognises only a *label*, the value is evaluated by the
grammar that owns that label. ``bearer``/``basic`` need credential-shaped auth
material; an explicit secret assignment fails closed unless its complete value
is one of a small, closed set of documentation statuses such as ``Required for
download`` or ``Undisclosed``. The two cases deliberately do not share a
heuristic: an eight-character password can be real even though an eight-character
word after ``Basic`` is usually prose.

Loose matching is what made ordinary wording read as a secret, in three waves:
substrings ("risk-report", "task-summary", "desk-review", "Basic reporting
guidance", because ``looks_like_secret_value`` tests ``"sk-"`` and ``"basic "``
as substrings); a case-insensitive delimiter-free ``akia``/``asia`` prefix
("asia-pacific-operations", "asia_pacific_summary", "asiapacificoperations",
"akianakamura-reports"); and a secret label with any eight-character value
("Password: Required", "Authorization: Approved by the board",
"Token: unlimited", "secret: undisclosed"). A false rejection is not free: it
withholds a governed item, so the rules have to be precise in both directions.

Everything here is pure: no database, no MCP client, no connection configuration.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .redaction_policy import is_sensitive_key

# Closed finding vocabulary. A finding is a narrow-charset fact about a URI; the
# URI itself is never part of it, so a finding is safe to report and persist.
CREDENTIAL_FINDING_USERINFO = "uri_userinfo"
CREDENTIAL_FINDING_QUERY = "uri_credential_query_parameter"
CREDENTIAL_FINDING_SECRET_VALUE = "uri_secret_value"
MCP_RESOURCE_CREDENTIAL_FINDINGS = (
    CREDENTIAL_FINDING_USERINFO,
    CREDENTIAL_FINDING_QUERY,
    CREDENTIAL_FINDING_SECRET_VALUE,
)

# Presigned-URL and bearer-style query parameters across the object stores and
# SAS schemes this platform can be pointed at. ``is_sensitive_key`` covers the
# generic ``*_token`` / ``*secret*`` family; these are the names it does not.
_CREDENTIAL_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "awsaccesskeyid",
        "credential",
        "key-pair-id",
        "password",
        "policy",
        "sas",
        "sig",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "x-goog-credential",
        "x-goog-signature",
    }
)
# Userinfo in *any* scheme's authority, not only ``http(s)``.
_USERINFO_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/?#\s]*@")
# One embedded URI inside a free-text field, taken as a whole and then parsed by
# the URI rule. Anchored at a token start so a long run of ordinary words is
# scanned once rather than once per character.
_EMBEDDED_URI_RE = re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^\s<>\"')\]]+")
# Key material that announces itself by prefix. The prefix must *start* a token:
# "sk-" inside "risk-report" is wording, "sk-" followed by an opaque token is a
# key. Twelve trailing token characters keep a bare prefix from matching. Every
# prefix listed here ends in its own delimiter (``-`` or ``_``), so none of them
# can be the head of an ordinary word.
_TOKEN_PREFIX_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\-])(?:sk-|gho_|ghp_|ghu_|ghs_|github_pat_|glpat-|xox[abpsr]-)"
    r"[A-Za-z0-9_\-]{12,}"
)
# An AWS access key identifier has one exact shape: uppercase ``AKIA`` (long-term)
# or ``ASIA`` (STS) followed by exactly sixteen uppercase alphanumerics. It is
# matched case-*sensitively* and as a whole token, because ``akia``/``asia`` are
# delimiter-free prefixes of ordinary words: folded into the case-insensitive
# prefix rule above they turned "asia-pacific-operations", "asia_pacific_summary",
# "asiapacificoperations" and "akianakamura-reports" into credential findings. The
# exact shape refuses every identifier AWS issues and no wording.
_AWS_ACCESS_KEY_ID_RE = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")
# ``Authorization: Bearer <material>`` and friends. The scheme alone proves
# nothing — "Basic reporting guidance" is a sentence — so the token that follows
# has to look like credential material (``_is_auth_credential_material``).
_AUTH_SCHEME_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]{12,})")
# ``<secret name> = <value>`` anchored on a closed list of secret names. The full
# value (up to a field separator or newline) is captured: inspecting only its
# first token would let ``Required <secret>`` hide material later in the field.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:api[-_ ]?key|access[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token"
    r"|session[-_ ]?token|client[-_ ]?secret|secret[-_ ]?key|private[-_ ]?key|aws[-_ ]?secret[-_ ]?access[-_ ]?key"
    r"|authorization|password|passwd|token|secret)\s*[:=]\s*['\"]?([^\r\n'\",;&]{1,160})"
)
# A secret label is also used as a documentation field label. Only these closed,
# non-secret status phrases are accepted. Every other non-empty assigned value is
# ambiguous and therefore a credential finding, including short, alphabetic and
# hex values. This is intentionally stricter than the auth-scheme heuristic.
_SAFE_SECRET_ASSIGNMENT_STATUS_RE = re.compile(
    r"(?i)^(?:"
    r"approved(?:\s+by\s+the\s+board)?"
    r"|configured\s+elsewhere"
    r"|disabled"
    r"|inherited(?:\s+from\s+the\s+workspace\s+binding)?"
    r"|managed\s+externally"
    r"|not\s+(?:applicable|configured|provided|set)"
    r"|provided(?:-|\s+)on(?:-|\s+)request"
    # ``redact_secret_text`` rewrites accepted status values under labels it also
    # owns. The persisted projection must remain recognisably non-secret when the
    # policy re-checks it; ``Password: Required for download`` becomes the first
    # form below, while single-token statuses become the second.
    r"|\[redacted\](?:\s+for\s+download)?"
    r"|redacted"
    r"|required(?:\s+for\s+download)?"
    r"|unavailable"
    r"|undisclosed(?:\s+by\s+the\s+vendor)?"
    r"|unlimited"
    r"|unspecified"
    r")\s*[.!]?\s*$"
)
_PRIVATE_KEY_RE = re.compile(r"(?i)-----begin [a-z ]*private key-----")
# Word shapes that make a token ordinary wording rather than credential material.
_WORD_SEGMENT_RE = re.compile(r"[A-Za-z]{1,24}")
_TOKEN_SEGMENT_SPLIT_RE = re.compile(r"[-_.~+/=]+")
_MIN_CREDENTIAL_MATERIAL_CHARS = 16

# Every provider-controlled string that reaches persistence is bounded well below
# this (a mirrorable name by the identifier rule, a description by 500
# characters, a media type by 120), so scanning a wider window than any persisted
# projection is sufficient — and the bound keeps a hostile megabyte-long name
# from turning credential inspection into the expensive part of a mirror run.
_MAX_CREDENTIAL_SCAN_CHARS = 4096


def _structured_uri_finding(candidate: str) -> str:
    """Return the finding a *parsed* URI carries, or ``""``.

    Structured on purpose: the authority is read for userinfo and the query is
    read as query parameters, so nothing here depends on where a substring
    happens to appear.
    """
    if _USERINFO_RE.match(candidate):
        return CREDENTIAL_FINDING_USERINFO
    try:
        query = urlsplit(candidate).query
    except ValueError:
        # An unparseable authority is not something this platform addresses.
        return CREDENTIAL_FINDING_SECRET_VALUE
    for name, _value in parse_qsl(query, keep_blank_values=True):
        normalized = str(name or "").strip().lower()
        if normalized in _CREDENTIAL_QUERY_PARAMS or is_sensitive_key(normalized):
            return CREDENTIAL_FINDING_QUERY
    return ""


def _is_auth_credential_material(token: str) -> bool:
    """Whether a bearer/basic token is material rather than ordinary wording.

    Ordinary wording decomposes into alphabetic segments in one case pattern —
    ``risk-management-report``, ``Troubleshooting-Documentation``, ``Required``,
    ``undisclosed``. Credential material does not: it is base64, hex, or
    otherwise mixed. Short tokens are never material, which is what keeps "Basic
    reporting" a sentence.

    This heuristic belongs only to an auth scheme followed by whitespace. An
    explicit ``password=...`` assignment is stronger evidence and is evaluated
    separately by ``_is_safe_secret_assignment_status``.
    """
    if len(token) < _MIN_CREDENTIAL_MATERIAL_CHARS:
        return False
    segments = [segment for segment in _TOKEN_SEGMENT_SPLIT_RE.split(token) if segment]
    if not segments:
        return False
    return not all(
        _WORD_SEGMENT_RE.fullmatch(segment) and (segment.islower() or segment.istitle() or segment.isupper())
        for segment in segments
    )


def _is_safe_secret_assignment_status(value: str) -> bool:
    """Whether an explicit secret field contains known documentation prose.

    Classification of arbitrary prose as a password is not reliable. The safe
    direction is therefore a closed grammar: well-known non-secret status phrases
    pass, while every other assigned value is ambiguous and fails closed.
    """
    candidate = str(value or "").strip()
    return bool(candidate and _SAFE_SECRET_ASSIGNMENT_STATUS_RE.fullmatch(candidate))


def mcp_resource_uri_credential_finding(uri: Any) -> str:
    """Return why this URI carries a credential, or ``""`` when it does not.

    Deliberately conservative *about URIs*: a false positive costs one resource
    an admin can re-publish without the credential, a false negative publishes
    the credential. The free-text rule is consulted last, for a URI that embeds
    another URI or that carries assigned secret material the structured parse
    did not reach.
    """
    candidate = str(uri or "").strip()
    if not candidate:
        return ""
    finding = _structured_uri_finding(candidate)
    if finding:
        return finding
    return mcp_resource_text_credential_finding(candidate)


def mcp_resource_text_credential_finding(value: Any) -> str:
    """Return why this free-text field carries a credential, or ``""``.

    Names, descriptions, media types, and prompt argument descriptions are all
    provider-controlled and all reach the model, the admin UI, and the mirror
    report. ``redact_secret_text`` rewrites URI userinfo but not every credential
    shape (a presign query), so the shapes it misses have to be recognised here — but they are recognised
    *structurally*: an embedded URI is extracted and parsed as a URI, a key
    prefix must start a token, an AWS access key identifier must match its exact
    uppercase shape, and an auth scheme must be followed by a value
    ``_is_auth_credential_material`` accepts. An explicit secret assignment is
    refused unless its complete value matches the closed documentation-status
    grammar. Nothing is matched as a bare substring and no marker decides on its own, so ordinary
    risk/task/desk/basic/asia-pacific wording and ordinary field labels
    ("Password: Required") are accepted and only real credential shapes are
    refused.
    """
    text = str(value or "").strip()[:_MAX_CREDENTIAL_SCAN_CHARS]
    if not text:
        return ""
    for match in _EMBEDDED_URI_RE.finditer(text):
        finding = _structured_uri_finding(match.group(0))
        if finding:
            return finding
    if _PRIVATE_KEY_RE.search(text) or _TOKEN_PREFIX_RE.search(text) or _AWS_ACCESS_KEY_ID_RE.search(text):
        return CREDENTIAL_FINDING_SECRET_VALUE
    for match in _AUTH_SCHEME_RE.finditer(text):
        if _is_auth_credential_material(match.group(1)):
            return CREDENTIAL_FINDING_SECRET_VALUE
    for match in _SECRET_ASSIGNMENT_RE.finditer(text):
        if not _is_safe_secret_assignment_status(match.group(1)):
            return CREDENTIAL_FINDING_SECRET_VALUE
    return ""


__all__ = [
    "CREDENTIAL_FINDING_QUERY",
    "CREDENTIAL_FINDING_SECRET_VALUE",
    "CREDENTIAL_FINDING_USERINFO",
    "MCP_RESOURCE_CREDENTIAL_FINDINGS",
    "mcp_resource_text_credential_finding",
    "mcp_resource_uri_credential_finding",
]
