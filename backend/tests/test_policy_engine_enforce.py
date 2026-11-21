"""The guarded switch to enforce, and what enforce mode does at every enforcement point.

Enforce = the existing decision narrowed by Cedar: a Cedar denial of an allowed request becomes the answer
(``cedar_policy_denied`` with the policy ids and the decision-log record); Cedar never widens; when Cedar cannot be
evaluated the existing check decides (fallback); an evaluation that reports errors denies (fail closed).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import PolicyDecisionLog, Project, SystemConfig
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.classification_tool_policy import classification_tool_decision, classification_tool_refusal
from app.services.knowledge.embedding.port import EmbeddingError
from app.services.knowledge.embedding.selection import admit_remote
from app.services.model_gateway.data_policy.classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    WorkspaceDataClassification,
)
from app.services.model_gateway.litellm.project_admission import build_project_model_admission
from app.services.policy_engine.enforce import SHADOW_SINCE_CONFIG_KEY
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from app.services.policy_engine.shadow import (
    EnforcedDenial,
    PolicyComparison,
    custom_fallback_counters,
    enforced_denial,
    reset_shadow_state,
)
from app.services.project import get_project_config
from app.time_utils import utc_now
from tests.policy_engine_support import BASE, bearer, make_user, use_custom_policies

INTERNAL = WorkspaceDataClassification("internal", CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")
EVERYTHING = "\n".join(
    f'@id("no-{action}")\nforbid (principal, action == Action::"{action}", resource);'
    for action in ("use_seat", "call_model", "use_reranker", "read_connector", "write_connector", "call_tool")
)


async def _workspace(db, level: str = "internal", **config) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
                      config={"data_policy": {"classification": level}, **config})
    db.add(project)
    await db.commit()
    return project.id


# ---- the switch -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_needs_a_full_clean_shadow_window(client, db):
    admin = await make_user(db, admin=True)

    async def put(mode: str):
        return await client.put(f"{BASE}/mode", json={"mode": mode}, headers=bearer(admin))

    refused = await put("enforce")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "policy_engine_enforce_not_ready"
    assert "window_not_elapsed" in refused.json()["detail"]["reasons"]
    assert (await put("shadow")).json()["enforce"]["shadow_since"] is not None
    still = await put("enforce")
    assert still.json()["detail"]["reasons"] == ["window_not_elapsed"]

    since = await db.get(SystemConfig, SHADOW_SINCE_CONFIG_KEY)
    since.value = (utc_now() - timedelta(hours=25)).isoformat()
    db.add(PolicyDecisionLog(point="seat", action="use_seat", outcome="mismatch", mode="shadow", principal="User::u",
                             resource="Workspace::w", decision="allow", legacy_decision="deny", determining=[],
                             errors=[], schema_version="x", latency_us=1, created_at=utc_now() - timedelta(hours=2)))
    await db.commit()
    assert (await put("enforce")).json()["detail"]["reasons"] == ["mismatches_in_window"]
    settings = await client.put(f"{BASE}/settings", json={"enforce_window_hours": 1}, headers=bearer(admin))
    assert settings.json() == {"enforce_window_hours": 1, "decision_log_retention_days": 365}
    status = (await client.get(f"{BASE}/status", headers=bearer(admin))).json()["enforce"]
    assert status["ready"] is True and status["window_hours"] == 1
    enforced = await put("enforce")
    assert enforced.status_code == 200 and enforced.json()["mode"] == "enforce"


@pytest.mark.asyncio
async def test_settings_are_validated(client, db):
    admin = await make_user(db, admin=True)
    for body in ({}, {"enforce_window_hours": 0}, {"decision_log_retention_days": 366}, {"bogus": 1},
                 {"enforce_window_hours": "24"}):
        response = await client.put(f"{BASE}/settings", json=body, headers=bearer(admin))
        assert response.status_code == 422 and response.json()["detail"]["code"] == "policy_engine_setting_invalid"


# ---- the decision rule ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("legacy", "comparison", "expected"), [
    (True, None, None),
    (True, PolicyComparison("custom_policy", False, ("p",), mode="shadow", record_id="r"), None),
    (True, PolicyComparison("custom_policy", False, ("p",), mode="enforce", record_id="r"), EnforcedDenial(("p",), "r")),
    (True, PolicyComparison("error", False, (), ("bad",), mode="enforce", record_id="r"), EnforcedDenial((), "r")),
    (True, PolicyComparison("error", None, (), ("RuntimeError",), mode="enforce"), None),
    (False, PolicyComparison("mismatch", True, ("platform:x",), mode="enforce", record_id="r"), None),
    (True, PolicyComparison("match", True, ("platform:x",), mode="enforce"), None),
])
def test_enforce_narrows_never_widens_falls_back_when_unavailable_and_fails_closed_on_errors(legacy, comparison,
                                                                                               expected):
    assert enforced_denial(legacy, comparison) == expected


# ---- every enforcement point ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_mode_denies_at_every_point_with_the_policy_id(db, monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", "bedrock_titan2_1024_v1")
    workspace = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    use_custom_policies(EVERYTHING, mode="enforce")

    seat = await workspace_seat_decision(db, workspace)
    assert (seat.allowed, seat.reason) == (False, "cedar_policy_denied")
    admission = build_project_model_admission(project_id=workspace, project_config={"model_policy": {
        "allowed_aliases": ["octryx-a"]}}, source="test", data_classification=INTERNAL)
    model = admission.decide("octryx-a")
    assert (model.allowed, model.reason) == (False, "cedar_policy_denied")
    with pytest.raises(EmbeddingError) as refused:
        await admit_remote(db, project_id=workspace, data_policy_class="internal", model_kind="reranker")
    assert refused.value.reason == "cedar_policy_denied"
    config = await get_project_config(workspace, db)
    listing = classification_tool_decision("get_pod_logs", config)
    assert (listing.allowed, listing.reason, listing.policy_ids) == (False, "cedar_policy_denied", ("no-read_connector",))
    refusal = classification_tool_refusal("run_kubectl", config, {"args": "apply -f x"})
    assert refusal["reason"] == "cedar_policy_denied"
    assert refusal["policy_decision"]["policy_ids"] == ["no-write_connector"]
    assert refusal["policy_decision"]["decision_id"] and "no-write_connector" in refusal["error"]
    reset_shadow_state()


@pytest.mark.asyncio
async def test_enforce_mode_keeps_legacy_denials_and_allows_what_both_allow(db):
    workspace = await _workspace(db, "confidential", agent_gateway_policy={"seat_mode": "allowed"})
    use_custom_policies('@id("only-tools")\nforbid (principal, action == Action::"call_tool", resource);', mode="enforce")
    seat = await workspace_seat_decision(db, workspace)
    assert seat.reason == "seat_classification_too_sensitive"  # the existing reason, not Cedar's
    config = await get_project_config(workspace, db)
    assert classification_tool_decision("get_pod_logs", config).allowed  # nothing forbids a connector read
    reset_shadow_state()


@pytest.mark.asyncio
async def test_enforce_mode_falls_back_when_cedar_is_unavailable_or_the_published_set_no_longer_parses(db, monkeypatch):
    workspace = await _workspace(db)
    config = await get_project_config(workspace, db)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("engine down")

    use_custom_policies(EVERYTHING, mode="enforce")
    with monkeypatch.context() as patched:
        patched.setattr("app.services.policy_engine.shadow.evaluate", unavailable)
        assert classification_tool_decision("list_jira_issues", config).allowed  # the existing check decides
    # Delivery 3 (#5): an unparseable published set no longer denies everything; its policies fall back to shadow.
    set_policy_runtime(PolicyRuntime(mode="enforce", custom_text="x", custom_digest="sha256:x", custom_version=9,
                                     custom_invalid=True, loaded_at=1e18))
    allowed = classification_tool_decision("list_jira_issues", config)
    assert (allowed.allowed, allowed.policy_ids) == (True, ())
    assert custom_fallback_counters() == {"tool_admission": 1}
    reset_shadow_state()
