"""Line-preserving secret redaction of repository files before they become evidence.

Both fetch modes of a ``git_repository`` source (the host archive and a launcher's local snapshot)
pass every file through this one step, so the same commit yields the same revisions either way.

Redaction never adds or removes a line: a line range cited against the redacted text is the same
range in the repository. Replaced are, within their line:

- credentials in connection strings (``scheme://user:pass@host`` for any scheme, the JDBC
  ``jdbc:oracle:thin:user/pass@host`` form), keeping the scheme and host;
- ``Authorization: Bearer|Basic <token>`` values and bare ``Bearer <token>``;
- vendor tokens by their prefix (``ghp_``, ``github_pat_``, ``glpat-``, ``xoxb-``, ``sk-`` ...) at a
  realistic length, and AWS access key ids;
- every line inside a private-key block, including its BEGIN and END lines.

In source code, generic ``password=`` assignments are deliberately not redacted: they name a
variable whose name is the fact a reader asks about. In a **configuration file** (``path`` given and
``is_config_path``: ``.ini``, ``.properties``, ``.yaml``, ``.env`` ... and the structured profile's
configuration globs) the *value* of every setting the shared policy names secret
(``redaction_policy.is_secret_setting_key``: ``KeystorePass``, ``Pwd``, ``Passwort``, ``api-key``)
is replaced and the key kept, together with its continuation lines (an INI ``+`` line, a trailing
backslash, an indented YAML block scalar). The redaction count per file is reported; the text that
was replaced never is.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ...redaction_policy import (
    REDACTED_SECRET,
    SENSITIVE_VALUE_PREFIXES,
    is_secret_setting_key,
    redact_embedded_credentials,
)
from ..structured.profile import structured_profile

_TOKEN_PREFIXES = tuple(prefix for prefix in SENSITIVE_VALUE_PREFIXES if not prefix.endswith(" "))
_VENDOR_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(prefix) for prefix in _TOKEN_PREFIXES) + r")[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY_ID = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
_AUTH_TOKEN = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{16,}")
_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
CONFIG_FILE_SUFFIXES = (".cfg", ".conf", ".env", ".ini", ".properties", ".toml", ".yaml", ".yml")
_COMMENT_PREFIXES = ("#", ";", "!", "//")
# ``key = value`` / ``key: value`` / ``- key: value`` / ``export KEY=value``, key quoted or not.
_ASSIGNMENT = re.compile(
    r"^(?P<lead>\s*(?:-\s+|export\s+)?[\"']?)(?P<key>[A-Za-z0-9_.$\[\]-]+)(?P<sep>[\"']?\s*[=:]\s*)(?P<value>.*?)\s*$"
)
_BLOCK_SCALAR = re.compile(r"^[|>][0-9+-]*$")


@dataclass(frozen=True, slots=True)
class RedactedFile:
    text: str
    redactions: int


def is_config_path(path: str | None) -> bool:
    """Whether ``path`` is a configuration file whose secret-named settings lose their values."""
    if not path:
        return False
    name = PurePosixPath(str(path)).name.lower()
    if name.endswith(CONFIG_FILE_SUFFIXES) or name.startswith(".env"):
        return True
    return any(fnmatch.fnmatch(name, rule.glob.lower()) for rule in structured_profile().config_files)


def _line(line: str) -> tuple[str, int]:
    count = 0
    line, hits = redact_embedded_credentials(line)
    count += hits
    line, hits = _AUTH_TOKEN.subn(lambda match: f"{match.group(1)} {REDACTED_SECRET}", line)
    count += hits
    line, hits = _VENDOR_TOKEN.subn(REDACTED_SECRET, line)
    count += hits
    line, hits = _AWS_ACCESS_KEY_ID.subn(REDACTED_SECRET, line)
    return line, count + hits


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _redact_config_settings(lines: list[str]) -> int:
    """Replace the values of secret-named settings (and their continuation lines) in place."""
    redactions = 0
    continues = False  # the previous line was a redacted value; a ``+`` line continues it
    backslash = False  # ... and that line ended with a backslash, so the next line continues it
    block_indent: int | None = None  # a redacted YAML block scalar: deeper lines belong to it
    for index, line in enumerate(lines):
        stripped = line.strip()
        if block_indent is not None:
            if not stripped or _indent(line) > block_indent:
                if stripped:
                    lines[index], redactions = line[: _indent(line)] + REDACTED_SECRET, redactions + 1
                continue
            block_indent = None
        if continues and (backslash or stripped.startswith("+")):
            backslash = stripped.endswith("\\")
            lines[index], redactions = line[: _indent(line)] + REDACTED_SECRET, redactions + 1
            continue
        continues = backslash = False
        if not stripped or stripped.startswith(_COMMENT_PREFIXES):
            continue
        match = _ASSIGNMENT.match(line)
        if match is None or not is_secret_setting_key(match.group("key")):
            continue
        value = match.group("value")
        if _BLOCK_SCALAR.match(value):
            block_indent = _indent(line)
            continue
        if not value or value.strip("\"'") == REDACTED_SECRET:
            continue
        lines[index] = f"{match.group('lead')}{match.group('key')}{match.group('sep')}{REDACTED_SECRET}"
        redactions += 1
        continues, backslash = True, value.endswith("\\")
    return redactions


def redact_repository_text(text: str, path: str | None = None) -> RedactedFile:
    """``text`` with its secrets replaced line by line; the number of lines never changes.

    ``path`` (repository-relative) turns on the configuration-file setting rule (module docstring).
    """
    lines = text.split("\n")
    redactions = 0
    in_key = False
    for index, line in enumerate(lines):
        if in_key or _KEY_BEGIN.search(line):
            in_key = not _KEY_END.search(line)
            lines[index] = REDACTED_SECRET
            redactions += 1
            continue
        lines[index], hits = _line(line)
        redactions += hits
    if is_config_path(path):
        redactions += _redact_config_settings(lines)
    return RedactedFile("\n".join(lines), redactions)


__all__ = ["CONFIG_FILE_SUFFIXES", "RedactedFile", "is_config_path", "redact_repository_text"]
