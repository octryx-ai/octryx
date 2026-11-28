"""Independent evaluation acceptance probes: unknown evidence must not become verified success."""

import json

from app.services.knowledge.eval.library_manifest import load_manifest
from app.services.knowledge.eval.library_scoring import score_documents
from tests.services.knowledge.knowledge_library_eval_support import (
    SHA_A,
    api_hit,
    body,
    capture_doc,
    case,
    judgments,
    manifest_doc,
    only_case,
    record,
    scored,
)


def test_hybrid_missing_component_states_is_not_complete():
    manifest = load_manifest(manifest_doc(case(kind="no_answer")))
    response = body([], mode_states={"lexical": "ok"}, workspace_states={"Own": {"lexical": "ok"}})
    result = only_case(scored(manifest, [record(manifest, "C1", response)]))
    assert result["availability"]["class"] != "complete"
    assert result["outcome"] != "true_empty"


def test_answer_with_unverifiable_workspace_exclusion_is_not_eligible(tmp_path):
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"schema": "octryx.library_eval.prior_queries/v1", "queries": ["older"]}))
    manifest = load_manifest(manifest_doc(case(split="holdout", excluded=[{"workspace_id": "ws-foreign"}])),
                             prior_query_paths=[prior])
    response = body([api_hit("rev1:1", workspace="Unknown unmapped workspace", bound=True)])
    inventory = {"schema": "octryx.library_eval.evidence_inventory/v1", "spans": [{
        "source_id": "src-a", "revision_id": "rev1", "content_sha256": SHA_A, "span_ordinal": 1,
        "span_count": 4, "verified_by": "root", "verified_at": "2026-10-05T08:30:00+00:00",
        "method": "synthetic root inventory"}]}
    result = only_case(scored(manifest, [record(manifest, "C1", response)], inventory=inventory))
    assert result["acceptance"]["state"] == "refused"
    assert "exclusion_unverifiable" in result["acceptance"]["reasons"]


def test_malformed_judgment_hit_collection_returns_invalid_report():
    manifest = load_manifest(manifest_doc(case()))
    capture = capture_doc(manifest, [record(manifest, "C1", body([api_hit("rev1:1")]))])
    malformed = judgments(manifest, capture, ["not an object"])
    assert score_documents(manifest, capture, malformed)["status"] == "invalid"


def test_judgment_on_duplicate_applies_to_first_identity_rank():
    manifest = load_manifest(manifest_doc(case()))
    # Same source content/span under different revision keys: judged equivalent evidence on second occurrence.
    hits = [api_hit("rev2:3"), api_hit("rev3:3")]
    result = only_case(scored(manifest, [record(manifest, "C1", body(hits))],
                              {"C1": {"rev3:3": {"label": "relevant", "supports": ["F1"]}}}))
    assert result["hits"]["relevant"] == 1
    assert result["first_relevant_rank"] == 1


def test_inventory_accepts_actual_one_based_last_span():
    from app.services.knowledge.eval.library_inventory import load_inventory

    entry = {"source_id": "src-a", "revision_id": "rev1", "content_sha256": SHA_A,
             "span_ordinal": 1, "span_count": 1, "verified_by": "root",
             "verified_at": "2026-10-04T08:00:00+00:00", "method": "ledger read"}
    # KnowledgeEvidenceSpan has span_ordinal >= 1. A one-span PDF is key rev1:1.
    load_inventory({"schema": "octryx.library_eval.evidence_inventory/v1", "spans": [entry]})


def test_inventory_refuses_zero_ordinal_outside_product_contract():
    import pytest

    from app.services.knowledge.eval.library_inputs import EvaluationInputError
    from app.services.knowledge.eval.library_inventory import load_inventory

    entry = {"source_id": "src-a", "revision_id": "rev1", "content_sha256": SHA_A,
             "span_ordinal": 0, "span_count": 1, "verified_by": "root",
             "verified_at": "2026-10-04T08:00:00+00:00", "method": "ledger read"}
    with pytest.raises(EvaluationInputError):
        load_inventory({"schema": "octryx.library_eval.evidence_inventory/v1", "spans": [entry]})
