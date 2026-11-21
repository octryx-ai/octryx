"""Release sync configuration of a Jira connector: explicit data, never guessed from names.

A Jira connector syncs its projects' **versions** (fixVersions) as release notes only when its scope
carries a ``releases`` block. Every value is configuration an author set:

- ``products``: Jira project key -> product key. A project's versions are released knowledge of
  exactly that product; a project without an entry has no release sync. An empty mapping is the
  explicit state ``needs_configuration`` (``release_product_not_configured``), never a product
  derived from the project or version name.
- ``version_name_prefixes``: literal prefixes stripped from a Jira version name before it is read
  as a version (``"Release "`` turns ``Release 2.4.20`` into ``2.4.20``). Only a leading ``v``
  directly before a digit (``v2.4.20``) is read without configuration: it is the common version
  notation, not a guess. A name that is still not a numeric dotted version is skipped with
  ``version_name_unrecognized``.
- ``sections``: ordered release-note sections, each matching issue types and/or labels exactly
  (case-insensitive). An issue lands in the first section it matches; an issue no section matches
  is listed under its own Jira issue type. Without sections, every issue is listed under its type.
- ``blocker_priorities``: the Jira priority names that count as blockers for the live status tool
  (``jira_release_status``). Without it, the status reports no blockers and says so.

Values are refused, never cleaned up. A refusal names the field it belongs to and a fixed code
(``InvalidReleaseConfigError``), so an author sees which row or tag to fix; neither carries a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...ledger.errors import InvalidEvidenceRequestError
from ..scope import normalize_products, normalize_version

RELEASE_SYNC_OFF = "off"
RELEASE_SYNC_ACTIVE = "active"
RELEASE_SYNC_NEEDS_CONFIGURATION = "needs_configuration"
REASON_RELEASE_PRODUCT_NOT_CONFIGURED = "release_product_not_configured"
REASON_VERSION_NAME_UNRECOGNIZED = "version_name_unrecognized"

MAX_PREFIXES = 5
MAX_PREFIX_CHARS = 40
MAX_SECTIONS = 12
MAX_SECTION_TITLE_CHARS = 80
MAX_MATCH_VALUES = 10
MAX_MATCH_VALUE_CHARS = 60
MAX_BLOCKER_PRIORITIES = 5

_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")
# A release version: numeric dotted parts, optionally one pre-release/build suffix (2.4.20-rc1).
_RELEASE_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,5}(?:[-+][0-9A-Za-z.]{1,20})?$")
_ALLOWED_KEYS = frozenset({"products", "version_name_prefixes", "sections", "blocker_priorities"})

# Fixed refusal codes of a ``releases`` block; the field is a path such as ``releases.products[1]``.
CODE_BLOCK_INVALID = "release_block_invalid"
CODE_PROJECT_KEY_INVALID = "release_project_key_invalid"
CODE_PROJECT_NOT_IN_SCOPE = "release_project_not_in_scope"
CODE_PRODUCT_INVALID = "release_product_invalid"
CODE_LIST_INVALID = "release_list_invalid"
CODE_TOO_MANY_VALUES = "release_too_many_values"
CODE_VALUE_INVALID = "release_value_invalid"
CODE_VALUE_TOO_LONG = "release_value_too_long"
CODE_SECTION_INVALID = "release_section_invalid"
CODE_SECTION_TITLE_INVALID = "release_section_title_invalid"
CODE_SECTION_WITHOUT_MATCH = "release_section_without_match"


class InvalidReleaseConfigError(InvalidEvidenceRequestError):
    """A refused ``releases`` value: the field path and a fixed code, never the value itself."""

    def __init__(self, field: str, code: str) -> None:
        super().__init__()
        self.field = field
        self.code = code


@dataclass(frozen=True, slots=True)
class ReleaseSection:
    title: str
    issue_types: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    def matches(self, issue_type: str, labels: tuple[str, ...]) -> bool:
        if issue_type.casefold() in {value.casefold() for value in self.issue_types}:
            return True
        wanted = {value.casefold() for value in self.labels}
        return any(label.casefold() in wanted for label in labels)


@dataclass(frozen=True, slots=True)
class ReleaseConfig:
    products: tuple[tuple[str, str], ...]  # (project key, product key), in configured order
    version_name_prefixes: tuple[str, ...] = ()
    sections: tuple[ReleaseSection, ...] = ()
    blocker_priorities: tuple[str, ...] = ()

    def product_of(self, project_key: str) -> str | None:
        return next((product for key, product in self.products if key == project_key), None)


def _strings(raw: object, *, field: str, limit: int, max_chars: int, strip: bool = True) -> tuple[str, ...]:
    if raw is None:
        return ()
    if type(raw) is not list:
        raise InvalidReleaseConfigError(field, CODE_LIST_INVALID)
    if len(raw) > limit:
        raise InvalidReleaseConfigError(field, CODE_TOO_MANY_VALUES)
    values: list[str] = []
    for index, item in enumerate(raw):
        if type(item) is not str or any(ord(ch) < 32 for ch in item):
            raise InvalidReleaseConfigError(f"{field}[{index}]", CODE_VALUE_INVALID)
        value = item.strip() if strip else item
        if not value.strip():
            raise InvalidReleaseConfigError(f"{field}[{index}]", CODE_VALUE_INVALID)
        if len(value) > max_chars:
            raise InvalidReleaseConfigError(f"{field}[{index}]", CODE_VALUE_TOO_LONG)
        values.append(value)
    return tuple(dict.fromkeys(values))


def _section(raw: object, field: str) -> ReleaseSection:
    if type(raw) is not dict or set(raw) - {"title", "issue_types", "labels"}:
        raise InvalidReleaseConfigError(field, CODE_SECTION_INVALID)
    title = raw.get("title")
    if type(title) is not str or not title.strip() or len(title.strip()) > MAX_SECTION_TITLE_CHARS:
        raise InvalidReleaseConfigError(f"{field}.title", CODE_SECTION_TITLE_INVALID)
    issue_types = _strings(
        raw.get("issue_types"), field=f"{field}.issue_types", limit=MAX_MATCH_VALUES, max_chars=MAX_MATCH_VALUE_CHARS
    )
    labels = _strings(
        raw.get("labels"), field=f"{field}.labels", limit=MAX_MATCH_VALUES, max_chars=MAX_MATCH_VALUE_CHARS
    )
    if not issue_types and not labels:
        raise InvalidReleaseConfigError(field, CODE_SECTION_WITHOUT_MATCH)
    return ReleaseSection(" ".join(title.split()), issue_types, labels)


def validate_release_config(raw: object, *, project_keys: tuple[str, ...]) -> dict[str, object] | None:
    """The stored ``releases`` block of a Jira scope, or ``None`` when release sync is off."""
    if raw is None:
        return None
    if type(raw) is not dict or set(raw) - _ALLOWED_KEYS:
        raise InvalidReleaseConfigError("releases", CODE_BLOCK_INVALID)
    mapping = raw.get("products") or {}
    if type(mapping) is not dict:
        raise InvalidReleaseConfigError("releases.products", CODE_BLOCK_INVALID)
    products: dict[str, str] = {}
    for index, (key, product) in enumerate(mapping.items()):
        field = f"releases.products[{index}]"
        if type(key) is not str or not _PROJECT_KEY.fullmatch(key):
            raise InvalidReleaseConfigError(field, CODE_PROJECT_KEY_INVALID)
        if key not in project_keys:
            raise InvalidReleaseConfigError(field, CODE_PROJECT_NOT_IN_SCOPE)
        try:
            normalized = normalize_products([product]) if type(product) is str else ()
        except InvalidEvidenceRequestError:
            normalized = ()
        if len(normalized) != 1:
            raise InvalidReleaseConfigError(field, CODE_PRODUCT_INVALID)
        products[key] = normalized[0]
    # Prefixes are literal and kept as typed (``"Release "`` ends with its space).
    prefixes = _strings(
        raw.get("version_name_prefixes"),
        field="releases.version_name_prefixes",
        limit=MAX_PREFIXES,
        max_chars=MAX_PREFIX_CHARS,
        strip=False,
    )
    sections_raw = raw.get("sections")
    if sections_raw is not None and type(sections_raw) is not list:
        raise InvalidReleaseConfigError("releases.sections", CODE_LIST_INVALID)
    if sections_raw is not None and len(sections_raw) > MAX_SECTIONS:
        raise InvalidReleaseConfigError("releases.sections", CODE_TOO_MANY_VALUES)
    sections = [_section(item, f"releases.sections[{index}]") for index, item in enumerate(sections_raw or ())]
    blockers = _strings(
        raw.get("blocker_priorities"),
        field="releases.blocker_priorities",
        limit=MAX_BLOCKER_PRIORITIES,
        max_chars=MAX_MATCH_VALUE_CHARS,
    )
    return {
        "products": products,
        "version_name_prefixes": list(prefixes),
        "sections": [
            {"title": s.title, "issue_types": list(s.issue_types), "labels": list(s.labels)} for s in sections
        ],
        "blocker_priorities": list(blockers),
    }


def load_release_config(scope: dict) -> ReleaseConfig | None:
    """The release configuration of a stored Jira scope; ``None`` when off or without any product."""
    raw = scope.get("releases")
    if not isinstance(raw, dict) or not raw.get("products"):
        return None
    return ReleaseConfig(
        products=tuple((str(key), str(product)) for key, product in dict(raw["products"]).items()),
        version_name_prefixes=tuple(raw.get("version_name_prefixes") or ()),
        sections=tuple(
            ReleaseSection(str(item["title"]), tuple(item.get("issue_types") or ()), tuple(item.get("labels") or ()))
            for item in raw.get("sections") or ()
        ),
        blocker_priorities=tuple(raw.get("blocker_priorities") or ()),
    )


def release_sync_state(scope: dict) -> dict[str, object]:
    """The explicit release sync state an author sees on the connector."""
    if not isinstance(scope.get("releases"), dict):
        return {"state": RELEASE_SYNC_OFF}
    config = load_release_config(scope)
    if config is None:
        return {"state": RELEASE_SYNC_NEEDS_CONFIGURATION, "reason": REASON_RELEASE_PRODUCT_NOT_CONFIGURED}
    return {"state": RELEASE_SYNC_ACTIVE, "products": dict(config.products)}


def release_version(name: object, prefixes: tuple[str, ...]) -> str | None:
    """The normalized version a Jira version name stands for, or ``None`` when it is not one."""
    if type(name) is not str:
        return None
    candidate = name.strip()
    for prefix in prefixes:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :].strip()
            break
    if candidate[:1] in ("v", "V") and candidate[1:2].isdigit():
        candidate = candidate[1:]
    if not _RELEASE_VERSION.fullmatch(candidate):
        return None
    try:
        return normalize_version(candidate)
    except InvalidEvidenceRequestError:
        return None


__all__ = [
    "InvalidReleaseConfigError",
    "REASON_RELEASE_PRODUCT_NOT_CONFIGURED",
    "REASON_VERSION_NAME_UNRECOGNIZED",
    "RELEASE_SYNC_ACTIVE",
    "RELEASE_SYNC_NEEDS_CONFIGURATION",
    "RELEASE_SYNC_OFF",
    "ReleaseConfig",
    "ReleaseSection",
    "load_release_config",
    "release_sync_state",
    "release_version",
    "validate_release_config",
]
