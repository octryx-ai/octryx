"""The configured ServiceNow scope, and the encoded queries that can only narrow it.

A ServiceNow connector reads two kinds of targets:

- **knowledge base articles** (``kb_knowledge``) of the configured knowledge bases (``sys_id``s of
  ``kb_knowledge_base``), published and active only;
- **records** of the configured tables (``incident``, ``problem``, ``change_request``).

Each kind may carry an author-supplied **encoded query** (``sysparm_query``) that narrows it. The
connector always places the scope first and the filter after it:
``<scope>^<filter>^ORDERBYsys_created_on^ORDERBYsys_id``. The filter is validated so it cannot
widen the scope. In the encoded-query grammar, ``^OR`` binds to the condition just before it and
``^NQ`` starts a new ``OR``-ed query. So every segment must start with a field name (ServiceNow
field names are lower case: ``u_``/``x_`` custom and dot-walked names included), or with ``OR``
followed by a field name, and the first segment may not be an ``OR``. That excludes:

- ``NQ``, which would widen the scope;
- ``EQ``, ``ORDERBY``/``GROUPBY``, which the connector owns;
- ``RLQUERY``/``SUBQUERY``, whose nested grammar is not verified here;
- ``javascript:`` values, which the instance would evaluate.

Values are refused, never cleaned up.
"""

from __future__ import annotations

import re

from ...ledger.errors import InvalidEvidenceRequestError

KNOWLEDGE_TABLE = "kb_knowledge"
RECORD_TABLES = frozenset({"incident", "problem", "change_request"})
MAX_KNOWLEDGE_BASES = 20
MAX_QUERY_CHARS = 500
ORDER_CLAUSE = "ORDERBYsys_created_on^ORDERBYsys_id"

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_CONDITION = re.compile(r"^[a-z][a-z0-9_.]*")
_OR_CONDITION = re.compile(r"^OR[a-z][a-z0-9_.]*")


def validate_encoded_query(raw: object) -> str | None:
    """An encoded query that can only narrow what it is ANDed to, or ``None``; refuses otherwise."""
    if raw is None or (type(raw) is str and not raw.strip()):
        return None
    if type(raw) is not str or len(raw) > MAX_QUERY_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise InvalidEvidenceRequestError()
    query = raw.strip()
    if "javascript:" in query.lower():
        raise InvalidEvidenceRequestError()
    for index, segment in enumerate(query.split("^")):
        if _CONDITION.match(segment):
            continue
        if index > 0 and _OR_CONDITION.match(segment):
            continue
        raise InvalidEvidenceRequestError()
    return query


def _knowledge_bases(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list | tuple) or len(raw) > MAX_KNOWLEDGE_BASES:
        raise InvalidEvidenceRequestError()
    ids = []
    for item in raw:
        if type(item) is not str or not _SYS_ID.fullmatch(item.strip().lower()):
            raise InvalidEvidenceRequestError()
        ids.append(item.strip().lower())
    return list(dict.fromkeys(ids))


def _tables(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list | tuple) or len(raw) > len(RECORD_TABLES):
        raise InvalidEvidenceRequestError()
    tables = []
    for item in raw:
        if type(item) is not str or item.strip().lower() not in RECORD_TABLES:
            raise InvalidEvidenceRequestError()
        tables.append(item.strip().lower())
    return sorted(set(tables))


def validate_servicenow_scope(
    *, knowledge_bases: object, tables: object, article_query: object, record_query: object
) -> dict[str, object]:
    bases, record_tables = _knowledge_bases(knowledge_bases), _tables(tables)
    if not bases and not record_tables:
        raise InvalidEvidenceRequestError()
    articles, records = validate_encoded_query(article_query), validate_encoded_query(record_query)
    if (articles and not bases) or (records and not record_tables):
        raise InvalidEvidenceRequestError()
    return {"knowledge_bases": bases, "tables": record_tables, "article_query": articles, "record_query": records}


def scope_tables(scope: dict) -> tuple[str, ...]:
    """The ServiceNow tables a scope reads, checked against the tool's ``servicenow_allowed_tables``."""
    tables = [KNOWLEDGE_TABLE] if scope.get("knowledge_bases") else []
    return (*tables, *(str(table) for table in scope.get("tables") or ()))


def _query(scope_clause: str, author_filter: str | None) -> str:
    parts = [scope_clause, author_filter, ORDER_CLAUSE] if author_filter else [scope_clause, ORDER_CLAUSE]
    return "^".join(parts)


def article_query(knowledge_bases: tuple[str, ...], author_filter: str | None) -> str:
    bases = ",".join(knowledge_bases)
    return _query(f"kb_knowledge_baseIN{bases}^workflow_state=published^active=true", author_filter)


def record_query(author_filter: str | None) -> str:
    # The table itself is the scope of a record target; the filter can only narrow it.
    return _query("sys_idISNOTEMPTY", author_filter)


__all__ = [
    "KNOWLEDGE_TABLE",
    "RECORD_TABLES",
    "article_query",
    "record_query",
    "scope_tables",
    "validate_encoded_query",
    "validate_servicenow_scope",
]
