"""The assignment groups and services seen in recent ServiceNow records: suggestions for the record limit."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from ...servicenow_record_limit import CHECK_FIELDS, FIELDS, record_in_limit, record_limit, record_refs
from ...servicenow_scripted_fetch import fetch_matching_records
from .source import CODE_TABLE_NOT_CONFIGURED, IntakeSourceError, endpoint, reading, table_records

SAMPLE = 500
MAX_VALUES = 50
TABLES = ("incident", "change_request")


def _allowed_tables(config: Mapping[str, Any]) -> set[str]:
    raw = config.get("servicenow_allowed_tables")
    items = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    return {str(item).strip() for item in items if str(item).strip()}


def _counted(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    counts: dict[str, Counter[str]] = {spec.key: Counter() for spec in FIELDS}
    shown: dict[str, dict[str, str]] = {spec.key: {} for spec in FIELDS}
    for record in records:
        for key, refs in record_refs(record).items():
            names = {" ".join(name.split()) for _sys_id, name in refs if isinstance(name, str) and name.strip()}
            for name in names:  # one count per record, however many keys carry the name
                folded = name.casefold()
                shown[key].setdefault(folded, name)
                counts[key][folded] += 1
    return {key: [{"name": shown[key][folded], "count": count}
                  for folded, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:MAX_VALUES]]
            for key, counter in counts.items()}


async def known_values(config: Mapping[str, Any], *, limited: bool, table: str = "incident") -> dict[str, Any]:
    if table not in TABLES:
        raise IntakeSourceError(CODE_TABLE_NOT_CONFIGURED, f"table must be one of: {', '.join(TABLES)}")
    allowed = _allowed_tables(config)
    if allowed and table not in allowed:
        raise IntakeSourceError(CODE_TABLE_NOT_CONFIGURED, f"{table} is not in the connector's allowed tables")
    target = endpoint(config)
    scope = record_limit(config) if limited else None
    async with reading(target) as client:
        if target.api is None:
            records = await table_records(client, target.base_url, table, None, SAMPLE, target.headers, scope,
                                          fields=",".join(CHECK_FIELDS))
        else:
            path = target.api.paths.get(table)
            if not path:
                raise IntakeSourceError(CODE_TABLE_NOT_CONFIGURED, f"no Scripted REST path for {table}")
            records, _complete = await fetch_matching_records(
                client, target.base_url, path, table, limit=SAMPLE, page_size=target.api.page_size,
                headers=target.headers, keep=lambda record: record_in_limit(record, scope), max_scanned=SAMPLE,
            )
    return {"table": table, "scanned": len(records), **_counted(records)}


__all__ = ["MAX_VALUES", "SAMPLE", "known_values"]
