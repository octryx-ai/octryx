"""The Table API side of the ServiceNow record limit (``servicenow_record_limit``). The server-side condition is a
superset; each record is also checked exactly client-side."""

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
    # ``^OR`` binds to the condition before it and ``^`` ANDs.
    groups = [_clause_parts(spec, values) for spec, values in limit.lists()]
    if limit is NOTHING or not groups:
        return "sys_idISEMPTY^sys_idISNOTEMPTY"  # the fail-closed limit: a condition no record satisfies
    if limit.mode == MODE_ANY:
        return "^OR".join(part for parts in groups for part in parts)
    return "^".join("^OR".join(parts) for parts in groups)


def with_clause(query: str | None, limit: RecordLimit | None) -> str | None:
    if limit is None:
        return query
    return "^".join(part for part in (encoded_clause(limit), query) if part)


def widens(query: str | None) -> bool:
    # Anything but plain narrowing conditions (then sort-only ``ORDERBY`` segments) could escape the condition it is
    # ANDed after.
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
