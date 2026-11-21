"""The PostgreSQL statement behind each Evidence registry operation.

Every statement is fixed text and scoped by ``:project_id``, which the client derives from the
validated :class:`WorkspaceId` — no caller supplies it, so no operation can reach another
Workspace's rows. Query text only ever arrives as a bound value: ``plainto_tsquery`` parses it as
plain words with the same ``simple`` parser that built the indexed ``tsvector``, so a term matches
whole tokens, and operators in it are just characters.

- A lexical fetch has a server-owned ``LIMIT :cap`` and orders the matches by ``ts_rank_cd``
  before cutting, so the candidate window is the best-matching spans for the term.
- The vector search filters by ACL, product and version *inside* the scan and returns the exact
  nearest ``:k`` that pass, so a restricted or out-of-scope span never costs recall.
"""

from __future__ import annotations

from types import MappingProxyType

from ..embedding.catalog import EMBEDDING_SPACES
from . import operations as ops

INDEX_TABLE = "knowledge_evidence_index"
VECTOR_TABLE = "knowledge_evidence_vectors"

_ACL = " AND acl_keys && CAST(:principals AS text[])"
_PRODUCTS = " AND products && CAST(:products AS text[])"
_VERSION = " AND version = :version"
_ONE = (
    f"SELECT evidence_key, body_text FROM {INDEX_TABLE}, plainto_tsquery('simple', :term) AS q "
    "WHERE project_id = :project_id AND body_tsv @@ q"
)
_TWO = (
    f"SELECT evidence_key, body_text FROM {INDEX_TABLE}, plainto_tsquery('simple', :term_a) AS qa, "
    "plainto_tsquery('simple', :term_b) AS qb WHERE project_id = :project_id AND body_tsv @@ qa AND body_tsv @@ qb"
)
_ONE_ORDER = " ORDER BY ts_rank_cd(body_tsv, q) DESC, evidence_key LIMIT :cap"
_TWO_ORDER = " ORDER BY ts_rank_cd(body_tsv, qa && qb) DESC, evidence_key LIMIT :cap"

# Lexical reads: (statement) per registry key. The ACL predicate is in every one of them.
LEXICAL = MappingProxyType(
    {
        ops.SEARCH_EVIDENCE_LEXICAL: _ONE + _ACL + _ONE_ORDER,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR: _TWO + _ACL + _TWO_ORDER,
        ops.SEARCH_EVIDENCE_LEXICAL_SCOPED: _ONE + _PRODUCTS + _ACL + _ONE_ORDER,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED: _TWO + _PRODUCTS + _ACL + _TWO_ORDER,
        ops.SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION: _ONE + _PRODUCTS + _VERSION + _ACL + _ONE_ORDER,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION: _TWO + _PRODUCTS + _VERSION + _ACL + _TWO_ORDER,
    }
)

# Vector reads: the scope predicates per registry key; the statement is built per space (dimension).
_I_ACL = " AND i.acl_keys && CAST(:principals AS text[])"
_I_PRODUCTS = " AND i.products && CAST(:products AS text[])"
_I_VERSION = " AND i.version = :version"
VECTOR_SCOPES = MappingProxyType(
    {
        ops.SEARCH_EVIDENCE_VECTOR: _I_ACL,
        ops.SEARCH_EVIDENCE_VECTOR_SCOPED: _I_PRODUCTS + _I_ACL,
        ops.SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION: _I_PRODUCTS + _I_VERSION + _I_ACL,
    }
)


def vector_search(dimensions: int, scope: str) -> str:
    """Exact cosine nearest neighbours of one space inside one Workspace, filtered in the scan."""
    typed = f"vector({int(dimensions)})"
    return (
        f"SELECT i.evidence_key AS evidence_key, i.body_text AS body_text, "
        f"(CAST(v.embedding AS {typed}) <=> CAST(CAST(:vector AS text) AS {typed})) AS distance "
        f"FROM {VECTOR_TABLE} AS v JOIN {INDEX_TABLE} AS i "
        "ON i.project_id = v.project_id AND i.evidence_key = v.evidence_key "
        "WHERE v.project_id = :project_id AND v.space_key = :space_key"
        + scope
        + " ORDER BY distance, i.evidence_key LIMIT :k"
    )


UPSERT_EVIDENCE = (
    f"INSERT INTO {INDEX_TABLE} (project_id, evidence_key, body_text, revision_id, span_ordinal, products, version, "
    "acl_keys, updated_at) VALUES (:project_id, :evidence_key, :body_text, :revision_id, :span_ordinal, "
    "CAST(:products AS text[]), :version, CAST(:acl_keys AS text[]), now() AT TIME ZONE 'utc') "
    "ON CONFLICT (project_id, evidence_key) DO UPDATE SET body_text = EXCLUDED.body_text, "
    "revision_id = EXCLUDED.revision_id, span_ordinal = EXCLUDED.span_ordinal, products = EXCLUDED.products, "
    "version = EXCLUDED.version, acl_keys = EXCLUDED.acl_keys, updated_at = EXCLUDED.updated_at"
)
DELETE_EVIDENCE = f"DELETE FROM {INDEX_TABLE} WHERE project_id = :project_id AND evidence_key = :evidence_key"
COUNT_EVIDENCE = (
    f"SELECT count(*) AS total FROM {INDEX_TABLE} WHERE project_id = :project_id AND evidence_key = :evidence_key"
)
MARK_UNMARKED = (
    f"UPDATE {INDEX_TABLE} SET acl_keys = CAST(:acl_keys AS text[]) WHERE project_id = :project_id "
    f"AND evidence_key IN (SELECT evidence_key FROM {INDEX_TABLE} WHERE project_id = :project_id "
    "AND acl_keys IS NULL ORDER BY evidence_key LIMIT :cap)"
)
# No vector-only ghost rows: a vector is only written for a span the projection already holds.
SET_VECTOR = (
    f"INSERT INTO {VECTOR_TABLE} (project_id, space_key, evidence_key, embedding) "
    "SELECT project_id, :space_key, evidence_key, CAST(CAST(:embedding AS text) AS vector) "
    f"FROM {INDEX_TABLE} WHERE project_id = :project_id AND evidence_key = :evidence_key "
    "ON CONFLICT (project_id, space_key, evidence_key) DO UPDATE SET embedding = EXCLUDED.embedding"
)
READ_VECTOR = (
    f"SELECT CAST(embedding AS text) AS vector FROM {VECTOR_TABLE} "
    "WHERE project_id = :project_id AND space_key = :space_key AND evidence_key = :evidence_key"
)
VECTOR_TABLE_PRESENT = f"SELECT to_regclass('{VECTOR_TABLE}') IS NOT NULL AS present"

SET_VECTOR_KEYS = MappingProxyType({ops.set_vector_operation(key): key for key in EMBEDDING_SPACES})
READ_VECTOR_KEYS = MappingProxyType({ops.read_vector_operation(key): key for key in EMBEDDING_SPACES})
VECTOR_KEYS = frozenset(VECTOR_SCOPES) | frozenset(SET_VECTOR_KEYS) | frozenset(READ_VECTOR_KEYS)
