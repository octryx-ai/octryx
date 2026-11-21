"""Shared redaction policy for secret-bearing retained-backend payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED_SECRET = "[redacted]"

SENSITIVE_KEY_MARKERS = (
    "access_key",
    "access_token",
    "api_key",
    "apikey",
    "auth_header",
    "auth_token",
    "authorization",
    "bearer",
    "bearer_token",
    "client_secret",
    "cookie",
    "credential",
    "encrypted_token",
    "id_token",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_ref",
    "session_token",
    "token_secret",
)
SENSITIVE_VALUE_PREFIXES = (
    "bearer ",
    "basic ",
    "gho_",
    "ghp_",
    "github_pat_",
    "glpat-",
    "sk-",
    "xoxb-",
    "xoxp-",
)
SENSITIVE_VALUE_MARKERS = (
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "aws_secret_access_key",
)

# Setting names whose value is a secret, judged by the name's last word (``KeystorePass``,
# ``db.password``, ``Kennwort``, ``api-key``); camelCase, snake_case, kebab-case and dots all split.
SECRET_SETTING_LAST_WORDS = frozenset(
    {
        "apikey", "credential", "credentials", "kennwort", "pass", "passphrase", "passwd", "password",
        "passwort", "pin", "pwd", "secret", "token",
    }
)
_KEY_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_KEY_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")
# Credentials embedded in a connection string: ``scheme://user:password@`` for any scheme (``jdbc:
# postgresql://``, ``amqp://``) and the JDBC ``user/password@`` form (``jdbc:oracle:thin:scott/tiger@``).
_CREDENTIAL_URL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@")
# A token as the user name without a password (``https://<token>@github.com/...``, the usual form of a Git token).
_CREDENTIAL_HTTP_USER_RE = re.compile(r"(?i)\b(https?://)(?!\[redacted\]@)[^/\s:@]+@")  # not twice
_CREDENTIAL_JDBC_SLASH_RE = re.compile(r"(?i)\b(jdbc:[a-z0-9]+(?::[a-z0-9]+)*:)[^\s/:@]+/[^\s@]+@")
_AUTH_HEADER_RE = re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic)\s+[a-z0-9._~+/=-]{8,}")
_AUTH_TOKEN_RE = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{8,}")
# A secret assigned to a name: the name may carry a prefix (``GITHUB_TOKEN``, ``DB_PASSWORD``, ``db.password``;
# a plain word boundary misses them because ``_`` is a word character), be quoted (JSON ``"password": "…"``) or YAML
# (``password: …``); the value may be quoted with spaces inside. ``max_tokens: 4096``, ``tokenizer=`` and a name
# without a value are no secrets.
_SECRET_NAMES = (r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|session[_-]?token|auth[_-]?token|"
                 r"token|password|passwd|passphrase|secret|client[_-]?secret|private[_-]?key|secret[_-]?access[_-]?key")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![\w.-])([\"']?[\w.-]*?(?:" + _SECRET_NAMES + r")[\"']?)(\s*[:=]\s*)"
    # A quoted value honours escapes; an unquoted one runs to the next whitespace (``password=ab,cd`` is one value).
    r"(\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|\S+)"
)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"(?is)-----begin [^-]*private key-----.*?-----end [^-]*private key-----"
)


def _known_token_patterns() -> list[re.Pattern[str]]:
    """Known secret forms redacted wherever they appear: ``backend/scripts/secret_patterns.py``, the one list the
    transcript rules and the launcher use too."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "secret_patterns.py"
    spec = importlib.util.spec_from_file_location("secret_patterns", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("secret_patterns_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compiled()


_KNOWN_TOKENS = _known_token_patterns()


def is_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    if normalized == "token" or normalized.endswith("_token"):
        return True
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def setting_key_words(key: str) -> list[str]:
    """The lower-case words of a setting name: ``KeystorePass`` -> ``keystore``, ``pass``."""
    split = _KEY_WORD_BOUNDARY.sub("_", str(key or ""))
    return [word.lower() for word in _KEY_WORD_SPLIT.split(split) if word]


def is_secret_setting_key(key: str) -> bool:
    """Whether a configuration setting named ``key`` holds a secret (by name only)."""
    words = setting_key_words(key)
    if not words:
        return False
    if words[-1] in SECRET_SETTING_LAST_WORDS or "".join(words[-2:]) in SECRET_SETTING_LAST_WORDS:
        return True
    return is_sensitive_key(key) or is_sensitive_key("_".join(words))


def has_embedded_credentials(value: Any) -> bool:
    text = str(value or "")
    return bool(_CREDENTIAL_URL_RE.search(text) or _CREDENTIAL_HTTP_USER_RE.search(text)
                or _CREDENTIAL_JDBC_SLASH_RE.search(text))


def redact_embedded_credentials(value: Any) -> tuple[str, int]:
    """``value`` with ``user:password@`` / ``user/password@`` / an http(s) ``token@`` replaced, keeping scheme and
    host."""
    text, url_hits = _CREDENTIAL_URL_RE.subn(lambda match: f"{match.group(1)}{REDACTED_SECRET}@", str(value or ""))
    text, user_hits = _CREDENTIAL_HTTP_USER_RE.subn(lambda match: f"{match.group(1)}{REDACTED_SECRET}@", text)
    text, jdbc_hits = _CREDENTIAL_JDBC_SLASH_RE.subn(lambda match: f"{match.group(1)}{REDACTED_SECRET}@", text)
    return text, url_hits + user_hits + jdbc_hits


def is_secret_setting(key: str, value: Any) -> bool:
    """Whether a configuration setting must never keep its value: secret by name or by value."""
    return is_secret_setting_key(key) or looks_like_secret_value(value)


def looks_like_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    if any(prefix in normalized for prefix in SENSITIVE_VALUE_PREFIXES):
        return True
    if any(marker in normalized for marker in SENSITIVE_VALUE_MARKERS):
        return True
    return bool(
        has_embedded_credentials(value) or _AUTH_TOKEN_RE.search(value) or _SECRET_ASSIGNMENT_RE.search(value)
        or any(pattern.search(value) for pattern in _KNOWN_TOKENS)
    )


def redact_secret_text(value: Any, *, max_chars: int | None = None) -> str:
    text = str(value or "").strip()
    text = _PRIVATE_KEY_BLOCK_RE.sub(REDACTED_SECRET, text)
    text, _hits = redact_embedded_credentials(text)
    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}{match.group(2)} {REDACTED_SECRET}", text)
    text = _AUTH_TOKEN_RE.sub(lambda match: f"{match.group(1)} {REDACTED_SECRET}", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED_SECRET}", text)
    for pattern in _KNOWN_TOKENS:
        text = pattern.sub(REDACTED_SECRET, text)
    if max_chars is not None and len(text) > max_chars:
        return f"{text[:max_chars]}...[truncated]"
    return text


def redact_secret_payload(
    value: Any,
    *,
    key_hint: str = "",
    max_string_length: int | None = None,
    redact_secret_like_strings: bool = True,
) -> Any:
    if is_sensitive_key(key_hint):
        return REDACTED_SECRET
    if isinstance(value, Mapping):
        return {
            str(key): redact_secret_payload(
                item,
                key_hint=str(key),
                max_string_length=max_string_length,
                redact_secret_like_strings=redact_secret_like_strings,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [
            redact_secret_payload(
                item,
                key_hint=key_hint,
                max_string_length=max_string_length,
                redact_secret_like_strings=redact_secret_like_strings,
            )
            for item in value
        ]
    if isinstance(value, str):
        if redact_secret_like_strings and looks_like_secret_value(value):
            return REDACTED_SECRET
        if max_string_length is not None and len(value) > max_string_length:
            return f"{value[:max_string_length]}..."
    return value


def redaction_matrix() -> dict[str, dict[str, str]]:
    return {
        "admin_api": {
            "owner": "backend/app/services/admin",
            "entry_point": "sanitize_admin_audit_value",
            "rule": "redact secret keys and secret-looking values before audit persistence",
        },
        "chat_ui": {
            "owner": "chat-facing API serializers",
            "entry_point": "surface-specific serializers using redaction_policy",
            "rule": "public payloads expose markers or references, never raw secret values",
        },
        "provider_metadata": {
            "owner": "backend/app/services/provider",
            "entry_point": "redact_provider_public_metadata",
            "rule": "redact nested provider credential metadata before admin exposure",
        },
        "traces": {
            "owner": "backend/app/services/trace_events.py",
            "entry_point": "redact_trace_payload",
            "rule": "redact trace payloads before persistence or API serialization",
        },
        "tool_results": {
            "owner": "backend/app/tools/results.py",
            "entry_point": "safe_tool_error_message",
            "rule": "normalize bounded model-visible errors and redact credential-bearing text",
        },
        "source_control_evidence": {
            "owner": "backend/app/services/source_control",
            "entry_point": "sanitize_source_control_payload",
            "rule": "drop forbidden fields and redact credential-bearing provider output",
        },
        "speech": {
            "owner": "backend/app/services/stt and backend/app/services/tts",
            "entry_point": "speech API routes and provider resolution services",
            "rule": "redact provider errors before audit, logs, and HTTP responses; never log transcript/audio content",
        },
        "logs": {
            "owner": "backend/app/services/observability/logging.py",
            "entry_point": "JsonLogFormatter",
            "rule": "redact messages, exceptions, and structured extra metadata before JSON serialization",
        },
    }


__all__ = [
    "REDACTED_SECRET",
    "SECRET_SETTING_LAST_WORDS",
    "SENSITIVE_KEY_MARKERS",
    "has_embedded_credentials",
    "is_secret_setting",
    "is_secret_setting_key",
    "is_sensitive_key",
    "looks_like_secret_value",
    "redact_embedded_credentials",
    "redact_secret_payload",
    "redact_secret_text",
    "redaction_matrix",
    "setting_key_words",
]
