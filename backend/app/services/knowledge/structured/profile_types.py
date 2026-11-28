"""The structured profile's value types and the constants its rows and checks share."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .profile_patterns import ProfilePattern

LAYER_MANUAL = "manual"
LAYER_CONFIGURATION = "configuration"
LAYER_OPERATIONS = "operations"
LAYERS = (LAYER_MANUAL, LAYER_CONFIGURATION, LAYER_OPERATIONS)
RELATIONS = frozenset({"requires", "supports"})
# The ``profile`` column of every structured row.
MAX_PROFILE_ID_CHARS = 40
FILE_FORMATS = frozenset({"ini", "properties", "yaml"})


class StructuredProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigFileRule:
    glob: str
    format: str
    manual_documented: bool


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    relation: str

    @property
    def folded(self) -> str:
        return fold(self.name)


@dataclass(frozen=True, slots=True)
class ReferencePattern:
    kind: str
    pattern: ProfilePattern


@dataclass(frozen=True)
class StructuredProfile:
    key: str
    version: int
    title: str
    manual_media_types: tuple[str, ...]
    config_connector_kinds: tuple[str, ...]
    config_files: tuple[ConfigFileRule, ...]
    ops_connector_kinds: tuple[str, ...]
    ignored_headings: tuple[ProfilePattern, ...]
    filler_lines: tuple[ProfilePattern, ...]
    parameter_name_headers: frozenset[str]
    default_headers: frozenset[str]
    description_headers: frozenset[str]
    allowed_headers: frozenset[str]
    allowed_value_patterns: tuple[ProfilePattern, ...]
    units: tuple[tuple[str, str], ...]
    reference_patterns: tuple[ReferencePattern, ...]
    term_suffixes: tuple[str, ...]
    max_terms_per_section: int
    components: tuple[Component, ...]
    similarity_top_k: int
    similarity_min_score: float
    similarity_max_sections: int
    registry_sections: tuple[str, ...]
    # File format -> the line prefixes that make a line a comment (``properties``: ``#``, ``!``, ``;``).
    comment_prefixes: dict[str, tuple[str, ...]]
    continuation_prefixes: tuple[str, ...]
    # File-name patterns with the named groups ``base`` and ``variant`` (``app.ini-test``).
    variant_patterns: tuple[ProfilePattern, ...]
    # A value placeholder with the named group ``name`` (``${Dec_ThreadCount}``).
    placeholder_pattern: ProfilePattern
    # File-name globs of key=value files that define the placeholders of their component.
    placeholder_sources: tuple[str, ...]
    # Documented defaults that are no value (``<Format>``, ``{BaseDir}+"/in"``, prose): never compared.
    non_comparable_defaults: tuple[ProfilePattern, ...]
    # A difference between two placeholder definitions is reported once, on the settings resolving from them.
    fold_resolved_definitions: bool
    ticket_patterns: tuple[tuple[str, ProfilePattern], ...]
    caused_by_patterns: tuple[ProfilePattern, ...]
    max_mentions_per_record: int
    inventory_namespace_pattern: ProfilePattern
    inventory_cluster_pattern: ProfilePattern
    # Set for a Workspace's own profile document: the revision it was saved as.
    workspace_revision: int | None = None

    @property
    def profile_id(self) -> str:
        base = f"{self.key}-v{self.version}"
        return base if self.workspace_revision is None else f"{base}-w{self.workspace_revision}"


def fold(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


__all__ = [
    "FILE_FORMATS",
    "LAYERS",
    "LAYER_CONFIGURATION",
    "LAYER_MANUAL",
    "LAYER_OPERATIONS",
    "MAX_PROFILE_ID_CHARS",
    "RELATIONS",
    "Component",
    "ConfigFileRule",
    "ReferencePattern",
    "StructuredProfile",
    "StructuredProfileError",
    "fold",
]
