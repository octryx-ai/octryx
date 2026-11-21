"""Web research in a phase a Workspace lists (``device_runs.research_phases``).

A phase whose allowlist has no ``web_search`` / ``web_fetch`` is never offered them, so spec-writing ``draft``
writes SPEC.md "without a live web search". The Workspace switch reaches a running run pinned to its version; the
seed offers them to new runs.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.devices.device_runs_keys import DEFAULTS, DeviceRunsPolicyError, normalize_device_runs
from app.services.workflow_checks.library import validate_checks
from app.services.workflow_runs.octryx.research import RESEARCH_NOTE, with_research
from app.services.workflow_runs.octryx.stop import run_stop
from app.time_utils import utc_now
from tests.research_phases_support import SOURCES, _draft_definition, _list, _patch, _seed
from tests.workflow_run_octryx_support import ROOT, _bound_run, _call

# --- the Workspace keys ---------------------------------------------------------------------------------------------


def test_the_research_keys_default_off_and_are_validated():
    assert (DEFAULTS["research_phases"], DEFAULTS["research_min_sources"]) == ([], 3)
    assert normalize_device_runs({"research_phases": [" spec-writing.draft ", "spec-writing.draft"],
                                  "research_min_sources": 5}, "p") == {
        "research_phases": ["spec-writing.draft"], "research_min_sources": 5}
    for bad in ("spec-writing.draft", ["draft"], ["spec writing.draft"], [""], [7]):
        with pytest.raises(DeviceRunsPolicyError) as refused:
            normalize_device_runs({"research_phases": bad}, "p")
        assert (refused.value.reason, refused.value.path) == ("invalid_research_phases", "p.research_phases")
    for bad in (0, 21, "3", 2.0, True):
        with pytest.raises(DeviceRunsPolicyError) as refused:
            normalize_device_runs({"research_min_sources": bad}, "p")
        assert (refused.value.reason, refused.value.path) == ("invalid_number", "p.research_min_sources")


# --- the definition at runtime --------------------------------------------------------------------------------------


def test_a_listed_phase_gets_the_web_tools_the_note_and_two_blocking_checks_first():
    definition = _draft_definition()["nodes"][1]["config"]
    assert with_research(definition, None) is definition  # unlisted: unchanged
    researched = with_research(definition, 4)
    policy = researched["tool_policy"]
    assert policy["allowlist"] == ["read_workspace_file", "edit_workspace_file", "knowledge_search", "web_search",
                                   "web_fetch"]  # the Workspace's knowledge first
    assert "web_fetch" not in policy["denylist"]  # the Workspace's list wins over the node's deny
    contract = researched["workflow_contract"]
    assert contract["research"] == {"rule": RESEARCH_NOTE, "tools": ["knowledge_search", "web_search", "web_fetch"],
                                    "min_sources": 4}
    assert [(check["type"], check["params"].get("min_count"), check["blocking"]) for check in contract["checks"]] == [
        ("evidence_count", 4, True), ("urls_cited", 4, True), ("tool_called", None, True)]
    assert contract["checks"][0]["params"]["tools"] == ["knowledge_hit", "web_search", "web_fetch"]
    assert validate_checks(contract["checks"]) == []
    assert with_research(researched, 4)["workflow_contract"]["checks"] == contract["checks"]  # never twice
    assert contract["when_to_use"] == "Write SPEC.md."  # the device reads ``research``; a server turn the brief
    assert with_research(definition, 4, brief=True)["workflow_contract"]["when_to_use"].endswith(RESEARCH_NOTE)
    assert definition["tool_policy"]["allowlist"] == ["read_workspace_file", "edit_workspace_file"]  # not mutated


# --- a running device run picks up the switch ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_running_device_run_gets_the_web_tools_note_and_checks_when_its_workspace_lists_the_phase(db):
    from app.services.workflow_runs.octryx.contract import run_contract

    run, gateway, _key, workspace_id = await _bound_run(db, _draft_definition())
    assert run.current_node_id == "draft"
    version = run.workflow_version
    phase = (await run_contract(db, run))["phase"]
    assert "web_search" not in phase["tools"]["allow"] and "research" not in phase  # unlisted: unchanged
    for other in (["spec-writing.draft"], [f"{run.workflow_key}.interview"]):  # another workflow or phase
        await _list(db, workspace_id, other)
        assert "research" not in (await run_contract(db, run))["phase"]
    await _list(db, workspace_id, [f"{run.workflow_key}.draft"], research_min_sources=2)
    contract = await run_contract(db, run, session=gateway)
    phase = contract["phase"]
    assert contract["run"]["workflow_version"] == version  # the pinned version, switched at runtime
    assert {"web_search", "web_fetch"} <= set(phase["tools"]["allow"]) and "web_fetch" not in phase["tools"]["deny"]
    assert {"mcp__octryx-knowledge__web_search", "mcp__octryx-knowledge__web_fetch"} <= set(
        phase["tools"]["on_device"])
    assert phase["research"] == {"rule": RESEARCH_NOTE, "tools": ["knowledge_search", "web_search", "web_fetch"],
                                 "min_sources": 2}
    assert phase["checks"][:2] == ["Researched: at least 2 knowledge_search hits or web_search / web_fetch results",
                                   "The written file cites at least 2 distinct source URLs (a Sources section)"]

    # Stop: the spec without research is blocked with both reasons; the agent must research.
    later = utc_now() + timedelta(seconds=5)
    entry = dict(run.node_state or {}).get("entry")
    wrote = _call(gateway, "Write", at=later, file_path=f"{ROOT}/SPEC.md")

    def facts(lines: list[str]) -> dict:
        return {"hook_event_name": "Stop", "workflow_run_facts": {
            "node_id": "draft", "entry": entry, "change": {"base": "", "patch": _patch("SPEC.md", lines)}}}

    blocked = await run_stop(db, session=gateway, hook_input=facts(["# Spec", "No live web search."]),
                             tool_calls=[wrote], test_prefixes=(("pytest",),))
    assert blocked["state"] == "blocked"
    assert "Researched: at least 2" in blocked["detail"] and "cites at least 2 distinct source URLs" in blocked["detail"]
    assert run.current_node_id == "draft"
    # Recorded on the run like the seed's own checks (the run card shows them with their detail).
    recorded = {item["type"]: item for item in run.gate_results["draft"]["results"]}
    assert (recorded["evidence_count"]["outcome"], recorded["evidence_count"]["detail"]) == (
        "failed", "0 of 2 evidence calls")
    assert (recorded["urls_cited"]["outcome"], recorded["urls_cited"]["detail"]) == (
        "failed", "0 of 2 distinct source URLs cited in SPEC.md")
    searched = [_call(gateway, "mcp__octryx-knowledge__web_search", at=later + timedelta(seconds=1),
                      input={"query": "coffee roasting"},
                      excerpt=f'{{"state": "ok", "results": [{{"url": "{SOURCES[0]}"}}], "count": 1}}'),
                _call(gateway, "mcp__octryx-knowledge__web_fetch", at=later + timedelta(seconds=2),
                      input={"url": SOURCES[0]}, excerpt=f'{{"url": "{SOURCES[0]}", "content": "x"}}')]
    still = await run_stop(db, session=gateway, hook_input=facts(["# Spec", f"- {SOURCES[0]}"]),
                           tool_calls=[*searched, wrote], test_prefixes=(("pytest",),))
    assert still["state"] == "blocked" and "cites at least 2 distinct source URLs" in still["detail"]
    assert "Researched: at least" not in still["detail"]
    passed = await run_stop(db, session=gateway, hook_input=facts(["# Spec", "## Sources", *SOURCES[:2]]),
                            tool_calls=[*searched, wrote], test_prefixes=(("pytest",),))
    assert passed["state"] == "passed"
    assert run.current_node_id != "draft"


@pytest.mark.asyncio
async def test_a_codex_session_sees_the_web_tools_in_its_names_and_its_calls_count_as_evidence(db):
    from app.services.model_gateway.inbound.openai_view import evidence_names
    from app.services.workflow_runs.octryx.contract import run_contract
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence

    run, gateway, _key, workspace_id = await _bound_run(db, _draft_definition())
    from app.services.agent_gateway.engine_keys import ENGINE_CODEX, SESSION_ENGINE_KEY

    await _list(db, workspace_id, [f"{run.workflow_key}.draft"])
    gateway.metadata_ = {**gateway.metadata_, SESSION_ENGINE_KEY: ENGINE_CODEX}
    phase = (await run_contract(db, run, session=gateway))["phase"]
    assert {"mcp__octryx_knowledge__web_search", "mcp__octryx_knowledge__web_fetch"} <= set(
        phase["tools"]["on_device"])
    # Codex shows the server as ``octryx_knowledge``; the gateway records the platform's name.
    name, _input = evidence_names("mcp__octryx_knowledge__web_search", {"query": "x"})
    assert name == "mcp__octryx-knowledge__web_search"
    found = ('{"state": "ok", "reason": "ok", "provider": "tavily", "results": [{"url": "https://coffee.example"}], '
             '"count": 1}')
    rows = [_call(gateway, name, at=utc_now() + timedelta(seconds=index), excerpt=found) for index in range(3)]
    evidence = phase_evidence(rows, since=None, test_prefixes=())
    assert [use.name for use in evidence.tools if use.succeeded] == ["web_search"] * 3


@pytest.mark.asyncio
async def test_a_server_turn_of_a_listed_phase_gets_the_tools_and_the_note_in_its_resolution(db):
    from app.services.workflow_runs.phase_turns import phased_turn_resolution
    from tests.phased_workflow_fixtures import admin_user

    run, _gateway, _key, workspace_id = await _bound_run(db, _draft_definition())
    await _list(db, workspace_id, [f"{run.workflow_key}.draft"])
    resolution = await phased_turn_resolution(db, run, user_message="write it",
                                              user=await admin_user(db))
    assert {"web_search", "web_fetch"} <= set(resolution["tool_policy"]["allowlist"])
    contract = resolution["workflow_contract"]
    assert RESEARCH_NOTE in contract["when_to_use"]
    assert [check["type"] for check in contract["checks"]][:2] == ["evidence_count", "urls_cited"]


# --- the seed -------------------------------------------------------------------------------------------------------


def test_the_spec_draft_seed_offers_the_web_tools_and_asks_for_sources():
    from app.services.workflow_runs.graph_validation import validate_phased_definition

    definition = _seed("spec-writing")
    assert validate_phased_definition(definition)["errors"] == []
    nodes = {node["id"]: node["config"] for node in definition["nodes"] if node.get("config")}
    draft = nodes["draft"]
    assert {"web_search", "web_fetch"} <= set(draft["tool_policy"]["allowlist"])
    # offered, not a must: no check asks for a web tool (the draft's checks are the spec file and the Spec Studio)
    assert not any({"web_search", "web_fetch"} & set(check.get("params", {}).get("tools", []))
                   for check in draft["workflow_contract"]["checks"])
    text = draft["workflow_contract"]["when_to_use"]
    assert "research on the web before writing" in text and '"Sources" section' in text
    assert not {"web_search", "web_fetch"} & set(nodes["interview"]["tool_policy"]["allowlist"])


@pytest.mark.asyncio
async def test_the_device_runs_put_patch_stores_the_research_keys_and_the_get_shows_them(db):
    from app.models import Project
    from app.services.devices.workspace_policy import set_workspace_device_runs, workspace_device_runs
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import admin_user

    workspace_id = await seed_workspace(db)
    project, admin = await db.get(Project, workspace_id), await admin_user(db)
    assert {key: (await workspace_device_runs(db, workspace_id))[key]
            for key in ("research_phases", "research_min_sources")} == {"research_phases": [],
                                                                         "research_min_sources": 3}
    await set_workspace_device_runs(db, project=project, patch={"research_phases": ["spec-writing.draft"]},
                                    actor_id=admin.id)
    await set_workspace_device_runs(db, project=project, patch={"research_min_sources": 4}, actor_id=admin.id)
    section = await workspace_device_runs(db, workspace_id)
    assert (section["research_phases"], section["research_min_sources"]) == (["spec-writing.draft"], 4)  # a patch
    with pytest.raises(DeviceRunsPolicyError):
        await set_workspace_device_runs(db, project=project, patch={"research_min_sources": 50}, actor_id=admin.id)


@pytest.mark.asyncio
async def test_the_offer_of_a_listed_research_phase_carries_web(db):
    """Without an offer the session answers "WebSearch / WebFetch I do not have in this session" while the
    platform's web tools cannot leave a restricted egress. The offer tells the launcher to add Claude Code's
    own web tools to the phase turn."""
    from app.models import DeviceJob
    from app.services.devices.job_offer import offer_body
    from app.services.workflow_runs.octryx.research import research_min_sources
    from app.services.workflow_runs.octryx.subagents import turn_phase

    run, _gateway, _key, workspace_id = await _bound_run(db, _draft_definition())
    phase = await turn_phase(db, run)
    assert not await research_min_sources(db, run, phase)
    await _list(db, workspace_id, [f"{run.workflow_key}.draft"])
    assert await research_min_sources(db, run, phase)
    job = DeviceJob(id="j", profile="seat", folder="/f")
    assert offer_body(job, limits={}, web=True)["web"] is True
    assert "web" not in offer_body(job, limits={})


@pytest.mark.asyncio
async def test_codexs_own_web_search_runs_in_every_phase_by_default_and_counts(db):
    """Codex offers web.run; a hook that refuses it as tool_not_classified (and the ChatGPT apps search next to it)
    sends Codex to fetch google.com/search instead. Web is allowed in every phase by default (logged);
    ``web_tools: research_only`` keeps it to the research phases; counted as search."""
    from app.services.workflow_runs.octryx.stop_evidence import phase_evidence
    from tests.workflow_run_octryx_support import _decide, _hook, set_tool_defaults

    run, gateway, key, workspace_id = await _bound_run(db, _draft_definition())
    for tool in ("webrun", "mcp__codex_apps__search_service__web_run", "WebSearch"):
        opened = await _decide(db, gateway, key, workspace_id, _hook(tool, commands=[{"query": "x"}]))
        assert (opened["decision"], opened["reason"]) == ("allow", "allowed_by_default"), tool
    await set_tool_defaults(db, workspace_id, web_tools="research_only")
    for tool in ("webrun", "mcp__codex_apps__search_service__web_run", "WebSearch"):
        refused = await _decide(db, gateway, key, workspace_id, _hook(tool, commands=[{"query": "x"}]))
        assert refused["decision"] == "deny" and refused["reason"] == "outside_phase_tools", tool
        assert refused["remedy"] == {"setting": "device_runs.tool_defaults.web_tools", "value": "all"}
    await _list(db, workspace_id, [f"{run.workflow_key}.draft"])
    for tool in ("webrun", "mcp__codex_apps__search_service__web_run"):
        allowed = await _decide(db, gateway, key, workspace_id, _hook(tool, commands=[{"query": "x"}]))
        assert allowed["decision"] == "allow", (tool, allowed)
    rows = [_call(gateway, "webrun", at=utc_now()), _call(gateway, "webrun", at=utc_now(), ok=False)]
    assert [(use.name, use.succeeded) for use in phase_evidence(rows, since=None, test_prefixes=()).tools] == [
        ("web_search", True), ("web_search", False)]


@pytest.mark.asyncio
async def test_every_phase_is_told_how_to_fetch_from_the_web_in_the_sandbox(db):
    """curl and Python HTTPS fail their certificate check inside the sandbox; WebFetch and Node work."""
    from app.services.workflow_runs.octryx.hooks import session_contract
    from app.services.workflow_runs.run_texts import run_text

    _run, gateway, _key, _workspace_id = await _bound_run(db, _draft_definition())
    assert (await session_contract(db, gateway))["phase"]["web_requests"] == run_text("contract.web_requests")
