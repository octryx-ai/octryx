"""Safe run-reader projection of internal immutable review snapshots.

Run-read membership is not source-read authority. Never expose snapshot bodies, source text or ACL principals
through the generic event API, including after a later source revocation.
"""
from __future__ import annotations

from .artefact_contract import SNAPSHOT_EVENT

BINDING_FIELDS = frozenset({"kind", "version", "hash", "parent_run_id", "node_id", "entry",
                            "review_node_id", "review_entry", "rubric_version", "source"})
REFERENCE_FIELDS = frozenset({"call_id", "evidence_key", "source_id", "revision_id", "content_sha256", "text_hash"})


def _scalars(raw, allowed):
    return {key: value for key, value in raw.items() if key in allowed and type(value) in (str, int, bool)}


def event_detail(kind: str, detail: dict) -> dict:
    if kind == "specification_read_provenance":
        return {**_scalars(detail, {"kind", "version", "hash", "node_id", "entry"}), "content_withheld": True}
    if kind != SNAPSHOT_EVENT:
        return detail
    snapshot = detail.get("snapshot") if isinstance(detail.get("snapshot"), dict) else {}
    binding = snapshot.get("binding") if isinstance(snapshot.get("binding"), dict) else {}
    evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), list) else []
    return {**_scalars(detail, {"attempt", "snapshot_hash"}), "content_withheld": True,
        "binding": _scalars(binding, BINDING_FIELDS),
        "evidence_refs": [_scalars(ref, REFERENCE_FIELDS) for ref in evidence if isinstance(ref, dict)]}


def gate_detail(gate):
    """Artifact findings can quote evidence; a generic run reader gets state, not that source content."""
    if not isinstance(gate, dict):
        return gate
    results = gate.get("results")
    if not isinstance(results, list):
        return gate
    projected = []
    for result in results:
        if isinstance(result, dict) and result.get("type") == "artefact_review_passed":
            result = {**result, "detail": "Detailed artifact findings remain in the authorized owner phase context."}
        projected.append(result)
    return {**gate, "results": projected}
