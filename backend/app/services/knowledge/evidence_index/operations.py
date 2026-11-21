"""The closed, versioned registry of Evidence index operations.

Every interaction the product has with the Evidence index is a named entry here: a **read** or a
**write** with a **fixed parameter name set**. A caller passes an operation key and parameter values,
never statement text; the statement behind each key is fixed in ``postgres_statements``. The registry
deliberately contains exactly one delete, by the unique ``evidence_key``: the index mirrors the
ledger's *current* revisions, so the spans of a superseded or tombstoned revision are removed again
(the ledger keeps them as history).

Source ACL facets. Every span write sets the span's ``acl_keys`` marker and every retrieval operation
carries ``principals``, so a restricted span is filtered inside the statement, never after it
(``access/acl_keys.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_OPERATION_KEY = re.compile(r"^[a-z][a-z0-9_]*_v[0-9]+$")
_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class OperationKind(StrEnum):
    """Whether an operation only reads or also writes."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """One named, versioned operation with a fixed parameter set."""

    key: str
    kind: OperationKind
    parameters: frozenset[str]

    def __post_init__(self) -> None:
        if type(self.key) is not str or not _OPERATION_KEY.fullmatch(self.key):
            raise ValueError("operation key must be a versioned lower-case identifier")
        if type(self.kind) is not OperationKind:
            raise TypeError("kind must be an OperationKind")
        if not all(type(name) is str and _PARAMETER_NAME.fullmatch(name) for name in self.parameters):
            raise ValueError("parameter names must be lower-case identifiers")
        object.__setattr__(self, "parameters", frozenset(self.parameters))


_READ = OperationKind.READ
_WRITE = OperationKind.WRITE

# --- projection
UPSERT_EVIDENCE_SCOPED = "upsert_evidence_scoped_v2"
DELETE_EVIDENCE = "delete_evidence_v1"
COUNT_EVIDENCE_BY_KEY = "count_evidence_by_key_v1"
# Marks spans without an ACL marker public, bounded by ``cap`` per call; restricted spans are always
# written with their marker, never without one.
MARK_UNMARKED_EVIDENCE = "mark_unmarked_evidence_v1"

# --- lexical retrieval: one term or a conjunctive pair, optionally scoped by product and version
SEARCH_EVIDENCE_LEXICAL = "search_evidence_lexical_v2"
SEARCH_EVIDENCE_LEXICAL_PAIR = "search_evidence_lexical_pair_v2"
SEARCH_EVIDENCE_LEXICAL_SCOPED = "search_evidence_lexical_scoped_v2"
SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED = "search_evidence_lexical_pair_scoped_v2"
SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION = "search_evidence_lexical_scoped_version_v2"
SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION = "search_evidence_lexical_pair_scoped_version_v2"

# --- vector retrieval in one catalogued embedding space (``space``), optionally scoped
SEARCH_EVIDENCE_VECTOR = "search_evidence_vector_v3"
SEARCH_EVIDENCE_VECTOR_SCOPED = "search_evidence_vector_scoped_v3"
SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION = "search_evidence_vector_scoped_version_v3"


def set_vector_operation(space_key: str) -> str:
    """Store one span's vector in one embedding space."""
    return f"set_vector_{space_key}_v1"


def read_vector_operation(space_key: str) -> str:
    """One span's stored vector, by evidence key (structured-graph similarity)."""
    return f"read_vector_{space_key}_v1"


def _spec(key: str, kind: OperationKind, *parameters: str) -> OperationSpec:
    return OperationSpec(key=key, kind=kind, parameters=frozenset(parameters))


_ONE = ("term",)
_PAIR = ("term_a", "term_b")
_SPECS: list[OperationSpec] = [
    _spec(
        UPSERT_EVIDENCE_SCOPED,
        _WRITE,
        "body_text",
        "revision_id",
        "span_ordinal",
        "products",
        "version",
        "acl_keys",
        "evidence_key",
    ),
    _spec(DELETE_EVIDENCE, _WRITE, "evidence_key"),
    _spec(COUNT_EVIDENCE_BY_KEY, _READ, "evidence_key"),
    _spec(MARK_UNMARKED_EVIDENCE, _WRITE, "acl_keys", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL, _READ, *_ONE, "principals", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL_PAIR, _READ, *_PAIR, "principals", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL_SCOPED, _READ, *_ONE, "products", "principals", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED, _READ, *_PAIR, "products", "principals", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION, _READ, *_ONE, "products", "version", "principals", "cap"),
    _spec(SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION, _READ, *_PAIR, "products", "version", "principals", "cap"),
    _spec(SEARCH_EVIDENCE_VECTOR, _READ, "space", "vector", "principals", "k"),
    _spec(SEARCH_EVIDENCE_VECTOR_SCOPED, _READ, "space", "vector", "products", "principals", "k"),
    _spec(SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION, _READ, "space", "vector", "products", "version", "principals", "k"),
]


def _vector_specs() -> tuple[OperationSpec, ...]:
    from ..embedding.catalog import EMBEDDING_SPACES

    specs: list[OperationSpec] = []
    for space_key in EMBEDDING_SPACES:
        specs.append(_spec(set_vector_operation(space_key), _WRITE, "embedding", "evidence_key"))
        specs.append(_spec(read_vector_operation(space_key), _READ, "evidence_key"))
    return tuple(specs)


_ALL = (*_SPECS, *_vector_specs())
_REGISTRY: dict[str, OperationSpec] = {spec.key: spec for spec in _ALL}

if len(_REGISTRY) != len(_ALL):  # a duplicate key would silently shrink the registry
    raise ValueError("duplicate evidence index operation key")

OPERATIONS = MappingProxyType(_REGISTRY)


def operation(key: object) -> OperationSpec:
    """Resolve a registered operation. An unknown key is a closed-registry error."""
    if type(key) is not str:
        raise KeyError("unknown evidence index operation")
    spec = _REGISTRY.get(key)
    if spec is None:
        raise KeyError("unknown evidence index operation")
    return spec


def operation_keys() -> frozenset[str]:
    """Every registered operation key; the registry is closed to everything else."""
    return frozenset(_REGISTRY)


__all__ = [
    "COUNT_EVIDENCE_BY_KEY",
    "DELETE_EVIDENCE",
    "MARK_UNMARKED_EVIDENCE",
    "OPERATIONS",
    "SEARCH_EVIDENCE_LEXICAL",
    "SEARCH_EVIDENCE_LEXICAL_PAIR",
    "SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED",
    "SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION",
    "SEARCH_EVIDENCE_LEXICAL_SCOPED",
    "SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION",
    "SEARCH_EVIDENCE_VECTOR",
    "SEARCH_EVIDENCE_VECTOR_SCOPED",
    "SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION",
    "UPSERT_EVIDENCE_SCOPED",
    "OperationKind",
    "OperationSpec",
    "operation",
    "operation_keys",
    "read_vector_operation",
    "set_vector_operation",
]
