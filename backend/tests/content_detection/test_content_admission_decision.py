"""Content decisions fail closed for named findings, the draft shadow sees draft-only detectors, and alias approvals and sticky session categories reach the Cedar entities."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.content_detection.custom_validation import check_detector_set
from app.services.content_detection.scanner import Segment
from app.services.content_routing.decision import decide_model_content, scan_for
from app.services.policy_engine.draft_shadow import pending_buckets
from app.services.policy_engine.runtime import current_runtime, set_policy_runtime
from app.services.policy_engine.shadow import LegacyDecision
from tests.content_detection.content_admission_support import BLOCK_IBAN, IBAN
from tests.model_gateway.conftest import ALIAS, verified_admission
from tests.policy_engine_support import use_custom_policies

# --- fail closed and the draft shadow -----------------------------------------------------------------------


def _decide(text, *, workspace_id="ws-1"):
    scans = scan_for([Segment(text, "prompt")], workspace_id)
    return decide_model_content(route="seat", alias="claude-sonnet-5", scans=scans, builtin_check=LegacyDecision(True),
                                workspace_id=workspace_id)


def test_content_policy_unavailable_fails_closed_only_for_named_findings():
    runtime = use_custom_policies(BLOCK_IBAN, mode="enforce")
    set_policy_runtime(replace(runtime, custom_invalid=True))
    assert _decide(f"iban {IBAN}").refusal == "content_policy_unavailable"
    assert _decide("mail someone@example.org").refusal == ""
    set_policy_runtime(replace(runtime, mode="shadow", custom_invalid=True))
    assert _decide(f"iban {IBAN}").refusal == ""


def test_draft_shadow_sees_draft_only_custom_detectors():
    detectors = check_detector_set({"detectors": [{"id": "custom.case_ref", "label": "Case", "category":
                                                   "confidential_identifier", "pattern": r"\bQX-\d{6}\b"}]})
    draft = ('@id("case-refs")\nforbid (principal, action == Action::"call_model", resource)\n'
             'when { context.content.detected.contains("custom.case_ref") };')
    runtime = use_custom_policies("", mode="shadow")
    set_policy_runtime(replace(runtime, draft_text=draft, draft_ids=frozenset({"case-refs"}), draft_version=2,
                               draft_digest="sha256:draft", draft_detectors=detectors))
    decision = _decide("ticket QX-123456")
    assert decision.refusal == "" and decision.report.detected == frozenset()
    assert decision.comparison.draft_blocking == ("case-refs",)
    assert pending_buckets() == 1
    assert current_runtime().custom_detectors.empty


# --- approved_for and sensitive in the entities ---------------------------------------------------------------


def test_alias_catalog_reads_approved_categories_and_refuses_a_malformed_list():
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from tests.model_gateway.conftest import gateway_config

    config = gateway_config()
    config["litellm_gateway"]["aliases"][ALIAS]["approved_data_categories"] = ["pii", "contracts"]
    assert resolve_alias_admission(ALIAS, config).entry.approved_data_categories == {"pii", "contracts"}
    for bad in (["PII"], "pii", [1], ["x" * 41]):
        config["litellm_gateway"]["aliases"][ALIAS]["approved_data_categories"] = bad
        assert resolve_alias_admission(ALIAS, config).denial_reason == "alias_approved_data_categories_invalid"


@pytest.mark.asyncio
async def test_alias_approvals_snapshot_intersects_providers(db):
    import uuid

    from app.services.policy_engine.runtime import alias_approvals
    from tests.model_gateway.conftest import gateway_config, gateway_provider

    first, second = gateway_config(), gateway_config()
    first["litellm_gateway"]["aliases"][ALIAS]["approved_data_categories"] = ["pii", "secrets"]
    second["litellm_gateway"]["aliases"][ALIAS]["approved_data_categories"] = ["pii"]
    db.add(gateway_provider(name=f"a-{uuid.uuid4().hex[:6]}", config_json=first))
    db.add(gateway_provider(name=f"b-{uuid.uuid4().hex[:6]}", config_json=second))
    db.add(gateway_provider(name=f"c-{uuid.uuid4().hex[:6]}", config_json=first, is_active=False))
    await db.commit()
    assert (await alias_approvals(db))[ALIAS] == frozenset({"pii"})


def test_model_query_carries_the_snapshot_approvals_and_empty_content():
    from app.services.policy_engine.points import model_query

    runtime = use_custom_policies("", mode="shadow")
    set_policy_runtime(replace(runtime, alias_approvals={ALIAS: frozenset({"pii"})}))
    query = model_query(verified_admission(ALIAS), ALIAS)
    alias_record = next(item for item in query.entities if item["uid"]["type"] == "ModelAlias")
    assert alias_record["attrs"]["approved_for"] == ["pii"]
    assert query.requests[0].context["route"] == "governed"
    assert query.requests[0].context["content"]["scanned"] is False


def test_with_sensitive_sets_the_session_categories_only():
    from app.services.policy_engine.entities import principal_entities, with_sensitive

    session, records = principal_entities("u1", session_id="s1", profile="seat", client="c")
    updated = with_sensitive(session, records, ["pii", "pii", "secrets"])
    assert updated[1]["attrs"]["sensitive"] == ["pii", "secrets"] and records[1]["attrs"]["sensitive"] == []
    user, user_records = principal_entities("u1")
    assert with_sensitive(user, user_records, ["pii"]) == user_records


def test_sticky_category_on_the_principal_denies_a_clean_request():
    policy = ('@id("pii-stays")\nforbid (principal, action == Action::"call_model", resource)\n'
              'when { principal is AgentSession && principal.sensitive.contains("pii") };')
    from app.services.policy_engine.entities import principal_entities

    use_custom_policies(policy, mode="enforce")
    scans = scan_for([Segment("hello", "prompt")], "ws-1")
    principal = principal_entities("u1", session_id="s1", profile="seat")
    decided = decide_model_content(route="seat", alias="m", scans=scans, builtin_check=LegacyDecision(True),
                                   workspace_id="ws-1", principal=principal, sensitive=["pii"])
    assert decided.refusal == "content_policy_denied" and decided.policies == ("pii-stays",)
    clean = decide_model_content(route="seat", alias="m", scans=scans, builtin_check=LegacyDecision(True),
                                 workspace_id="ws-1", principal=principal)
    assert clean.refusal == ""


def test_a_governed_question_without_its_admission_is_refused_not_turned_into_seat():
    from app.services.policy_engine.content_points import model_content_query

    with pytest.raises(ValueError):
        model_content_query(route="governed", alias=ALIAS, content={}, workspace_id="ws-1")
    with pytest.raises(ValueError):
        model_content_query(route="other", alias=ALIAS, content={}, workspace_id="ws-1")
