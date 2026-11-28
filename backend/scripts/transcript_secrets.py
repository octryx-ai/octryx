"""One secret rule set for full session transcripts, on the Mac and on the platform.

In a local test with test values two secrets reached the platform's store. An
``.env`` read with ``STRIPE_KEY=sk_live_…`` came through unredacted while ``DATABASE_URL`` was redacted. The output
of ``aws secretsmanager get-secret-value`` also came through: ``{"password": "…"}`` as JSON inside a string. The
platform only applied the shape patterns of the session lessons, which name neither ``*_KEY`` assignments, Stripe
keys nor JSON fields. The launcher's whole-output rule for secret commands and credential files did not exist on
the platform at all, so a batch that reached the platform any other way kept them.

Stdlib only. The platform imports this file (``app/services/session_transcripts/redaction``) and so does the
launcher, through the copy the platform vendors into the client package (``octryx_claude/_platform_scripts``, like
the finalize digest's redactor). The same rules therefore apply when the launcher sends a line, when the platform
stores it and when the platform serves it:

1. ``KEY=VALUE`` and ``KEY: VALUE`` when the name is secret-like (``KEY``, ``TOKEN``, ``SECRET``, ``PASSWORD``,
   ``PASSWD``, ``PWD``, ``CREDENTIAL``, ``PRIVATE``, ``AUTH``, ``API_KEY``, ``ACCESS_KEY``, ``CONNECTION_STRING``,
   case-insensitive, also as part of a name such as ``STRIPE_KEY``);
2. known prefixes and formats (``secret_patterns.py``, the one list shared with the platform): Stripe
   ``sk_live_``/``sk_test_``/``rk_``, Anthropic/OpenAI ``sk-``, GitHub, Slack, AWS access key ids, GitLab
   ``glpat-``, JWTs; PEM private-key blocks, ``Bearer``/``Basic`` headers, URLs with ``user:pass@``;
3. JSON fields such as ``password``, ``secret``, ``token``, ``api_key``, ``access_key``, ``private_key``,
   ``client_secret``, ``SecretString`` and Octryx's ``confirmation_ticket``, also escaped inside a string and nested;
4. the output of a command that prints a secret (:data:`SECRET_COMMANDS`) or of a read of a credential file
   (``.env*``, ``*.pem``, ``*.key``, ``id_*``, ``.npmrc``, ``.netrc``, ``credentials`` …) is replaced as a whole.

A line's dict key that names a secret (``password``, ``client_secret`` …) gets its string value replaced too.
Over-redaction (code such as ``token: str``) is accepted. A secret value never stays.
"""

from __future__ import annotations

import copy
import posixpath
import re
from typing import Any

REDACTED = "[redacted]"
SECRET_OUTPUT = "[redacted: output of a secret command or credential file]"

_SECRET_WORDS = r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|PRIVATE|AUTH|API_KEY|ACCESS_KEY|CONNECTION_STRING)"
_SECRET_NAME = rf"[A-Za-z0-9_.-]*{_SECRET_WORDS}[A-Za-z0-9_.-]*"
_JSON_WORDS = (r"(?:password|passwd|secret|token|api_?key|access_?key|private_?key|client_?secret|credential"
               r"|confirmation_ticket)")
_JSON_NAME = rf"[A-Za-z0-9_.-]*{_JSON_WORDS}[A-Za-z0-9_.-]*"

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S)
# JSON fields: plain (``"password": "x"``) and escaped inside a string (``{\"password\": \"x\"}``, any depth).
_JSON_FIELD = re.compile(rf'("{_JSON_NAME}"\s*:\s*)"(?:[^"\\]|\\.)*"', re.I)
_JSON_FIELD_ESCAPED = re.compile(rf'((?<!\\)(\\+)"{_JSON_NAME}\2"\s*:\s*\2")(.*?)(?<!\\)(\2")', re.I)
_ASSIGNMENT = re.compile(
    rf"(?<![A-Za-z0-9_.-])({_SECRET_NAME})(\s*[=:]\s*)(?!\[redacted)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;}}\]]+)",
    re.I,
)
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@")
_AUTH_HEADER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")


def _known_tokens() -> list[re.Pattern[str]]:
    """``secret_patterns.py`` next to this file (in the checkout, the image and the launcher's vendored copy)."""
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("secret_patterns", Path(__file__).with_name("secret_patterns.py"))
    if spec is None or spec.loader is None:
        raise ImportError("secret_patterns")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compiled()


_TOKENS = _known_tokens()

# Commands whose output is a secret's raw value: the same list as the live progress
# (``octryx_claude.live_progress.SECRET_COMMANDS``; a launcher test keeps the two equal).
SECRET_COMMANDS = re.compile(
    r"\b(aws\s+(secretsmanager|ssm|kms|sts|iam\s+create-access-key|ecr\s+get-login|configure\s+(get|export))"
    r"|kubectl\b[^;&|\n]*\b(secrets?|serviceaccount|token|config\s+view)\b"
    r"|oc\b[^;&|\n]*\bsecrets?\b"
    r"|helm\s+get\s+values"
    r"|vault\s+(kv|read|write|token|login|print|secrets)"
    r"|gcloud\b[^;&|\n]*\b(secrets|auth\s+(print-access-token|print-identity-token|application-default))"
    r"|az\s+(keyvault|account\s+get-access-token|ad\s+sp\s+credential)"
    r"|op\s+(read|item|inject|signin|document)"
    r"|gh\s+auth\s+(token|status)"
    r"|git\s+credential|git\s+config\b[^;&|\n]*\b(credential|token|password)"
    r"|docker\s+(login|secret)|podman\s+login"
    r"|doppler\s+(secrets|run)|pass\s+(show|ls|find|grep)|gopass|bw\s+(get|list|unlock)|lpass\s+show"
    r"|sops\s+(-d|--decrypt|exec)|age\s+(-d|--decrypt)|gpg\s+(-d|--decrypt)"
    r"|keychain|security\s+find-|npm\s+token|cat\s+[^;&|\n]*\.(npmrc|netrc|pgpass))",
    re.IGNORECASE,
)
# Credential files by their name. ``id_*`` without an extension (``id_rsa``, ``id_ed25519``), so ``id_utils.py``
# stays readable.
CREDENTIAL_FILE = re.compile(
    r"^(\.env(\..*)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_[A-Za-z0-9_-]+|\.npmrc|\.netrc|\.pgpass|\.pypirc"
    r"|\.git-credentials|\.dockercfg|credentials(\.(json|ya?ml|ini|txt))?)$",
    re.I,
)
_COMMAND_WORDS = re.compile(r"[\s;&|<>()'\"=`]+")
_FILE_TOOLS = frozenset({"Read", "NotebookRead"})
_SENSITIVE_KEY = re.compile(rf"^{_JSON_NAME}$|^(authorization|cookie|SecretString|connection_?string)$", re.I)
_NOT_SECRET_KEYS = frozenset({"input_tokens", "output_tokens", "cache_creation_input_tokens",
                              "cache_read_input_tokens", "max_tokens", "tool_use_id"})


def redact_text(text: str) -> str:
    """``text`` without secret values (rules 1-3); everything else stays as it was, whitespace included."""
    if not text:
        return text
    text = _PEM.sub(REDACTED, text)
    text = _JSON_FIELD.sub(lambda match: f'{match.group(1)}"{REDACTED}"', text)
    text = _JSON_FIELD_ESCAPED.sub(lambda match: f"{match.group(1)}{REDACTED}{match.group(4)}", text)
    text = _URL_CREDENTIALS.sub(lambda match: f"{match.group(1)}{REDACTED}@", text)
    text = _AUTH_HEADER.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
    for pattern in _TOKENS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(_assignment, text)


# Names that hold a key in the sense of an identifier, never a credential: ``project_key: CHEF``, ``issue_key: CHEF-1``.
# Masking them would turn ``project_key: CHEF`` on a write-plan card into ``[redacted]``, so the card and the
# confirmed plan would not say where a write lands.
_IDENTIFIER_KEYS = frozenset({
    "project_key", "issue_key", "ticket_key", "space_key", "epic_key", "parent_key", "source_key", "item_key",
    "jira_project_key", "board_key", "repo_key", "repository_key", "sort_key", "primary_key", "foreign_key",
    "partition_key", "cache_key", "op_key", "definition_key", "page_key",
})


def _assignment(match: re.Match[str]) -> str:
    if match.group(1).lower() in _IDENTIFIER_KEYS:
        return match.group(0)
    value = match.group(3)
    quote = value[0] if value[:1] in ("'", '"') else ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED}{quote}"


def credential_file(path: str) -> bool:
    name = posixpath.basename(str(path or "").replace("\\", "/").rstrip("/"))
    return bool(name and CREDENTIAL_FILE.match(name))


def secret_source(name: str, tool_input: Any) -> bool:
    """Whether a tool call's output may be a secret's raw value (rule 4: then none of it is kept)."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if name == "Bash":
        command = str(tool_input.get("command") or "")
        return bool(SECRET_COMMANDS.search(command)) or any(
            credential_file(word) for word in _COMMAND_WORDS.split(command) if word)
    if name in _FILE_TOOLS:
        return credential_file(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
    return False


def _parts(entry: dict[str, Any]) -> list[dict[str, Any]]:
    message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
    content = message.get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def note_secret_calls(entry: Any, secret_ids: set[str]) -> None:
    """Add the ids of the line's tool calls whose output is a secret's (a later line carries that output)."""
    if not isinstance(entry, dict):
        return
    for part in _parts(entry):
        if part.get("type") == "tool_use" and secret_source(str(part.get("name") or ""), part.get("input")):
            secret_ids.add(str(part.get("id") or ""))


def _read_credential_file(entry: dict[str, Any]) -> bool:
    """A Read result names its file (``toolUseResult.file.filePath``): decided from the result line alone."""
    result = entry.get("toolUseResult")
    file = result.get("file") if isinstance(result, dict) else None
    return isinstance(file, dict) and credential_file(str(file.get("filePath") or ""))


def redact_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str):
        if key and value and key not in _NOT_SECRET_KEYS and _SENSITIVE_KEY.match(key):
            return REDACTED
        return redact_text(value)
    if isinstance(value, dict):
        return {name: redact_value(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, key=key) for item in value]
    return value


def redact_line(entry: Any, secret_ids: set[str]) -> Any:
    """One transcript line without secrets. ``secret_ids`` carries, from line to line, the tool calls whose output
    is replaced as a whole (rule 4); a credential file's read result is recognised by its own path."""
    if not isinstance(entry, dict):
        return redact_value(entry)
    entry = copy.deepcopy(entry)  # the caller's line stays as it was
    note_secret_calls(entry, secret_ids)
    whole = _read_credential_file(entry)
    replaced = whole
    for part in _parts(entry):
        if part.get("type") == "tool_result" and (whole or str(part.get("tool_use_id") or "") in secret_ids):
            part["content"] = SECRET_OUTPUT
            replaced = True
    if replaced and "toolUseResult" in entry:
        entry["toolUseResult"] = SECRET_OUTPUT
    return redact_value(entry)


def redact_lines(entries: list[Any], secret_ids: set[str] | None = None) -> list[Any]:
    ids = secret_ids if secret_ids is not None else set()
    return [redact_line(entry, ids) for entry in entries]


__all__ = [
    "CREDENTIAL_FILE",
    "REDACTED",
    "SECRET_COMMANDS",
    "SECRET_OUTPUT",
    "credential_file",
    "note_secret_calls",
    "redact_line",
    "redact_lines",
    "redact_text",
    "redact_value",
    "secret_source",
]
