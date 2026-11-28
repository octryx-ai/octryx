"""Read-only Library evaluation contract: deterministic, synthetic, no network or database."""

from __future__ import annotations

import copy
import json

import pytest

from app.services.knowledge.eval import library_inventory
from app.services.knowledge.eval.library_inputs import EvaluationInputError
from app.services.knowledge.eval.library_manifest import load_manifest
from app.services.knowledge.eval.library_scoring import score_documents
from tests.services.knowledge.knowledge_library_eval_support import (
    OWN,
    SHA_A,
    SHA_B,
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


def _break_capture(path, value):
    def mutate(document):
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


# --- frozen input and gate refusals ----------------------------------------------------------------


@pytest.mark.parametrize("mutate, reason", [
    (lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "duplicate case id"),
    (lambda d: d["cases"][0]["excluded"].append({"evidence_key": "rev1:1"}), "both supports a fact and is excluded"),
    (lambda d: d["cases"].extend(case(f"E{n}") for n in range(8)), "exceed max_search_requests"),
    (lambda d: d["cases"][0].update(limit=11), "limit must be 1-10"),
    (lambda d: d["budget"].update(max_source_reads=1), "max_source_reads"),
    (lambda d: d["budget"].update(max_logical_provider_ops=11), "logical provider operations"),
    (lambda d: d["budget"].update(concurrency=2), "concurrency"),
    (lambda d: d["budget"].update(retries=3), "unknown keys"),
    (lambda d: d["cases"][0].update(kind="no_answer"), "no_answer case has no facts"),
    (lambda d: d.update(frozen_at="2026-10-05"), "frozen_at"),
])
def test_invalid_manifests_are_refused(mutate, reason):
    document = manifest_doc(case())
    mutate(document)
    with pytest.raises(EvaluationInputError, match=reason):
        load_manifest(document)


def test_holdout_requires_prior_queries_and_refuses_known_reuse(tmp_path):
    with pytest.raises(EvaluationInputError, match="require the prior-query input"):
        load_manifest(manifest_doc(case(split="holdout")))
    prior = tmp_path / "frozen-cases.json"
    prior.write_text(json.dumps({"cases": [{"query": "Octryx local PDF acceptance fixture"}]}))
    reused = case(split="holdout", query="  octryx LOCAL pdf acceptance fixture. ")
    with pytest.raises(EvaluationInputError, match="reuse prior queries"):
        load_manifest(manifest_doc(reused), prior_query_paths=[prior])
    golden = case(split="holdout", query="What is the minimum Java version for Spring Boot 4?")
    with pytest.raises(EvaluationInputError, match="reuse prior queries"):
        load_manifest(manifest_doc(golden), prior_query_paths=[prior])
    fresh = load_manifest(manifest_doc(case(split="holdout")), prior_query_paths=[prior])
    assert fresh.overlap_check["performed"] and "does not certify" in fresh.overlap_check["method"]


def test_capture_and_judgment_gates_refuse_tampering_and_inconsistency():
    manifest = load_manifest(manifest_doc(case(), case("C2")))
    good = [record(manifest, "C1", body([api_hit("rev1:1"), api_hit("rev2:1", source="s2", sha=SHA_B)])),
            record(manifest, "C2", body([]))]

    def problems(records=good, judged=None, **kwargs):
        document = capture_doc(manifest, records, **kwargs)
        return score_documents(manifest, document, judgments(manifest, document, judged) if judged else None)

    assert problems()["status"] == "scored"
    tampered = capture_doc(manifest, good)
    tampered["manifest_sha256"] = "0" * 64
    assert score_documents(manifest, tampered)["status"] == "invalid"
    assert "more than once" in " ".join(problems([*good, good[0]])["problems"])
    changed = copy.deepcopy(good)
    changed[0]["request"]["query_text"] = "another question"
    assert "differs from the frozen case" in " ".join(problems(changed)["problems"])
    endless = copy.deepcopy(good)
    endless[0]["latency_ms"] = float("inf")
    assert "non-finite" in " ".join(problems(endless)["problems"])
    for judged, reason in [
        ({"C9": {}}, "unknown case"),
        ({"C1": {"rev404:1": {"label": "relevant", "supports": []}}}, "no such captured hit"),
        ({"C1": {"rev2:1": {"label": "relevant", "supports": ["F9"]}}}, "unknown facts"),
        ({"C1": {"rev2:1": {"label": "irrelevant", "supports": ["F1"]}}}, "cannot support"),
        ({"C1": {"rev1:1": {"label": "irrelevant", "supports": []}}}, "prelabeled"),
        ({"C1": {"rev2:1": {"label": "maybe", "supports": []}}}, "label must be"),
    ]:
        assert reason in " ".join(problems(judged=judged)["problems"]), reason
    document = capture_doc(manifest, good)
    stale = judgments(manifest, document, {"C1": {}})
    document["requests_used"] = 2  # unchanged count, but any edit after judging changes the hash
    document["finished_at"] = "2026-10-05T10:06:00+00:00"
    assert "hashes do not match" in " ".join(score_documents(manifest, document, stale)["problems"])


def test_holdout_needs_a_capture_after_the_freeze_and_verified_corpus_evidence(tmp_path):
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"schema": "octryx.library_eval.prior_queries/v1", "queries": ["older"]}))
    manifest = load_manifest(manifest_doc(case(split="holdout")), prior_query_paths=[prior])
    records = [record(manifest, "C1", body([api_hit("rev1:1")]))]
    early = scored(manifest, records, started_at="2026-10-05T08:00:00+00:00")
    assert early["status"] == "invalid" and "after the manifest was frozen" in " ".join(early["problems"])
    unverified = only_case(scored(manifest, records))
    assert unverified["acceptance"] == {"state": "refused", "reasons": ["evidence_unverified:F1"]}
    inventory = {"schema": "octryx.library_eval.evidence_inventory/v1", "spans": [{
        "source_id": "src-a", "revision_id": "rev1", "content_sha256": SHA_A, "span_ordinal": 1, "span_count": 4,
        "verified_by": "root", "verified_at": "2026-10-05T08:30:00+00:00", "method": "ledger read, offline"}]}
    eligible = only_case(scored(manifest, records, inventory=inventory))
    assert eligible["acceptance"] == {"state": "eligible", "reasons": []}
    stale_inventory = copy.deepcopy(inventory)
    stale_inventory["spans"][0].update(revision_id="rev2", content_sha256=SHA_B)
    stale_manifest = load_manifest(manifest_doc(case(split="holdout", facts=[{"id": "F1", "required": True, "evidence": [
        {"source_id": "src-a", "content_sha256": SHA_A, "span_ordinal": 1}]}])), prior_query_paths=[prior])
    stale_records = [record(stale_manifest, "C1", body([api_hit("rev1:1")]))]
    stale = only_case(scored(stale_manifest, stale_records, inventory=stale_inventory))
    assert stale["acceptance"]["reasons"] == ["evidence_stale:F1"]


@pytest.mark.parametrize("mutate", [
    _break_capture(["cases"], {"C1": {}}),
    _break_capture(["cases", 0], "not a record"),
    _break_capture(["cases", 0, "hits", 0], "not a hit"),
    _break_capture(["cases", 0, "hits", 0, "found_by"], [1, ["x"]]),
    _break_capture(["cases", 0, "hits", 0, "span_ordinal"], True),
    _break_capture(["cases", 0, "hits", 0, "bound"], "yes"),
    _break_capture(["cases", 0, "hits", 0, "source_id"], ["src-a"]),
    _break_capture(["cases", 0, "mode_states"], ["ok"]),
    _break_capture(["cases", 0, "metadata_valid"], "true"),
    _break_capture(["cases", 0, "http_status"], "200"),
])
def test_structurally_malformed_captures_return_an_invalid_report(mutate):
    manifest = load_manifest(manifest_doc(case()))
    document = capture_doc(manifest, [record(manifest, "C1", body([api_hit("rev1:1")]))])
    mutate(document)
    report = score_documents(manifest, document)
    assert report["status"] == "invalid" and report["problems"] and "cases" not in report


@pytest.mark.parametrize("hits", [
    ["not an object"],
    {"C1": ["rev2:1"]},
    {"C1": {"rev2:1": "relevant"}},
    {"C1": {"rev2:1": {"label": "relevant", "supports": [["F1"]]}}},
    {"C1": {"rev2:1": {"label": "relevant", "supports": [1]}}},
    {"C1": {"rev2:1": {"label": 5, "supports": []}}},
    {"C1": {"rev2:1": {"label": "relevant", "supports": "F1"}}},
])
def test_structurally_malformed_judgments_return_an_invalid_report(hits):
    manifest = load_manifest(manifest_doc(case()))
    document = capture_doc(manifest, [record(manifest, "C1", body([api_hit("rev2:1", source="s2", sha=SHA_B)]))])
    report = score_documents(manifest, document, judgments(manifest, document, hits))
    assert report["status"] == "invalid" and report["problems"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["cases"][0].update(workspace=["P"]),
    lambda d: d["cases"][0].update(facts="F1"),
    lambda d: d["cases"][0].update(facts=[5]),
    lambda d: d["cases"][0]["facts"][0].update(evidence="rev1:1"),
    lambda d: d["cases"][0]["facts"][0].update(evidence=[["rev1:1"]]),
    lambda d: d["cases"][0].update(excluded={"evidence_key": "x"}),
    lambda d: d["cases"][0].update(excluded=[{"evidence_key": ["x"]}]),
    lambda d: d["cases"][0].update(products=[1]),
    lambda d: d.update(cases={"C1": {}}),
    lambda d: d.update(workspaces={"P": ["ws"]}),
    lambda d: d.update(workspace_name_map={OWN: ["Own"]}),
])
def test_structurally_malformed_manifests_are_refused_with_a_typed_error(mutate):
    document = manifest_doc(case())
    mutate(document)
    with pytest.raises(EvaluationInputError):
        load_manifest(document)


@pytest.mark.parametrize("spans", ["x", {"a": 1}, [{"source_id": ["s"]}], [{
    "source_id": "s", "revision_id": "r", "content_sha256": SHA_A, "span_ordinal": True, "span_count": 2,
    "verified_by": "root", "verified_at": "2026-10-05T00:00:00+00:00", "method": "offline"}]])
def test_structurally_malformed_inventories_are_refused(spans):
    manifest = load_manifest(manifest_doc(case()))
    document = capture_doc(manifest, [record(manifest, "C1", body([api_hit("rev1:1")]))])
    inventory = {"schema": "octryx.library_eval.evidence_inventory/v1", "spans": spans}
    report = score_documents(manifest, document, None, inventory)
    assert report["status"] == "invalid" and report["problems"]


def test_span_ordinals_follow_the_one_based_ledger_contract():
    zero_ref = case(facts=[{"id": "F1", "required": True, "evidence": [
        {"source_id": "src-a", "content_sha256": SHA_A, "span_ordinal": 0}]}])
    with pytest.raises(EvaluationInputError, match="evidence alternative"):
        load_manifest(manifest_doc(zero_ref))
    entry = {"source_id": "src-a", "revision_id": "rev1", "content_sha256": SHA_A, "span_ordinal": 4, "span_count": 4,
             "verified_by": "root", "verified_at": "2026-10-05T00:00:00+00:00", "method": "offline"}
    library_inventory.load_inventory({"schema": "octryx.library_eval.evidence_inventory/v1", "spans": [entry]})
    with pytest.raises(EvaluationInputError):
        library_inventory.load_inventory({"schema": "octryx.library_eval.evidence_inventory/v1",
                                         "spans": [{**entry, "span_ordinal": 5}]})
    manifest = load_manifest(manifest_doc(case()))
    assert record(manifest, "C1", body([api_hit("rev1:0", ordinal=0)]))["response_state"] == "malformed"
    document = capture_doc(manifest, [record(manifest, "C1", body([api_hit("rev1:1")]))])
    document["cases"][0]["hits"][0]["span_ordinal"] = 0
    assert score_documents(manifest, document)["status"] == "invalid"
