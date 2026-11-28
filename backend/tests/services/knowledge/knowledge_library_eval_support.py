"""Synthetic manifest, capture, judgment and scoring builders shared by the Library evaluation tests."""

from __future__ import annotations

from app.services.knowledge.eval.library_inputs import canonical_sha256
from app.services.knowledge.eval.library_records import capture_record
from app.services.knowledge.eval.library_scoring import score_documents

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


OWN, LIB, FOREIGN = "ws-own", "ws-lib", "ws-foreign"


COMPLETE = {"lexical": "ok", "vector": "ok", "rerank": "ok"}


def manifest_doc(*cases, **overrides) -> dict:
    doc = {
        "schema": "octryx.library_eval.manifest/v1",
        "manifest_id": "synthetic",
        "frozen_at": "2026-10-05T09:00:00+00:00",
        "issue": "#1",
        "principal": {"label": "member-synthetic", "expected_role": "member"},
        "environment_declared": {"space": "synthetic"},
        "workspaces": {"P": {"id": OWN}},
        "workspace_name_map": {OWN: "Own", LIB: "Library", FOREIGN: "Foreign"},
        "budget": {"max_search_requests": 8, "max_result_limit": 10, "max_logical_provider_ops": 96,
                   "max_source_reads": 0, "timeout_s": 30, "concurrency": 1},
        "cases": list(cases),
    }
    doc.update(overrides)
    return doc


def case(case_id="C1", *, kind="answer", split="exploration", mode="hybrid", facts=None, excluded=None, query=None):
    if facts is None and kind == "answer":
        facts = [{"id": "F1", "required": True, "evidence": [{"evidence_key": "rev1:1"}]}]
    return {"id": case_id, "split": split, "kind": kind, "workspace": "P", "mode": mode,
            "query": query or f"synthetic question {case_id}", "limit": 10, "products": None, "version": None,
            "facts": facts or [], "excluded": excluded or []}


def api_hit(key, *, source="src-a", sha=SHA_A, ordinal=None, workspace="Own", bound=False, text="evidence text"):
    ordinal = int(key.split(":")[1]) if ordinal is None else ordinal
    return {"evidence_key": key, "text": text, "citation": {}, "source_id": source, "revision_id": key.split(":")[0],
            "revision": 1, "span_ordinal": ordinal, "chars": [0, 10], "content_sha256": sha,
            "source_title": "Synthetic title", "source_url": None, "products": [], "version": None,
            "found_by": ["lexical", "vector"], "similarity": 0.5, "relevance": 0.4,
            "workspace": workspace, "bound": bound}


def body(hits, *, mode_states=None, workspace_states=None):
    states = dict(COMPLETE) if mode_states is None else mode_states
    return {"workspace_id": OWN, "limit": 10, "mode_states": states,
            "workspace_states": {"Own": states} if workspace_states is None else workspace_states, "evidence": hits}


def capture_doc(manifest, records, *, started_at="2026-10-05T10:00:00+00:00") -> dict:
    return {"schema": "octryx.library_eval.capture/v1", "manifest_sha256": manifest.sha256,
            "started_at": started_at, "finished_at": "2026-10-05T10:05:00+00:00",
            "declarations": {"principal": {}, "environment": {}, "verified": False}, "budget": manifest.budget,
            "requests_used": len(records), "cases": records}


def record(manifest, case_id, response=None, *, status=200):
    item = next(c for c in manifest.cases if c.id == case_id)
    return capture_record(item, manifest.workspaces[item.workspace], status=status, body=response, latency_ms=12.0)


def judgments(manifest, capture, hits, judge="codex") -> dict:
    return {"schema": "octryx.library_eval.judgments/v1", "manifest_sha256": manifest.sha256,
            "capture_sha256": canonical_sha256(capture), "judge": judge, "judged_at": "2026-10-05T11:00:00+00:00",
            "hits": hits}


def scored(manifest, records, judged=None, inventory=None, **capture_kwargs):
    document = capture_doc(manifest, records, **capture_kwargs)
    report = score_documents(manifest, document, judgments(manifest, document, judged) if judged else None, inventory)
    return report


def only_case(report):
    assert report["status"] == "scored", report.get("problems")
    return report["cases"][0]
