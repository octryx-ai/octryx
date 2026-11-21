"""The structured-graph extraction profile as validated data (``profiles/structured-v4.json``).

The profile is the only place the rule-based extractors take vocabulary and patterns from: which
revisions each layer reads, which configuration files are parsed and in which format, the heading
and table-header vocabulary of manuals, the compatibility components and whether a product
``requires`` or ``supports`` them, the comment prefixes per file format, the INI continuation
prefixes, the variant file names (``app.ini-test`` is a variant of ``app.ini``), the
placeholder syntax (``${Name}``) and the files that define placeholders, the documented defaults
that are no value and are never compared (``<Format>``), whether a difference between two
placeholder definitions folds into the settings that resolve from them, the reference, ticket and
inventory patterns, and the similarity bounds. Ticket node types are the ``ticket_patterns``
keys; a ServiceNow record is typed by the pattern its number matches.
Changing any of it needs a new ``version``: the profile id ``structured-v<version>`` is recorded on
every node, edge and extraction row, and rows of another profile are re-extracted on the next build.

Loading is strict: exactly the known fields, every pattern compiles and is safe to run
(``profile_patterns.check_pattern``: bounded length, no ambiguous nested repeat, compiled on the
linear-time RE2 engine, every text capped), and the file
fails when the catalog is read, never half-way through a build.

The file is the **instance default**. A Workspace may store its own document of the same schema
(``workspace_profile.py``); :func:`parse_profile` validates both the same way. A Workspace profile's
id carries its revision (``structured-v4-w3``), so its graph is never mixed with the default's.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from .profile_fields import (
    _bounded,
    _comment_prefixes,
    _components,
    _config_files,
    _fields,
    _flag,
    _grouped,
    _line_prefixes,
    _patterns,
    _references,
    _strings,
    _variant_patterns,
)
from .profile_types import (
    LAYER_CONFIGURATION,
    LAYER_MANUAL,
    LAYER_OPERATIONS,
    LAYERS,
    MAX_PROFILE_ID_CHARS,
    StructuredProfile,
    StructuredProfileError,
    fold,
)

PROFILE_PATH = Path(__file__).parent / "profiles" / "structured-v4.json"

_TOP = frozenset({"key", "version", "title", "layers", "manual", "configuration", "operations"})
_LAYERS = frozenset(LAYERS)
_MANUAL = frozenset(
    {
        "ignored_headings", "filler_lines", "parameter_name_headers", "default_headers", "description_headers",
        "allowed_headers", "allowed_value_patterns", "units", "reference_patterns", "term_suffixes",
        "max_terms_per_section", "components", "similarity",
    }
)
_CONFIGURATION = frozenset(
    {
        "registry_sections", "comment_prefixes", "continuation_prefixes", "variant_patterns", "placeholder_pattern",
        "placeholder_sources", "non_comparable_defaults", "fold_resolved_definitions",
    }
)
_OPERATIONS = frozenset(
    {
        "ticket_patterns", "caused_by_patterns", "max_mentions_per_record", "inventory_namespace_pattern",
        "inventory_cluster_pattern",
    }
)


def load_profile(path: Path) -> StructuredProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StructuredProfileError("structured profile: not a readable JSON document") from None
    return parse_profile(raw)


def _document_parts(raw: object) -> dict[str, Any]:
    """The checked top-level sections and the few values validated before the profile is built."""
    top = _fields(raw, _TOP, "the profile")
    if not isinstance(top["key"], str) or not re.fullmatch(r"[a-z][a-z-]{1,30}", top["key"]):
        raise StructuredProfileError("structured profile: key must be lower-case kebab-case")
    if not isinstance(top["title"], str) or not top["title"].strip():
        raise StructuredProfileError("structured profile: title must be a non-empty string")
    layers = _fields(top["layers"], _LAYERS, "layers")
    manual_layer = _fields(layers[LAYER_MANUAL], frozenset({"media_types"}), "the manual layer")
    config_layer = _fields(layers[LAYER_CONFIGURATION], frozenset({"connector_kinds", "files"}), "the config layer")
    ops_layer = _fields(
        layers[LAYER_OPERATIONS], frozenset({"connector_kinds"}), "the operations layer"
    )
    manual = _fields(top["manual"], _MANUAL, "manual")
    configuration = _fields(top["configuration"], _CONFIGURATION, "configuration")
    operations = _fields(top["operations"], _OPERATIONS, "operations")
    similarity = _fields(manual["similarity"], frozenset({"top_k", "min_score", "max_sections"}), "similarity")
    score = similarity["min_score"]
    if not isinstance(score, float) or not 0.5 <= score < 1.0:
        raise StructuredProfileError("structured profile: similarity min_score must be in [0.5, 1)")
    units = manual["units"]
    if not isinstance(units, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in units.items()):
        raise StructuredProfileError("structured profile: units must map words to unit symbols")
    tickets = operations["ticket_patterns"]
    if not isinstance(tickets, dict) or not tickets:
        raise StructuredProfileError("structured profile: ticket_patterns must map node types to patterns")
    if not all(re.fullmatch(r"[A-Z][A-Za-z]{1,39}", name) for name in tickets):
        raise StructuredProfileError("structured profile: a ticket node type must be a CamelCase word")
    return {
        "top": top, "manual_layer": manual_layer, "config_layer": config_layer, "ops_layer": ops_layer,
        "manual": manual, "configuration": configuration, "operations": operations, "similarity": similarity,
        "score": score, "units": units, "tickets": tickets,
    }


# The field builders below run in the order of the profile's fields, so a document with several
# faults is refused for the same first fault as when they were one constructor call.
def _layer_fields(parts: dict[str, Any]) -> dict[str, Any]:
    manual_layer, config_layer, ops_layer = parts["manual_layer"], parts["config_layer"], parts["ops_layer"]
    return {
        "manual_media_types": _strings(manual_layer["media_types"], "manual media types"),
        "config_connector_kinds": _strings(config_layer["connector_kinds"], "config connector kinds"),
        "config_files": _config_files(config_layer["files"]),
        "ops_connector_kinds": _strings(ops_layer["connector_kinds"], "operations connector kinds"),
    }


def _manual_fields(parts: dict[str, Any]) -> dict[str, Any]:
    manual, similarity = parts["manual"], parts["similarity"]
    return {
        "ignored_headings": _patterns(manual["ignored_headings"], "ignored_headings"),
        "filler_lines": _patterns(manual["filler_lines"], "filler_lines"),
        "parameter_name_headers": frozenset(fold(item) for item in _strings(manual["parameter_name_headers"], "names")),
        "default_headers": frozenset(fold(item) for item in _strings(manual["default_headers"], "defaults")),
        "description_headers": frozenset(fold(item) for item in _strings(manual["description_headers"], "descr")),
        "allowed_headers": frozenset(fold(item) for item in _strings(manual["allowed_headers"], "allowed")),
        "allowed_value_patterns": _patterns(manual["allowed_value_patterns"], "allowed_value_patterns"),
        "units": tuple(sorted(parts["units"].items())),
        "reference_patterns": _references(manual["reference_patterns"]),
        "term_suffixes": _strings(manual["term_suffixes"], "term_suffixes"),
        "max_terms_per_section": _bounded(manual["max_terms_per_section"], 1, 500, "max_terms_per_section"),
        "components": _components(manual["components"]),
        "similarity_top_k": _bounded(similarity["top_k"], 1, 10, "similarity top_k"),
        "similarity_min_score": parts["score"],
        "similarity_max_sections": _bounded(similarity["max_sections"], 1, 20000, "similarity max_sections"),
    }


def _configuration_fields(parts: dict[str, Any]) -> dict[str, Any]:
    configuration = parts["configuration"]
    return {
        "registry_sections": _strings(configuration["registry_sections"], "registry_sections"),
        "comment_prefixes": _comment_prefixes(configuration["comment_prefixes"]),
        "continuation_prefixes": _line_prefixes(configuration["continuation_prefixes"], "continuation_prefixes"),
        "variant_patterns": _variant_patterns(configuration["variant_patterns"]),
        "placeholder_pattern": _grouped(configuration["placeholder_pattern"], "name", "placeholder_pattern"),
        "placeholder_sources": _strings(configuration["placeholder_sources"], "placeholder_sources"),
        "non_comparable_defaults": _patterns(configuration["non_comparable_defaults"], "non_comparable_defaults"),
        "fold_resolved_definitions": _flag(configuration["fold_resolved_definitions"], "fold_resolved_definitions"),
    }


def _operations_fields(parts: dict[str, Any]) -> dict[str, Any]:
    operations = parts["operations"]
    return {
        "ticket_patterns": tuple(
            (name, _patterns([pattern], "a ticket pattern")[0]) for name, pattern in sorted(parts["tickets"].items())
        ),
        "caused_by_patterns": _patterns(operations["caused_by_patterns"], "caused_by_patterns"),
        "max_mentions_per_record": _bounded(
            operations["max_mentions_per_record"], 1, 1000, "max_mentions_per_record"
        ),
        "inventory_namespace_pattern": _grouped(
            operations["inventory_namespace_pattern"], "namespace", "inventory_namespace_pattern"
        ),
        "inventory_cluster_pattern": _grouped(
            operations["inventory_cluster_pattern"], "cluster", "inventory_cluster_pattern"
        ),
    }


def parse_profile(raw: object, *, workspace_revision: int | None = None) -> StructuredProfile:
    """Validate a profile document (the file's or a Workspace's) into the profile the builds use."""
    if workspace_revision is not None and (type(workspace_revision) is not int or workspace_revision < 1):
        raise StructuredProfileError("structured profile: a workspace revision is a positive integer")
    parts = _document_parts(raw)
    top = parts["top"]
    profile = StructuredProfile(
        key=top["key"],
        version=_bounded(top["version"], 1, 999, "version"),
        title=str(top["title"]),
        **_layer_fields(parts),
        **_manual_fields(parts),
        **_configuration_fields(parts),
        **_operations_fields(parts),
        workspace_revision=workspace_revision,
    )
    if len(profile.profile_id) > MAX_PROFILE_ID_CHARS:
        raise StructuredProfileError("structured profile: key and version make a profile id that is too long")
    return profile


def default_profile_document() -> dict[str, Any]:
    """The instance default as a document (a fresh copy), the starting point of a Workspace's own."""
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


@cache
def structured_profile() -> StructuredProfile:
    """The current structured profile (``profiles/structured-v4.json``)."""
    return load_profile(PROFILE_PATH)


__all__ = [
    "default_profile_document",
    "load_profile",
    "parse_profile",
    "structured_profile",
]
