"""Placeholder contract shared by every deployment secret containment check.

One contract, one place. A tracked or packaged file may describe *which* secret
material a deployment needs (key names are schema), but it must never carry the
material itself, and it must not carry a value that is deployable as-is.

Value classification:

``empty``
    No material shipped. Inert *unless* a consumer substitutes a weak default for
    it (see ``values_scan.weak_default_secret_keys``), which turns the empty value
    into a silently deployable credential.
``placeholder``
    A deliberately invalid marker (``REPLACE_WITH_...``, ``<hint>``, ``${ENV_REF}``).
    An unedited copy fails at the consuming API instead of deploying something.
``reference``
    A Helm/template expression (``{{ ... }}``). The material lives elsewhere.
``weak``
    A ``changeme``-family or otherwise well-known value. Not safe: it deploys a
    credential that every reader of this repository already knows.
``material``
    Anything else. Treated as real secret material.

Nothing in this package ever prints, decodes, measures, or otherwise reads back a
value. A finding carries the file, the line, the key name, and a reason code only.
Do not extend it to emit value text, lengths, or character classes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Reason codes. Stable strings referenced by CI output and tests.
REASON_TRACKED_LOCAL_FILE = "local-only-values-file-is-tracked"
REASON_NOT_PLACEHOLDER = "secret-value-not-placeholder"
REASON_BLOCK_NOT_PLACEHOLDER = "secret-block-value-not-placeholder"
REASON_BLOCK_SCALAR = "secret-key-uses-block-scalar"
REASON_BLOCK_UNREADABLE = "secret-block-value-not-readable"
REASON_DOCUMENT_UNREADABLE = "secret-document-not-readable"
REASON_WEAK_VALUE = "secret-value-is-weak-known-default"
REASON_EMPTY_WEAK_DEFAULT = "secret-key-empty-enables-weak-chart-default"
REASON_MISSING_WEAK_DEFAULT = "secret-key-missing-enables-weak-chart-default"
REASON_MISSING_HELMIGNORE = "chart-missing-helmignore"
REASON_HELMIGNORE_GAP = "chart-helmignore-missing-local-values-pattern"
REASON_SECRET_MATERIAL_FILE = "unexcluded-secret-material-file"
REASON_UNEXPECTED_CHART_FILE = "unexpected-chart-file-not-helmignored"

EMPTY = "empty"
PLACEHOLDER = "placeholder"
REFERENCE = "reference"
WEAK = "weak"
MATERIAL = "material"

# Explicit, deliberately unusable placeholder forms.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^REPLACE_WITH_[A-Z0-9_]+$"),
    re.compile(r"^<[^<>]+>$"),
    re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$"),
)

# Template expressions: the material is resolved by the renderer, not stored here.
_REFERENCE_PATTERN = re.compile(r"^\{\{.*\}\}$")

# Known-weak values. These are deployable, so they are never an acceptable
# placeholder for secret material, no matter how obvious they look.
_WEAK_SUBSTRINGS = ("changeme", "change-me", "change_me", "changeit")
_WEAK_EXACT = frozenset({"admin", "password", "passwort", "secret", "test", "postgres", "root"})

# YAML block scalar indicators. A secret key must never open a block.
BLOCK_SCALAR_INDICATORS = ("|", ">", "|-", ">-", "|+", ">+")

# Secret-material key names, normalised (lowercase, "_" and "-" removed). Reference
# keys such as secretName or tokenKey are absent on purpose: they name a secret,
# they do not carry one.
SECRET_MATERIAL_KEYS = frozenset(
    {
        "admindefaultpassword",
        "adminpassword",
        "databaseurl",
        "encryptionkey",
        "jwtsecret",
        "openrouterapikey",
        "postgrespassword",
    }
)

# Suffix rules for env-style files, where key names follow the environment
# variable convention rather than the chart schema. Each entry names material, not a
# reference to material. The list stays deliberately short: every suffix here is backed
# by a name that actually occurs in this repository, and broad families are excluded
# because repository evidence shows they also name non-secrets (``_KEY`` matches
# ``AWS_ACCESS_KEY_ID``-style identifiers, ``_PASS`` matches test-result flags such as
# ``COMPAT_PASS``). A Secret manifest needs none of this: there every entry is material
# by contract.
_SECRET_ENV_SUFFIXES = (
    "_PASSWORD",
    "_PASSWD",
    "_SECRET",
    "_SECRET_KEY",
    "_SECRET_ACCESS_KEY",
    "_SIGNING_KEY",
    "_TOKEN",
    "_API_KEY",
    "_APIKEY",
    "_PRIVATE_KEY",
    "_CREDENTIALS",
    "_DSN",
)

# Configuration fields that live inside a chart ``secrets`` block without carrying
# secret material themselves.
NON_SECRET_KEYS_IN_SECRET_BLOCK = frozenset({"generatesecrets"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    key: str
    reason: str

    def render(self) -> str:
        location = self.path if self.line == 0 else f"{self.path}:{self.line}"
        key = f" key={self.key}" if self.key else ""
        return f"{location}:{key} reason={self.reason}"


def normalise_key(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def classify_value(value: str) -> str:
    """Classify a scalar against the placeholder contract. Never returns the value."""
    if value == "":
        return EMPTY
    if _REFERENCE_PATTERN.match(value):
        return REFERENCE
    if any(pattern.match(value) for pattern in _PLACEHOLDER_PATTERNS):
        return PLACEHOLDER
    lowered = value.lower()
    if lowered in _WEAK_EXACT or any(token in lowered for token in _WEAK_SUBSTRINGS):
        return WEAK
    return MATERIAL


def is_secret_material_key(key: str) -> bool:
    """True for chart-schema secret keys (``jwtSecret``, ``postgresPassword``, ...)."""
    return normalise_key(key) in SECRET_MATERIAL_KEYS


def is_secret_env_key(key: str) -> bool:
    """True for env-style secret keys, by name list or by conventional suffix."""
    if is_secret_material_key(key):
        return True
    upper = key.strip().upper()
    return any(upper.endswith(suffix) for suffix in _SECRET_ENV_SUFFIXES)


def strip_scalar(rest: str) -> str:
    """Return the scalar part of a ``key: value`` / ``KEY=value`` tail, comments removed."""
    value = rest.strip()
    if value.startswith(('"', "'")):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()
