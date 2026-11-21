"""Tool results through receive_tool_result: platform, Octryx MCP, coding-agent client."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.models import PolicyDecisionLog
from app.services.content_detection.examination import RequestBudget
from app.services.content_routing.tool_results import check_tool_result
from app.services.policy_engine.decision_log import flush_decision_log
from app.tools.context import ToolContext
from app.tools.result_content import content_checked, mcp_result_checked
from tests.agent_gateway.test_tool_execution_evidence import _post_tool_use
from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE
from tests.policy_engine_support import use_custom_policies
from tests.test_agent_gateway_control_plane import BASE, _gateway, _workspace

PHONE = "+49 30 1234567"
MASKED_PHONE = "[PHONE *******4567 #1]"
MASK_RESULTS_ID = "mask-personal-data-in-tool-results"
MASK_RESULTS = ('@id("' + MASK_RESULTS_ID + '")\n@obligation("mask")\n@mask("email,phone")\n'
                '@mask_style("last4")\nforbid (principal, action == Action::"receive_tool_result", resource)\n'
                'when { context.content.detected.containsAny(["email", "phone"]) };')
BLOCK_CLIENT = ('@id("no-personal-data-from-client-tools")\n'
                'forbid (principal, action == Action::"receive_tool_result", resource)\n'
                'when { context.origin == "client" && context.content.categories.contains("pii") };')


def _context(session_id: str = "") -> ToolContext:
    return ToolContext(user_id="u1", project_ids=["ws-1"], roles=[], session_id=session_id,
                       project_config={"project_id": "ws-1"})


async def _records(db):
    await flush_decision_log(db)
    await db.commit()
    return list((await db.execute(select(PolicyDecisionLog))).scalars())


@pytest.mark.asyncio
async def test_platform_tool_result_masked_in_enforce_unchanged_in_shadow(client, db):
    result = {"logs": [f"caller {PHONE} declined", "ok"], "count": 2}
    use_custom_policies(MASK_RESULTS, mode="shadow")
    assert await content_checked("get_pod_logs", result, _context()) == result
    [shadow] = await _records(db)  # one record per release: what the policy would have done
    assert shadow.gate == "content_security" and shadow.obligation["released"] == "unchanged"
    assert shadow.obligation["cedar"]["would"] == "deny" and shadow.obligation["cedar"]["obligation"] == "mask"
    use_custom_policies(MASK_RESULTS, mode="enforce")
    masked = await content_checked("get_pod_logs", result, _context())
    assert masked["logs"][0] == f"caller {MASKED_PHONE} declined" and masked["count"] == 2
    assert masked["content_policy"]["found"] == {"phone": 1} and masked["content_policy"]["masked"] == 1
    assert result["logs"][0].endswith("declined") and PHONE in result["logs"][0]  # the input is not changed
    assert PHONE not in json.dumps([row.content for row in await _records(db)])


@pytest.mark.asyncio
async def test_a_plain_block_replaces_the_result_and_mcp_origin_is_explicit(client, db):
    block = ('@id("no-phones-from-mcp")\nforbid (principal, action == Action::"receive_tool_result", resource)\n'
             'when { context.origin == "mcp" && context.content.detected.contains("phone") };')
    use_custom_policies(block, mode="enforce")
    result = {"content": [{"type": "text", "text": f"tel {PHONE}"}]}
    blocked = await content_checked("mcp__logs__tail", result, _context())
    assert blocked["error_category"] == "policy_denied" and PHONE not in json.dumps(blocked)
    assert blocked["content_policy"]["policies"] == ["no-phones-from-mcp"]
    assert await content_checked("get_pod_logs", result, _context()) == result  # origin connector: not this policy
    assert (await mcp_result_checked("knowledge_search", result, "ws-1"))["error_category"] == "policy_denied"
    assert await mcp_result_checked("knowledge_search", result, {"error": "x"}) == result


@pytest.mark.asyncio
async def test_a_masked_result_that_is_still_denied_is_blocked(client, db):
    insufficient = MASK_RESULTS.replace('when { context.content.detected.containsAny(["email", "phone"]) }',
                                        'when { context.workspace == Workspace::"ws-1" }')
    use_custom_policies(insufficient, mode="enforce")
    outcome = await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id=None, conversation="chat")
    assert outcome.blocked and outcome.reason == "content_obligation_insufficient"


def test_registry_runs_the_content_check_last(monkeypatch):
    import asyncio

    from app.tools import registry

    async def no_checks(*_args):
        return None

    async def dispatched(*_args):
        return {"value": 1}

    async def checked(tool_name, result, context):
        return {**result, "checked": tool_name}

    monkeypatch.setattr(registry, "_run_governed_tool_checks", no_checks)
    monkeypatch.setattr(registry, "_dispatch_registered_tool", dispatched)
    monkeypatch.setattr(registry, "content_checked", checked)
    assert asyncio.run(registry.execute_tool("t", {}, _context())) == {"value": 1, "checked": "t"}

    async def inner(*_args):
        return {"value": 2}

    monkeypatch.setattr(registry, "_execute_tool_with_plugins", inner)
    assert asyncio.run(registry.execute_tool_with_plugins("p", {}, _context())) == {"value": 2, "checked": "p"}


# --- the coding-agent client --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launcher_report_answers_with_counts_and_the_masked_mcp_output(client, db):
    headers, _session = await _gateway(db, await _workspace(db))
    use_custom_policies(MASK_RESULTS, mode="enforce")
    report = {**_post_tool_use("PostToolUse", f"toolu_{uuid.uuid4().hex[:12]}"), "tool_name": "mcp__logs__tail",
              "tool_response": [{"type": "text", "text": f"caller {PHONE} failed"}]}
    response = await client.post(f"{BASE}/sessions/tool-executed", headers=headers, json=report)
    assert response.status_code == 200, response.text
    content = response.json()["content"]
    assert content["found"] == {"phone": 1} and content["notice"] == "phone ×1 masked by Octryx"
    assert content["updated_output"] == [{"type": "text", "text": f"caller {MASKED_PHONE} failed"}]
    bash = {**report, "tool_name": "Bash", "tool_response": {"stdout": f"caller {PHONE}"},
            "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}"}
    bash_answer = (await client.post(f"{BASE}/sessions/tool-executed", headers=headers, json=bash)).json()["content"]
    assert "updated_output" not in bash_answer and bash_answer["masked"] == 1
    clean = {**bash, "tool_response": {"stdout": "3 passed"}, "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}"}
    assert "content" not in (await client.post(f"{BASE}/sessions/tool-executed", headers=headers,
                                               json=clean)).json()
    records = {row.resource: row for row in await _records(db)}
    assert set(records) == {"tool client:mcp__logs__tail", "tool client:Bash"}, "one record per release, none clean"
    assert records["tool client:mcp__logs__tail"].obligation["released"] == "masked"
    assert records["tool client:Bash"].obligation["released"] == "kept_by_client", "the client keeps its output"


def _history_body(tool_output: str) -> dict:
    return {"model": "alias", "max_tokens": 64, "stream": True,
            "tools": [{"name": "Bash", "description": "Run", "input_schema": {"type": "object"}}],
            "messages": [
                {"role": "user", "content": "check the logs"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_h1", "name": "Bash",
                                                   "input": {"command": "kubectl logs pod"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_h1",
                                              "content": tool_output}]},
                {"role": "assistant", "content": "Found it."},
                {"role": "user", "content": "summarize"}]}


ASSIGNMENT = "password=Hunter2024x"  # a credential assignment: a gateway kind (reported by default)
MASK_ASSIGNMENTS = MASK_RESULTS.replace('["email", "phone"]', '["credential_assignment"]')


@pytest.mark.asyncio
async def test_the_gateway_refuses_client_tool_results_a_policy_denies(client, db, gateway_setup):
    """The gateway changes nothing: a mask obligation on a client tool's (re-sent) results refuses the request
    (``content_handling_gateway_refused``), shadow sends unchanged. C12F-08: a platform-only kind (a phone number) in
    the same results reaches no gateway policy question or record: the request is forwarded."""
    from tests.model_gateway.conftest import ALIAS
    fake, build = gateway_setup
    headers = await build()
    use_custom_policies(MASK_ASSIGNMENTS, mode="enforce")
    body = {**_history_body(f"login {ASSIGNMENT} failed"), "model": ALIAS}
    masked = await client.post(ROUTE, json=body, headers=headers)
    assert masked.status_code == 403 and masked.headers["x-octryx-gateway-reason"] == "content_handling_gateway_refused"
    assert MASK_RESULTS_ID in masked.json()["error"]["message"] and fake.requests == []
    use_custom_policies(MASK_RESULTS + "\n" + BLOCK_CLIENT, mode="enforce")
    phone = {**_history_body(f"caller {PHONE} failed"), "model": ALIAS}
    assert (await client.post(ROUTE, json=phone, headers=headers)).status_code == 200
    assert PHONE in fake.requests[0].content.decode()
    use_custom_policies(MASK_ASSIGNMENTS, mode="shadow")
    assert (await client.post(ROUTE, json=body, headers=headers)).status_code == 200
    assert "Hunter2024x" in fake.requests[1].content.decode()  # shadow: unchanged
    await flush_decision_log(db)
    await db.commit()
    rows = [row for row in (await db.execute(select(PolicyDecisionLog))).scalars() if row.resource.startswith("gateway ")]
    assert "phone" not in str([(row.content, row.obligation) for row in rows]), "platform-only kinds stay out"
    tool_rows = [row for row in rows if row.obligation and row.obligation.get("cedar", {}).get("tool") == "Bash"]
    assert [row.rule for row in tool_rows] == [MASK_RESULTS_ID]


@pytest.mark.asyncio
async def test_too_many_strings_make_the_scan_incomplete(client, db, monkeypatch):
    from app.services.content_routing import tool_results

    monkeypatch.setattr(tool_results, "MAX_STRINGS", 3)
    incomplete = ('@id("incomplete-results")\nforbid (principal, action == Action::"receive_tool_result", resource)\n'
                  'when { context.content.scanned && !context.content.complete };')
    use_custom_policies(incomplete, mode="enforce")
    outcome = await check_tool_result(["a", "b", "c", "d"], tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id=None, conversation="chat")
    assert outcome.blocked
    small = await check_tool_result(["a"], tool_name="t", family=None, origin="connector", workspace_id="ws-1",
                                    session_id=None, conversation="chat")
    assert not small.blocked


@pytest.mark.asyncio
async def test_a_route_obligation_never_applies_to_a_tool_result(client, db):
    from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime

    text = MASK_RESULTS.replace('@obligation("mask")', '@obligation("mask_reroute")\n@reroute_to("m")')
    set_policy_runtime(PolicyRuntime(mode="enforce", custom_text=text,
                                     custom_ids=frozenset({MASK_RESULTS_ID}), custom_version=1,
                                     custom_digest="sha256:x", loaded_at=1e18))
    outcome = await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id=None, conversation="chat")
    assert outcome.blocked and outcome.reason == "content_policy_denied"


@pytest.mark.asyncio
async def test_the_gateway_policy_check_groups_by_the_tool_that_produced_the_result(client, db, gateway_setup):
    from tests.model_gateway.conftest import ALIAS
    fake, build = gateway_setup
    headers = await build()
    only_bash = MASK_RESULTS.replace('forbid (principal, action == Action::"receive_tool_result", resource)',
                                     'forbid (principal, action == Action::"receive_tool_result", '
                                     'resource == Tool::"client:Bash")')
    use_custom_policies(only_bash.replace('["email", "phone"]', '["credential_assignment"]'), mode="enforce")
    body = {**_history_body(f"login {ASSIGNMENT} failed"), "model": ALIAS}
    assert (await client.post(ROUTE, json=body, headers=headers)).status_code == 403
    assert fake.requests == []
    other = json.loads(json.dumps(body).replace('"name": "Bash"', '"name": "Read"'))
    assert (await client.post(ROUTE, json=other, headers=headers)).status_code == 200
    assert "Hunter2024x" in fake.requests[0].content.decode()


def test_the_gateway_policy_check_fails_closed_when_the_policy_set_cannot_be_evaluated(monkeypatch):
    from app.services.content_routing import client_tool_results
    from app.services.content_routing.gateway import scan_request
    from app.services.policy_engine.engine import PolicySetInvalidError

    def broken(_text):
        raise PolicySetInvalidError("synthetic")

    use_custom_policies(MASK_ASSIGNMENTS, mode="enforce")
    monkeypatch.setattr(client_tool_results, "compile_policy_set", broken)

    def denial(output: str):
        results = scan_request(_history_body(output), "ws-1", RequestBudget()).tool_results
        return client_tool_results.client_tool_result_denial(results, workspace_id="ws-1", principal=None)

    found = denial(f"login {ASSIGNMENT} failed")
    assert found is not None and (found.tool, found.reason) == ("Bash", "content_policy_unavailable")
    assert denial("3 passed") is None
    assert denial(f"caller {PHONE} failed") is None, "C12F-08: a platform-only kind is not a gateway finding"


@pytest.mark.asyncio
async def test_launcher_report_is_decided_for_the_session_principal(client, db, monkeypatch):
    from app.api.routes import agent_gateway

    seen = {}

    async def spy(_hook_input, **kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(agent_gateway, "launcher_tool_result", spy)
    headers, _session = await _gateway(db, await _workspace(db))
    report = {**_post_tool_use("PostToolUse", f"toolu_{uuid.uuid4().hex[:12]}"), "tool_name": "Read",
              "tool_response": {"content": "synthetic"}}
    assert (await client.post(f"{BASE}/sessions/tool-executed", headers=headers, json=report)).status_code == 200
    assert seen["principal"][0].type == "AgentSession" and seen["principal"][0].id == seen["session_id"]


@pytest.mark.asyncio
async def test_a_tool_result_release_has_one_record_written_after_its_final_disposition(client, db, monkeypatch):
    """I-4 / C12C-07: the content handling's report and the Workspace policy's mask are one record, written once the
    result is released masked; a refused result has one denied record; Cedar writes none of its own."""
    from app.services.content_routing import tool_result_handling, tool_results
    from app.services.content_security.handling import plan_for
    from app.services.policy_engine import shadow

    written: list[dict] = []
    monkeypatch.setattr(tool_result_handling, "record_decision", written.append)
    monkeypatch.setattr(shadow, "record_decision", written.append)
    for action, policy in (("report", MASK_RESULTS), ("refuse", MASK_RESULTS)):
        written.clear()

        async def plan(_scope, surface, action=action):
            return plan_for({"phone": action}, surface)

        monkeypatch.setattr(tool_results, "content_handling_isolated", plan)
        use_custom_policies(policy, mode="enforce")
        outcome = await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                          workspace_id="ws-1", session_id=None, conversation="chat")
        (entry,) = written
        if action == "report":
            assert not outcome.blocked and MASKED_PHONE in json.dumps(outcome.result)
            # C12D-06: the policy's mask replaced the reported value, so the record says mask, never report
            assert entry["obligation"]["released"] == "masked" and entry["obligation"]["applied"] == {"phone": "mask"}
            assert entry["obligation"]["cedar"]["masked"] == 1 and outcome.notice["decision_id"] == entry["id"]
        else:
            assert outcome.blocked and entry["obligation"]["released"] == "blocked"
            assert outcome.notice["decision_id"] == entry["id"]


@pytest.mark.asyncio
async def test_every_release_writes_its_one_record_in_the_finally_and_counts_the_badge_after_it(monkeypatch):
    """C12C-07: clean → no record; unfinished, unavailable, a failing check → one record of what was (not) released;
    the badge counts only what entered the context, after the release (a blocked result adds nothing)."""
    from app.services.content_routing import tool_result_handling, tool_results
    from app.services.content_security.handling import ContentHandlingUnavailableError, plan_for

    written: list[dict] = []
    badges: list[dict] = []
    monkeypatch.setattr(tool_result_handling, "record_decision", written.append)

    async def badge(_session, _conversation, report, **_kwargs):
        badges.append(report.counts())

    monkeypatch.setattr(tool_results, "remember", badge)

    async def check(result):
        written.clear()
        badges.clear()
        return await check_tool_result(result, tool_name="t", family=None, origin="connector",
                                       workspace_id="ws-1", session_id="s", conversation="chat")

    async def plan(_scope, surface):
        return plan_for({}, surface)

    monkeypatch.setattr(tool_results, "content_handling_isolated", plan)
    use_custom_policies(MASK_RESULTS, mode="enforce")
    assert not (await check({"text": "3 passed"})).blocked and written == [] and badges == [{}]
    masked = await check({"text": f"tel {PHONE}"})
    (entry,) = written
    assert entry["obligation"]["released"] == "masked" and badges == [{}], "the masked result carries no phone"
    assert masked.notice["decision_id"] == entry["id"]

    async def unavailable(_scope, _surface):
        raise ContentHandlingUnavailableError("ws-1")

    monkeypatch.setattr(tool_results, "content_handling_isolated", unavailable)
    blocked = await check({"text": f"tel {PHONE}"})
    (entry,) = written
    assert blocked.blocked and (entry["obligation"]["released"], entry["reason"]) == (
        "blocked", "content_handling_unavailable")
    assert badges == [], "a blocked result enters no context"

    monkeypatch.setattr(tool_results, "content_handling_isolated", plan)

    def broken(*_args, **_kwargs):
        raise RuntimeError("the masking pass failed")

    monkeypatch.setattr(tool_results, "_masked", broken)
    with pytest.raises(RuntimeError):
        await check({"text": f"tel {PHONE}"})
    assert written == [] and badges == [], "C12F-05: a check failing before its return writes and counts nothing"


@pytest.mark.asyncio
async def test_a_tool_result_check_cancelled_before_its_return_writes_nothing(monkeypatch):
    """C12F-05: the record is written once the result is decided and the badge counted after it; a check cancelled
    while it is still deciding writes nothing and counts nothing."""
    from app.services.content_routing import tool_result_handling, tool_results
    from app.services.content_security.handling import plan_for

    order: list[str] = []
    monkeypatch.setattr(tool_result_handling, "record_decision", lambda entry: order.append("record"))

    async def badge(*_args, **_kwargs):
        order.append("badge")

    monkeypatch.setattr(tool_results, "remember", badge)

    async def plan(_scope, surface):
        return plan_for({"phone": "report"}, surface)

    monkeypatch.setattr(tool_results, "content_handling_isolated", plan)
    use_custom_policies(MASK_RESULTS, mode="shadow")
    outcome = await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id="s", conversation="chat")
    assert order == ["record", "badge"] and not outcome.blocked, "the badge is counted after the record"

    order.clear()

    async def cancelled(_scope, _surface):
        raise asyncio.CancelledError

    monkeypatch.setattr(tool_results, "content_handling_isolated", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                workspace_id="ws-1", session_id="s", conversation="chat")
    assert order == []


def test_a_tool_result_record_states_each_kind_as_the_released_result_carries_it(monkeypatch):
    """C12E-05: per kind from the released result — a report only for a kind it carries, a mask only for a kind found
    and absent from it; a policy's staged part only for a released result; nothing claimed when nothing was released;
    the fixed record for an unfinished examination."""
    from app.services.content_routing import tool_result_handling as handling
    from app.services.content_security.handling import SURFACE_PLATFORM, plan_for

    recorded: list[dict] = []
    monkeypatch.setattr(handling, "record_decision", recorded.append)
    plan = plan_for({"email": "report", "phone": "report"}, SURFACE_PLATFORM)
    cedar = {"policies": [MASK_RESULTS_ID], "decision": "deny", "mask": ["email", "phone"], "masked": 1}

    def written(released: str, present: frozenset[str], reason: str = "") -> dict:
        item = handling.handle_tool_result(plan, {"email", "phone"}, tool_name="fetch", workspace_id="ws-1",
                                           session_id=None, principal="u", counts={"email": 1, "phone": 1})
        item.release(released, reason, cedar=dict(cedar), present=present)
        item.write()
        return recorded[-1]

    masked = written(handling.RELEASED_MASKED, frozenset({"phone"}))["obligation"]
    assert masked["applied"] == {"email": "mask", "phone": "report"} and masked["cedar"]["masked"] == 1
    kept = written(handling.RELEASED_KEPT_BY_CLIENT, frozenset({"email", "phone"}))["obligation"]
    assert kept["applied"] == {"email": "report", "phone": "report"} and "cedar" not in kept
    blocked = written(handling.RELEASED_BLOCKED, frozenset())["obligation"]
    assert set(blocked["applied"].values()) == {"refuse"} and "cedar" not in blocked
    assert masked["informational"] == ["phone"], "C12F-05: informational follows the applied actions"
    unfinished = written(handling.RELEASED_BLOCKED, frozenset(), "content_scan_unfinished")
    assert "applied" not in unfinished["obligation"] and "cedar" not in unfinished["obligation"]
    assert unfinished["content"] == {}
