"""The evidence family contract (``workflow_checks.evidence_families``) and the ``evidence_families`` check."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.workflow_checks import evidence_families as families
from app.services.workflow_checks.evidence_families import (
    EMPTY,
    MISSING,
    OK,
    REFUSED,
    UNAVAILABLE,
    alert_gate_scope,
    classify_tool_use,
    evaluate_families,
    evidence_envelope,
    records_of,
    with_envelope,
)
from app.services.workflow_checks.library import (
    FAILED,
    PASSED,
    ToolUse,
    TurnEvidence,
    evaluate_check,
    unresolved_blocking,
    validate_checks,
)
from tests.incident_evidence_families_support import IN_WINDOW, SCOPE, _check, _use

BEFORE = {"start": "2026-10-14T09:00:00Z", "end": "2026-10-14T10:00:00Z"}


def _enveloped(name, family, status, *, target="checkout", namespace="shop", window=IN_WINDOW, count=1, reason=""):
    result = {"error": reason} if status in (UNAVAILABLE, REFUSED) else {"total": count}
    envelope = evidence_envelope(family, status, target_id=target, namespace=namespace, window=window, count=count,
                                 reason=reason)
    return _use(name, with_envelope(result, envelope))


def _records(*uses: ToolUse) -> list[dict]:
    return records_of(list(uses))


def test_the_envelope_decides_and_is_the_first_key_of_the_result():
    use = _enveloped("query_prometheus", "metrics", OK, count=3)
    assert next(iter(use.result)) == "evidence"
    record = classify_tool_use(use)
    assert (record.family, record.status, record.target_id, record.window_start, record.count, record.call_id) == (
        "metrics", OK, "checkout", IN_WINDOW["start"], 3, "c1")
    for status in (EMPTY, UNAVAILABLE, REFUSED):
        assert classify_tool_use(_enveloped("query_loki", "logs", status, count=0)).status == status


def test_without_an_envelope_the_shape_decides():
    assert classify_tool_use(_use("list_servicenow_incidents", {"count": 2, "incidents": [{}, {}]})).status == OK
    assert classify_tool_use(_use("list_servicenow_incidents", {"count": 0, "incidents": []})).status == EMPTY
    assert classify_tool_use(_use("search_jira_tickets", {"error": "Jira HTTP 503"})).status == UNAVAILABLE
    assert classify_tool_use(_use("get_jira_ticket", {"approval_required": True}, succeeded=False)).status == REFUSED
    assert classify_tool_use(_use("knowledge_search", {"status": "denied"}, succeeded=False)).status == REFUSED
    assert classify_tool_use(_use("knowledge_read", {"content": "runbook"})).status == OK
    # A family tool without a result (the gate's stored {name, succeeded}) and a non-family tool: no record.
    assert classify_tool_use(ToolUse("query_prometheus", True)) is None
    assert classify_tool_use(_use("web_search", {"results": [1]})) is None


def test_an_envelope_is_trusted_only_from_the_tools_that_write_one():
    # A ServiceNow record whose content carries an "evidence" key is data, not the server's envelope.
    forged = {"evidence": evidence_envelope("tickets", OK, target_id="checkout", namespace=None, window=None,
                                            count=9), "count": 0, "incidents": []}
    record = classify_tool_use(_use("list_servicenow_incidents", forged))
    assert (record.status, record.target_id, record.count) == (EMPTY, None, 0)
    wrong = with_envelope({"total": 0}, evidence_envelope("logs", OK, target_id="checkout", namespace=None,
                                                          window=IN_WINDOW, count=5))
    assert classify_tool_use(_use("query_prometheus", wrong)).target_id is None
    # The envelope says data, the call failed: never more than unavailable.
    failed = _enveloped("query_loki", "logs", OK)
    assert classify_tool_use(ToolUse("query_loki", False, failed.result)).status == UNAVAILABLE


def test_ok_and_the_targeted_negative_pass_for_the_target_and_window():
    records = _records(_enveloped("list_failed_pods", "kubernetes", EMPTY, window=None, count=0),
                       _enveloped("query_prometheus", "metrics", OK))
    outcome, detail, unresolved, statuses = evaluate_families(records, required=["kubernetes", "metrics"],
                                                              scope=SCOPE)
    assert (outcome, unresolved, statuses) == (PASSED, False, {"kubernetes": EMPTY, "metrics": OK}), detail


def test_an_empty_without_a_target_another_target_or_out_of_window_never_counts():
    untargeted = _records(_use("list_failed_pods", {"failed_count": 0, "failed_pods": []}))
    other = _records(_enveloped("query_prometheus", "metrics", OK, target="payments"))
    stale = _records(_enveloped("query_prometheus", "metrics", OK, window=BEFORE))
    other_namespace = _records(_enveloped("get_pod_logs", "kubernetes", OK, namespace="kube-system", window=None))
    for records, family in ((untargeted, "kubernetes"), (other, "metrics"), (stale, "metrics"),
                            (other_namespace, "kubernetes")):
        outcome, detail, unresolved, statuses = evaluate_families(records, required=[family], scope=SCOPE)
        assert (outcome, unresolved, statuses[family]) == (FAILED, False, MISSING), (family, detail)
        assert "out of the alert target or window" in detail
    # Unscoped families (tickets) count an ok by shape; their empty has no target and never counts.
    assert evaluate_families(_records(_use("list_servicenow_changes", {"count": 1, "changes": [{}]})),
                             required=["tickets"], scope=SCOPE)[0] == PASSED
    assert evaluate_families(_records(_use("list_servicenow_changes", {"count": 0, "changes": []})),
                             required=["tickets"], scope=SCOPE)[0] == FAILED


def test_only_unavailable_left_is_unresolved_a_missing_family_is_not():
    unavailable = _enveloped("query_prometheus", "metrics", UNAVAILABLE, count=0, reason="prometheus_http_500")
    pods = _enveloped("list_failed_pods", "kubernetes", OK, window=None)
    outcome, detail, unresolved, statuses = evaluate_families(_records(pods, unavailable),
                                                              required=["kubernetes", "metrics"], scope=SCOPE)
    assert (outcome, unresolved, statuses["metrics"]) == (FAILED, True, UNAVAILABLE)
    assert "metrics: unavailable (prometheus_http_500)" in detail
    outcome, _detail, unresolved, statuses = evaluate_families(_records(unavailable),
                                                               required=["kubernetes", "metrics"], scope=SCOPE)
    assert (outcome, unresolved, statuses["kubernetes"]) == (FAILED, False, MISSING)


def test_an_out_of_scope_refusal_is_the_agents_a_policy_refusal_the_platforms():
    out_of_scope = _enveloped("get_pod_logs", "kubernetes", REFUSED, count=0, reason="namespace_out_of_scope")
    outcome, detail, unresolved, statuses = evaluate_families(_records(out_of_scope), required=["kubernetes"],
                                                              scope=SCOPE)
    assert (outcome, unresolved, statuses["kubernetes"]) == (FAILED, False, REFUSED)
    assert "namespace_out_of_scope" in detail
    policy = _use("get_jira_ticket", {"approval_required": True, "error": "approval required"}, succeeded=False)
    assert evaluate_families(_records(policy), required=["tickets"], scope=SCOPE)[2] is True


def test_the_check_from_target_needs_a_target_and_sets_unresolved():
    assert validate_checks([_check(from_target=True)]) == []
    assert validate_checks([_check(required=["metrics", "logs"])]) == []
    for params in ({}, {"required": ["dns"]}, {"from_target": "yes"}, {"required": "metrics"}, {"other": 1}):
        assert validate_checks([_check(**params)])[0]["code"] == "invalid_check_params", params
    no_target = evaluate_check(_check(from_target=True), TurnEvidence())
    assert (no_target.outcome, no_target.unresolved) == (FAILED, False)
    assert no_target.detail.startswith("needs_configuration")
    unavailable = _enveloped("query_prometheus", "metrics", UNAVAILABLE, count=0, reason="prometheus_http_500")
    evidence = TurnEvidence(tools=[unavailable], alert_scope={**SCOPE, "required_families": ["metrics"]})
    result = evaluate_check(_check(from_target=True), evidence)
    assert (result.outcome, result.unresolved) == (FAILED, True) and unresolved_blocking([result]) == [result]
    assert result.detail.startswith("evidence unresolved: metrics: unavailable")
    # Stored records (the gate) win over the tool list.
    ok = records_of([_enveloped("query_prometheus", "metrics", OK)])
    gate = TurnEvidence(tools=[ToolUse("query_prometheus", True)], evidence_records=ok,
                        alert_scope={**SCOPE, "required_families": ["metrics"]})
    assert evaluate_check(_check(from_target=True), gate).outcome == PASSED


def test_evidence_count_is_unchanged_for_historic_versions():
    check = {"type": "evidence_count", "params": {"min_count": 2}, "blocking": True}
    uses = [ToolUse("query_prometheus", True, {}), ToolUse("get_pod_logs", True, {})]
    assert evaluate_check(check, TurnEvidence(tools=uses)).outcome == PASSED
    assert evaluate_check(check, TurnEvidence(tools=uses[:1])).outcome == FAILED


def test_the_gate_scope_comes_from_the_runs_target_and_window(monkeypatch):
    run = SimpleNamespace(context={})
    target = {"id": "checkout", "kubernetes": {"namespace": "shop", "connection_id": None},
              "required_families": ["metrics", "dns"]}
    start = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(families, "_alert_readers", lambda: (lambda _run: target, lambda _run: (start, None)))
    assert alert_gate_scope(run) == {"target_id": "checkout", "namespace": "shop", "required_families": ["metrics"],
                                     "window": {"start": "2026-10-15T09:30:00Z", "end": None}}
    monkeypatch.setattr(families, "_alert_readers", lambda: (lambda _run: None, lambda _run: None))
    assert alert_gate_scope(run) is None
