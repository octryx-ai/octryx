"""Whether a URI or a provider-controlled text field carries a credential, as a closed finding code."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ..redaction_policy import is_sensitive_key

# A finding never contains the URI, so it is safe to report and persist.
CREDENTIAL_FINDING_USERINFO = "uri_userinfo"
CREDENTIAL_FINDING_QUERY = "uri_credential_query_parameter"
CREDENTIAL_FINDING_SECRET_VALUE = "uri_secret_value"
MCP_RESOURCE_CREDENTIAL_FINDINGS = (
    CREDENTIAL_FINDING_USERINFO,
    CREDENTIAL_FINDING_QUERY,
    CREDENTIAL_FINDING_SECRET_VALUE,
)

# Presigned / bearer query names that ``is_sensitive_key`` (``*_token``, ``*secret*``) does not cover.
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
# Anchored at a token start so a long run of words is scanned once, not once per character.
_EMBEDDED_URI_RE = re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^\s<>\"')\]]+")
# The prefix must start a token ("sk-" in "risk-report" is wording); 12+ trailing chars keep a bare prefix out.
# Each prefix ends in its own delimiter, so none can head an ordinary word.
_TOKEN_PREFIX_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\-])(?:sk-|gho_|ghp_|ghu_|ghs_|github_pat_|glpat-|xox[abpsr]-)"
    r"[A-Za-z0-9_\-]{12,}"
)
# Exact, case-sensitive, whole-token shape: ``akia``/``asia`` head ordinary words ("asia-pacific"), so they
# cannot join the case-insensitive prefix rule above.
_AWS_ACCESS_KEY_ID_RE = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")
# The scheme alone proves nothing ("Basic reporting guidance"); the token must look like credential material.
_AUTH_SCHEME_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]{12,})")
# The full value is captured: checking only its first token would let ``Required <secret>`` hide material.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:api[-_ ]?key|access[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token"
    r"|session[-_ ]?token|client[-_ ]?secret|secret[-_ ]?key|private[-_ ]?key|aws[-_ ]?secret[-_ ]?access[-_ ]?key"
    r"|authorization|password|passwd|token|secret)\s*[:=]\s*['\"]?([^\r\n'\",;&]{1,160})"
)
# Labels double as documentation fields: only these closed statuses pass; any other value is a finding.
_SAFE_SECRET_ASSIGNMENT_STATUS_RE = re.compile(
    r"(?i)^(?:"
    r"approved(?:\s+by\s+the\s+board)?"
    r"|configured\s+elsewhere"
    r"|disabled"
    r"|inherited(?:\s+from\s+the\s+workspace\s+binding)?"
    r"|managed\s+externally"
    r"|not\s+(?:applicable|configured|provided|set)"
    r"|provided(?:-|\s+)on(?:-|\s+)request"
    # ``redact_secret_text`` rewrites accepted statuses; the persisted projection must still pass on re-check.
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

# Persisted provider strings are bounded well below this; the cap keeps a hostile megabyte-long name cheap to scan.
_MAX_CREDENTIAL_SCAN_CHARS = 4096


def _structured_uri_finding(candidate: str) -> str:
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
    candidate = str(value or "").strip()
    return bool(candidate and _SAFE_SECRET_ASSIGNMENT_STATUS_RE.fullmatch(candidate))


def mcp_resource_uri_credential_finding(uri: Any) -> str:
    candidate = str(uri or "").strip()
    if not candidate:
        return ""
    finding = _structured_uri_finding(candidate)
    if finding:
        return finding
    return mcp_resource_text_credential_finding(candidate)


def mcp_resource_text_credential_finding(value: Any) -> str:
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
