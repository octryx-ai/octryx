"""Library evaluation scoring: precision, fact coverage, no-answer outcomes, leaks, duplicates and availability."""

from __future__ import annotations

import json

import pytest

from app.services.knowledge.eval.library_inputs import EvaluationInputError
from app.services.knowledge.eval.library_manifest import load_manifest
from tests.knowledge_library_eval_support import (
    COMPLETE,
    FOREIGN,
    LIB,
    OWN,
    SHA_A,
    SHA_B,
    SHA_C,
    api_hit,
    body,
    case,
    manifest_doc,
    only_case,
    record,
    scored,
)

# --- quality semantics -----------------------------------------------------------------------------


def test_an_irrelevant_tail_lowers_judged_precision_but_not_the_first_rank():
    manifest = load_manifest(manifest_doc(case()))
    lone = only_case(scored(manifest, [record(manifest, "C1", body([api_hit("rev1:1")]))]))
    tail = [api_hit("rev1:1")] + [api_hit(f"rev9:{n}", source="src-z", sha=SHA_C) for n in range(2, 11)]
    labels = {f"rev9:{n}": {"label": "irrelevant", "supports": []} for n in range(2, 11)}
    noisy = only_case(scored(manifest, [record(manifest, "C1", body(tail))], {"C1": labels}))
    assert lone["first_relevant_rank"] == noisy["first_relevant_rank"] == 1
    assert lone["precision_strict"]["value"] == 1.0
    assert (noisy["precision_strict"]["numerator"], noisy["precision_strict"]["denominator"]) == (1, 10)


def test_two_required_facts_with_one_retrieved_is_incomplete_and_partial_is_not_coverage():
    facts = [{"id": "F1", "required": True, "evidence": [{"evidence_key": "rev1:1"}]},
             {"id": "F2", "required": True, "evidence": [{"evidence_key": "rev1:2"}]}]
    manifest = load_manifest(manifest_doc(case(facts=facts)))
    hits = [api_hit("rev1:1"), api_hit("rev7:4", source="src-b", sha=SHA_B)]
    result = only_case(scored(manifest, [record(manifest, "C1", body(hits))],
                              {"C1": {"rev7:4": {"label": "partial", "supports": ["F2"]}}}))
    assert result["outcome"] == "incomplete"
    assert result["fact_coverage"]["judged"]["covered"] == ["F1"]
    assert result["fact_coverage"]["judged"]["partially_covered"] == ["F2"]
    assert result["fact_coverage"]["judged"]["ratio"]["value"] == 0.5


def test_equivalent_evidence_supports_a_fact_but_post_hoc_support_is_reported_apart():
    facts = [{"id": "F1", "required": True, "evidence": [
        {"evidence_key": "rev1:1"}, {"source_id": "src-b", "content_sha256": SHA_B, "span_ordinal": 3}]}]
    manifest = load_manifest(manifest_doc(case(facts=facts)))
    by_span = only_case(scored(manifest, [record(manifest, "C1", body([api_hit("rev2:3", source="src-b", sha=SHA_B)]))]))
    assert by_span["fact_coverage"]["prelabeled"]["covered"] == ["F1"]
    post_hoc = only_case(scored(manifest, [record(manifest, "C1", body([api_hit("rev5:5", source="src-c", sha=SHA_C)]))],
                                {"C1": {"rev5:5": {"label": "relevant", "supports": ["F1"]}}}))
    assert post_hoc["fact_coverage"]["prelabeled"]["covered"] == []
    assert post_hoc["fact_coverage"]["judged"]["covered"] == ["F1"]


def test_unjudged_hits_stay_unjudged_and_only_widen_the_bounds():
    manifest = load_manifest(manifest_doc(case()))
    hits = [api_hit("rev1:1"), api_hit("rev8:2", source="src-y", sha=SHA_C), api_hit("rev8:3", source="src-y", sha=SHA_C)]
    result = only_case(scored(manifest, [record(manifest, "C1", body(hits))]))
    assert result["hits"]["unjudged"] == 2
    assert (result["precision_strict"]["numerator"], result["precision_strict"]["denominator"]) == (1, 1)
    low, high = result["precision_strict_bounds"]
    assert (low["numerator"], low["denominator"], high["numerator"]) == (1, 3, 3)


def test_no_answer_distinguishes_true_empty_errors_degraded_and_false_positives():
    cases = [case(f"N{n}", kind="no_answer") for n in range(4)]
    manifest = load_manifest(manifest_doc(*cases))
    records = [
        record(manifest, "N0", body([])),
        record(manifest, "N1", {"detail": {"code": "unavailable", "message": "secret upstream text"}}, status=503),
        record(manifest, "N2", body([], mode_states={"lexical": "ok", "vector": "unavailable", "rerank": "ok"})),
        record(manifest, "N3", body([api_hit("rev4:1")])),
    ]
    report = scored(manifest, records)
    outcomes = {item["case_id"]: item["outcome"] for item in report["cases"]}
    assert outcomes == {"N0": "true_empty", "N1": "error", "N2": "empty_degraded", "N3": "false_positive:1"}
    assert records[1]["error_code"] == "unavailable"
    assert "secret upstream text" not in json.dumps(records)


def test_foreign_and_revoked_evidence_is_a_leak_and_unknown_workspaces_are_unverifiable():
    excluded = [{"evidence_key": "rev3:1"}, {"source_id": "src-revoked"}, {"workspace_id": FOREIGN}]
    manifest = load_manifest(manifest_doc(case("X1", kind="exclusion", excluded=excluded),
                                          case("X2", kind="exclusion", excluded=[{"workspace_id": FOREIGN}])))
    leaks = [api_hit("rev3:1"), api_hit("rev6:2", source="src-revoked"),
             api_hit("rev7:3", source="src-f", workspace="Foreign", bound=True)]
    unknown = [api_hit("rev8:1", source="src-u", workspace="Unmapped", bound=True)]
    report = scored(manifest, [record(manifest, "X1", body(leaks)), record(manifest, "X2", body(unknown))])
    by_id = {item["case_id"]: item for item in report["cases"]}
    assert by_id["X1"]["outcome"] == "leak" and len(by_id["X1"]["leaks"]) == 3
    assert by_id["X2"]["outcome"] == "unverifiable"


def test_workspace_exclusions_need_an_unambiguous_root_map():
    with pytest.raises(EvaluationInputError, match="not in workspace_name_map"):
        load_manifest(manifest_doc(case("X", kind="exclusion", excluded=[{"workspace_id": "ws-unmapped"}])))
    with pytest.raises(EvaluationInputError, match="ambiguous"):
        load_manifest(manifest_doc(case(), workspace_name_map={OWN: "Same", LIB: "Same"}))


def test_duplicates_cannot_inflate_coverage_or_carry_conflicting_labels():
    manifest = load_manifest(manifest_doc(case()))
    duplicate = [api_hit("rev1:1"), api_hit("rev1:1"), api_hit("revX:1", source="src-a", sha=SHA_A, ordinal=1)]
    result = only_case(scored(manifest, [record(manifest, "C1", body(duplicate))]))
    assert result["hits"] == {"raw_returned": 3, "unique": 1, "duplicates": 2, "relevant": 1, "partial": 0,
                              "irrelevant": 0, "excluded_leak": 0, "unjudged": 0}
    assert result["fact_coverage"]["judged"]["ratio"]["numerator"] == 1
    pair = [api_hit("rev5:2", source="src-d", sha=SHA_C), api_hit("rev6:2", source="src-d", sha=SHA_C)]
    conflicting = {"C1": {"rev5:2": {"label": "relevant", "supports": ["F1"]},
                          "rev6:2": {"label": "irrelevant", "supports": []}}}
    report = scored(manifest, [record(manifest, "C1", body(pair))], conflicting)
    assert report["status"] == "invalid" and any("conflicting" in item for item in report["problems"])


def test_availability_separates_expected_skips_from_failed_components_and_malformed_metadata():
    manifest = load_manifest(manifest_doc(case("H1"), case("H2"), case("H3"), case("L1", mode="lexical")))
    skipped = {"Own": COMPLETE, "Library": {"state": "outside_binding_products"}}
    failed = {"Own": COMPLETE, "Library": {"lexical": "ok", "vector": "ok", "rerank": "needs_configuration"}}
    malformed = {"workspace_id": OWN, "limit": 10, "evidence": []}
    report = scored(manifest, [
        record(manifest, "H1", body([], workspace_states=skipped)),
        record(manifest, "H2", body([], workspace_states=failed)),
        record(manifest, "H3", malformed),
        record(manifest, "L1", {"workspace_id": OWN, "limit": 10, "mode_states": {"lexical": "ok"}, "evidence": []}),
    ])
    classes = {item["case_id"]: item["availability"]["class"] for item in report["cases"]}
    assert classes == {"H1": "complete", "H2": "partial", "H3": "malformed", "L1": "complete"}
    lexical = next(item for item in report["cases"] if item["case_id"] == "L1")
    assert lexical["scope"] == "single_workspace" and lexical["availability"]["api_reported_constant"] is True
    assert report["provider_usage"]["state"] == "unavailable"


# --- judge boundaries: contract shapes, malformed nesting, explicit exclusion state ---------------


@pytest.mark.parametrize("mode_states, workspace_states, expected", [
    (COMPLETE, {"Own": COMPLETE, "Library": {"state": "classification_above_reader"}}, "complete"),
    (COMPLETE, {"Own": COMPLETE, "Library": {"state": "classification_unresolved"}}, "partial"),
    (COMPLETE, {"Own": COMPLETE, "Library": {"state": "unavailable"}}, "partial"),
    ({"state": "unavailable"}, {"Own": {"state": "unavailable"}, "Library": COMPLETE}, "partial"),
    ({"state": "no_sources"}, {"Own": {"state": "no_sources"}}, "error"),
    ({"lexical": "ok", "vector": "ok"}, {"Own": {"lexical": "ok", "vector": "ok"}}, "malformed"),
    ({**COMPLETE, "extra": "ok"}, {"Own": {**COMPLETE, "extra": "ok"}}, "malformed"),
    (COMPLETE, {"Own": {"lexical": "ok", "vector": "unavailable", "rerank": "ok"}}, "malformed"),
    (COMPLETE, {"Own": COMPLETE, "Library": {"state": "x", "detail": "y"}}, "malformed"),
])
def test_hybrid_availability_follows_the_scoped_response_contract(mode_states, workspace_states, expected):
    manifest = load_manifest(manifest_doc(case(kind="no_answer")))
    response = body([], mode_states=mode_states, workspace_states=workspace_states)
    result = only_case(scored(manifest, [record(manifest, "C1", response)]))
    assert result["availability"]["class"] == expected
    assert (result["outcome"] == "true_empty") is (expected == "complete")


def test_lexical_availability_must_be_the_routes_constant():
    manifest = load_manifest(manifest_doc(case(kind="no_answer", mode="lexical")))
    response = {"workspace_id": OWN, "limit": 10, "mode_states": {"lexical": "ok", "vector": "ok"}, "evidence": []}
    assert only_case(scored(manifest, [record(manifest, "C1", response)]))["availability"]["class"] == "malformed"


def test_every_case_kind_reports_its_exclusion_check(tmp_path):
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"schema": "octryx.library_eval.prior_queries/v1", "queries": ["older"]}))
    foreign = [{"workspace_id": FOREIGN}]
    manifest = load_manifest(manifest_doc(
        case("A1", split="holdout", excluded=foreign), case("N1", kind="no_answer", split="holdout", excluded=foreign),
        case("P1"), case("E1", kind="no_answer", split="holdout", excluded=foreign),
    ), prior_query_paths=[prior])
    report = scored(manifest, [
        record(manifest, "A1", body([api_hit("rev1:1", workspace="Unmapped", bound=True)])),
        record(manifest, "N1", body([])),
        record(manifest, "P1", body([api_hit("rev1:1")])),
        record(manifest, "E1", {"detail": {"code": "unavailable"}}, status=503),
    ])
    by_id = {item["case_id"]: item for item in report["cases"]}
    assert by_id["A1"]["exclusion_check"] == "unverifiable"
    assert "exclusion_unverifiable" in by_id["A1"]["acceptance"]["reasons"]
    assert by_id["N1"]["exclusion_check"] == "verified"
    assert by_id["P1"]["exclusion_check"] == "not_requested"
    assert "exclusion_not_evaluated" in by_id["E1"]["acceptance"]["reasons"]


def test_the_first_relevant_rank_uses_the_resolved_identity_group():
    manifest = load_manifest(manifest_doc(case()))
    hits = [api_hit("rev8:1", source="src-x", sha=SHA_C), api_hit("rev2:3"), api_hit("rev3:3")]
    result = only_case(scored(manifest, [record(manifest, "C1", body(hits))],
                              {"C1": {"rev3:3": {"label": "relevant", "supports": ["F1"]}}}))
    assert (result["first_relevant_rank"], result["hits"]["relevant"], result["hits"]["unjudged"]) == (2, 1, 1)
