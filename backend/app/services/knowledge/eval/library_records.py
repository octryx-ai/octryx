"""Capture records: one per case, built from a search response and re-validated before scoring."""

from __future__ import annotations

import re
from typing import Any

from .library_inputs import MODE_SCOPE, Case, Manifest, is_finite_number, is_identifier, parse_timestamp
from .library_targets import (
    _HIT_TYPES,
    _SAFE_CODE,
    CAPTURE_SCHEMA,
    EXCERPT_CHARS,
    RESPONSE_STATES,
    TITLE_CHARS,
)


def _text(value: Any, limit: int) -> str | None:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else None


def _states(value: Any) -> tuple[dict[str, Any] | None, bool]:
    """String states or one nested level of them; anything else is malformed metadata."""
    if not isinstance(value, dict):
        return None, False
    clean: dict[str, Any] = {}
    for key, state in value.items():
        if not isinstance(key, str) or len(key) > 200:
            return None, False
        if isinstance(state, str) and len(state) <= 64:
            clean[key] = state
        elif isinstance(state, dict) and all(
            isinstance(k, str) and isinstance(v, str) and len(v) <= 64 for k, v in state.items()
        ):
            clean[key] = dict(state)
        else:
            return None, False
    return clean, True


def _error_code(body: Any) -> str | None:
    """Only a short, safe, typed code; never free error text."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        for key in ("code", "state"):
            if isinstance(detail.get(key), str) and _SAFE_CODE.match(detail[key]):
                return detail[key]
    if isinstance(detail, str) and _SAFE_CODE.match(detail):
        return detail
    return None


def _hit(rank: int, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not is_identifier(raw.get("evidence_key")):
        return None
    similarity, relevance = raw.get("similarity"), raw.get("relevance")
    if any(value is not None and not is_finite_number(value) for value in (similarity, relevance)):
        return None
    ordinal = raw.get("span_ordinal")
    if ordinal is not None and (type(ordinal) is not int or ordinal < 1):
        return None  # span ordinals are one-based; anything else is a malformed response
    found_by = raw.get("found_by")
    return {
        "rank": rank,
        "evidence_key": raw["evidence_key"],
        "source_id": raw.get("source_id") if is_identifier(raw.get("source_id")) else None,
        "revision_id": raw.get("revision_id") if is_identifier(raw.get("revision_id")) else None,
        "span_ordinal": ordinal,
        "content_sha256": raw.get("content_sha256") if isinstance(raw.get("content_sha256"), str) else None,
        "workspace": _text(raw.get("workspace"), 200),
        "bound": raw.get("bound") if isinstance(raw.get("bound"), bool) else None,
        "found_by": [item for item in found_by if isinstance(item, str)][:4] if isinstance(found_by, list) else [],
        "similarity_uncalibrated": similarity,
        "relevance_uncalibrated": relevance,
        "title": _text(raw.get("source_title"), TITLE_CHARS),
        "excerpt": _text(raw.get("text"), EXCERPT_CHARS),
    }


def capture_record(case, project_id: str, *, status: int | None, body: Any, latency_ms: float, failure: str = ""):
    """One sanitized capture entry from what the server returned (or a transport failure)."""
    record: dict[str, Any] = {
        "case_id": case.id,
        "request": {
            "workspace_id": project_id,
            "mode": case.mode,
            "limit": case.limit,
            "query_text": case.query,
            "products": list(case.products) if case.products is not None else None,
            "version": case.version,
        },
        "scope": MODE_SCOPE[case.mode],
        "http_status": status,
        "latency_ms": round(latency_ms, 1),
        "response_state": "ok",
        "error_code": None,
        "mode_states": None,
        "workspace_states": None,
        "metadata_valid": False,
        "hits": [],
    }
    if failure:
        record.update(response_state="transport_error", error_code=failure)
        return record
    if status != 200:
        record.update(response_state="http_error", error_code=_error_code(body))
        return record
    evidence = body.get("evidence") if isinstance(body, dict) else None
    if not isinstance(evidence, list) or len(evidence) > case.limit:
        record["response_state"] = "malformed"
        return record
    hits = [_hit(rank, raw) for rank, raw in enumerate(evidence, start=1)]
    if any(hit is None for hit in hits):
        record["response_state"] = "malformed"
        return record
    mode_states, modes_ok = _states(body.get("mode_states"))
    workspace_states, workspaces_ok = (None, True)
    if case.mode == "hybrid":
        workspace_states, workspaces_ok = _states(body.get("workspace_states"))
    record.update(
        hits=hits, mode_states=mode_states, workspace_states=workspace_states, metadata_valid=modes_ok and workspaces_ok
    )
    return record


def validate_capture(capture: Any, manifest: Manifest, problems: list[str]) -> dict[str, dict[str, Any]]:
    """Structural and frozen-case checks of a capture document; problems are appended, records returned by id."""
    if not isinstance(capture, dict) or capture.get("schema") != CAPTURE_SCHEMA:
        problems.append(f"capture: schema must be {CAPTURE_SCHEMA}")
        return {}
    if capture.get("manifest_sha256") != manifest.sha256:
        problems.append("capture: manifest_sha256 does not match the recomputed manifest hash")
    started, finished = parse_timestamp(capture.get("started_at")), parse_timestamp(capture.get("finished_at"))
    if started is None or finished is None or finished < started:
        problems.append("capture: started_at/finished_at must be ordered ISO-8601 timestamps with offsets")
    elif any(case.split == "holdout" for case in manifest.cases) and not started > manifest.frozen_at:
        problems.append("capture: holdout cases need a capture that started after the manifest was frozen")
    records = capture.get("cases")
    if not isinstance(records, list):
        problems.append("capture: cases must be a list")
        return {}
    budget = manifest.budget["max_search_requests"]
    if capture.get("requests_used") != len(records) or len(records) > budget:
        problems.append("capture: requests_used must equal the captured cases and stay within the budget")
    by_id: dict[str, dict[str, Any]] = {}
    cases = {case.id: case for case in manifest.cases}
    for record in records:
        case_id = record.get("case_id") if isinstance(record, dict) else None
        if case_id not in cases:
            problems.append(f"capture: unknown case {case_id!r}")
            continue
        if case_id in by_id:
            problems.append(f"capture: case {case_id} captured more than once")
            continue
        by_id[case_id] = record
        _validate_record(record, cases[case_id], manifest, problems)
    missing = sorted(set(cases) - set(by_id))
    if missing:
        problems.append(f"capture: cases not captured: {missing}")
    return by_id


def _validate_record(record: dict[str, Any], case: Case, manifest: Manifest, problems: list[str]) -> None:
    where = f"capture case {case.id}"
    expected = {
        "workspace_id": manifest.workspaces[case.workspace],
        "mode": case.mode,
        "limit": case.limit,
        "query_text": case.query,
        "products": list(case.products) if case.products is not None else None,
        "version": case.version,
    }
    if record.get("request") != expected:
        problems.append(f"{where}: request differs from the frozen case")
    if record.get("scope") != MODE_SCOPE[case.mode]:
        problems.append(f"{where}: scope must be {MODE_SCOPE[case.mode]}")
    if record.get("response_state") not in RESPONSE_STATES:
        problems.append(f"{where}: unknown response_state")
    status = record.get("http_status")
    if status is not None and (not isinstance(status, int) or isinstance(status, bool)):
        problems.append(f"{where}: http_status must be an integer or null")
    if record.get("error_code") is not None and not isinstance(record["error_code"], str):
        problems.append(f"{where}: error_code must be a string or null")
    if not isinstance(record.get("metadata_valid"), bool):
        problems.append(f"{where}: metadata_valid must be a boolean")
    for key in ("mode_states", "workspace_states"):
        if record.get(key) is not None and not isinstance(record[key], dict):
            problems.append(f"{where}: {key} must be an object or null")
    if not is_finite_number(record.get("latency_ms")) or record["latency_ms"] < 0:
        problems.append(f"{where}: latency_ms must be a finite non-negative number")
    hits = record.get("hits")
    if not isinstance(hits, list) or len(hits) > case.limit:
        problems.append(f"{where}: hits must be a list within the limit")
        return
    if record.get("response_state") == "ok" and record.get("http_status") != 200:
        problems.append(f"{where}: an ok response needs HTTP 200")
    if record.get("response_state") != "ok" and hits:
        problems.append(f"{where}: a failed response cannot carry hits")
    for rank, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict) or hit.get("rank") != rank or not is_identifier(hit.get("evidence_key")):
            problems.append(f"{where}: hit {rank} needs consecutive rank and a valid evidence_key")
            continue
        wrong = [key for key, types in _HIT_TYPES.items() if not isinstance(hit.get(key), types)]
        ordinal = hit.get("span_ordinal")
        if ordinal is not None and (type(ordinal) is not int or ordinal < 1):
            wrong.append("span_ordinal")
        if isinstance(hit.get("found_by"), list) and not all(isinstance(item, str) for item in hit["found_by"]):
            wrong.append("found_by")
        for key in ("similarity_uncalibrated", "relevance_uncalibrated"):
            if hit.get(key) is not None and not is_finite_number(hit[key]):
                wrong.append(key)
        if wrong:
            problems.append(f"{where}: hit {rank} has malformed fields {sorted(set(wrong))}")
