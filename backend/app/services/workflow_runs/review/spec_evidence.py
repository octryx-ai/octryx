"""Adapt the producer-owned exact specification resolver to immutable artifact review."""
from __future__ import annotations

import copy
from importlib import import_module

from ..phase_outputs import output_hash
from .artefact_contract import SPEC_KIND, ArtefactUnavailableError

RESOLVER_MODULE = "app.services.workflow_runs.specification.lineage"


async def resolve_spec_review_snapshot(db, run, node, *, actor, envelope, proof, review_entry=None):
    """No draft/URL fallback: producer authority and this review's current-pass proof must agree."""
    try:
        lineage = import_module(RESOLVER_MODULE)
    except ModuleNotFoundError as error:
        if error.name in {RESOLVER_MODULE, RESOLVER_MODULE.rsplit(".", 1)[0]}:
            raise ArtefactUnavailableError("specification_resolver_unavailable") from error
        raise
    resolver = getattr(lineage, "resolve_spec_snapshot", None)
    unavailable = getattr(lineage, "SpecificationUnavailable", None)
    if not callable(resolver) or not isinstance(unavailable, type) or not issubclass(unavailable, Exception):
        raise ArtefactUnavailableError("specification_resolver_unavailable")
    try:
        resolved = await resolver(db, run, principal=actor, purpose="review")
    except unavailable as error:
        raise ArtefactUnavailableError("specification_snapshot_unavailable") from error
    expected = {"kind": SPEC_KIND, "version": envelope["version"], "hash": envelope["hash"],
                "parent_run_id": run.id, "node_id": envelope["node_id"], "entry": envelope["entry"],
                "principal_user_id": actor.id, "workspace_id": run.project_id}
    if not isinstance(resolved, dict):
        raise ArtefactUnavailableError("specification_resolver_binding_mismatch")
    binding = resolved.get("binding")
    record = envelope["record"]
    if (not isinstance(binding, dict) or any(binding.get(key) != value for key, value in expected.items())
            or resolved.get("envelope") != envelope or resolved.get("evidence") != record.get("evidence")
            or any(binding.get(key) != record.get(key) or not isinstance(record.get(key), dict)
                   for key in ("idea_frame_ref", "research_brief_ref"))):
        raise ArtefactUnavailableError("specification_resolver_binding_mismatch")
    upstream = resolved.get("upstream")
    if not isinstance(upstream, dict) or set(upstream) != {"idea_frame", "research_brief"}:
        raise ArtefactUnavailableError("specification_upstream_unverified")
    for kind, saved in upstream.items():
        ref = record[kind + "_ref"]
        if (not isinstance(saved, dict) or not isinstance(saved.get("record"), dict)
                or saved.get("kind") != kind or saved.get("hash") != output_hash(saved["record"])
                or any(saved.get(key) != ref.get(key) for key in ("kind", "version", "hash", "node_id", "entry"))
                or ref.get("parent_run_id") != run.id):
            raise ArtefactUnavailableError("specification_upstream_unverified")
    evidence = resolved["evidence"]
    if (not isinstance(evidence, list) or not 1 <= len(evidence) <= 8
            or any(not isinstance(ref, dict) or not isinstance(ref.get("text"), str)
                   or not ref["text"] or len(ref["text"]) > 8000
                   or any(not isinstance(ref.get(key), str) or not ref[key]
                          for key in ("call_id", "evidence_key", "source_id", "revision_id", "content_sha256"))
                   or ref.get("text_hash") != output_hash({"text": ref["text"]}) for ref in evidence)
            or sum(len(ref["text"]) for ref in evidence) > 30000):
        raise ArtefactUnavailableError("specification_evidence_unverified")
    snapshot_binding = {**expected,
        "review_node_id": node.id,
        "review_entry": review_entry if review_entry is not None else dict(run.node_state or {}).get("entry"),
        "owner_id": actor.id, "owner_binding": copy.deepcopy(dict(run.context or {}).get("handoff_binding")),
        "rubric_version": 1, "source": "local_output",
        "producer_call_ids": copy.deepcopy(proof.get("call_ids", [])),
        "evidence_call_ids": sorted({ref["call_id"] for ref in evidence}),
        "idea_frame_ref": copy.deepcopy(record["idea_frame_ref"]),
        "research_brief_ref": copy.deepcopy(record["research_brief_ref"])}
    return {"binding": snapshot_binding, "envelope": copy.deepcopy(envelope),
            "evidence": copy.deepcopy(evidence), "upstream": copy.deepcopy(upstream)}
