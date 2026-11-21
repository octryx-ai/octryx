"""The Table API side of the ServiceNow record limit (``servicenow_record_limit``).

A Table API query gets the limit's condition server-side: ``<ref>IN<sys_ids>`` and, per name,
``<ref>.nameSTARTSWITH<name>``. That condition is deliberately a superset; every record is also
checked client-side (``servicenow_record_limit.record_in_limit``), exactly.
"""

from __future__ import annotations

import re

from .servicenow_record_limit import _SYS_ID, MODE_ANY, NOTHING, LimitField, RecordLimit, ValueLimit

_ORDER = re.compile(r"^ORDERBY(DESC)?[a-z][a-z0-9_.]*$")


def _clause_parts(spec: LimitField, values: ValueLimit) -> list[str]:
    parts = [f"{spec.reference}IN{','.join(sorted(values.sys_ids))}"] if values.sys_ids else []
    names = sorted(entry for entry in values.entries if not _SYS_ID.match(entry))
    parts.extend(f"{spec.walked}STARTSWITH{name}" for name in names)
    return parts


def encoded_clause(limit: RecordLimit) -> str:
    """The Table API condition for ``limit`` (a superset of the exact match), ANDed to the rest of the query.

    In the encoded-query grammar ``^OR`` binds to the condition before it and ``^`` ANDs, so ``all`` is one
    OR-group per list joined by ``^`` and ``any`` is a single OR-group over every list."""
    groups = [_clause_parts(spec, values) for spec, values in limit.lists()]
    if limit is NOTHING or not groups:
        return "sys_idISEMPTY^sys_idISNOTEMPTY"  # the fail-closed limit: a condition no record satisfies
    if limit.mode == MODE_ANY:
        return "^OR".join(part for parts in groups for part in parts)
    return "^".join("^OR".join(parts) for parts in groups)


def with_clause(query: str | None, limit: RecordLimit | None) -> str | None:
    """``query`` ANDed with the limit's condition; ``query`` unchanged without a limit."""
    if limit is None:
        return query
    return "^".join(part for part in (encoded_clause(limit), query) if part)


def widens(query: str | None) -> bool:
    """Whether an encoded query could escape a condition it is ANDed after: anything but plain narrowing
    conditions (``validate_encoded_query``'s segment rules: no leading ``OR``, no ``^NQ``/``EQ``/``RLQUERY``,
    no ``javascript:``), optionally followed by ``ORDERBY``/``ORDERBYDESC`` segments, which only sort."""
    from .knowledge.ledger.errors import InvalidEvidenceRequestError
    from .knowledge.sources.sync.servicenow_scope import validate_encoded_query

    segments = str(query or "").strip().split("^")
    while segments and _ORDER.match(segments[-1]):
        segments.pop()
    try:
        validate_encoded_query("^".join(segments))
    except InvalidEvidenceRequestError:
        return True
    return False


__all__ = ["encoded_clause", "widens", "with_clause"]
