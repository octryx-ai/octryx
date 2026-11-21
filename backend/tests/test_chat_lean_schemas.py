"""A chat request sends its full schemas lean (fewer input tokens per task).

The core schemas ride on every model call of a chat turn. Optional parameters no eval or live chat used are left out
of what the chat sends; the tool still accepts them, and the full definition stays for every other surface.
"""

from __future__ import annotations

from app.services.chat_deferred_tools import (
    CHAT_CORE_TOOLS,
    CHAT_OMITTED_PARAMS,
    DIRECT_TOOL_LIMIT,
    chat_tool_search,
    defer_chat_tools,
    lean_chat_schema,
    sent_chat_tool_definitions,
)
from app.tools.context import ToolContext
from app.tools.definitions import get_all_definitions


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=["member"], session_id="s", project_config={})


def _properties(definition) -> set[str]:
    return set(definition["function"]["parameters"]["properties"])


def _offered() -> list[dict]:
    definitions = get_all_definitions()
    names = [*CHAT_CORE_TOOLS, "start_workflow", "list_available_workflows"]
    filler = [name for name in definitions if name not in names][: DIRECT_TOOL_LIMIT + 1]
    return [definitions[name] for name in [*names, *filler] if name in definitions]


def test_the_chat_sends_core_schemas_without_the_unused_optional_parameters():
    full = get_all_definitions()
    sent = {d["function"]["name"]: d for d in defer_chat_tools(_offered(), families=(), history=[], context=_context())}

    for tool, omitted in CHAT_OMITTED_PARAMS.items():
        assert not _properties(sent[tool]) & set(omitted), tool
        assert set(omitted) <= _properties(full[tool]), f"{tool}: the full definition keeps them for other surfaces"
    assert {"query", "include_domains", "num_results"} <= _properties(sent["web_search"])
    assert "fix_versions" in _properties(sent["search_jira_tickets"])


def test_a_required_parameter_is_never_left_out():
    definition = {"type": "function", "function": {"name": "web_search", "parameters": {
        "type": "object", "properties": {"query": {}, "exclude_terms": {}}, "required": ["exclude_terms"]}}}

    assert "exclude_terms" in _properties(lean_chat_schema(definition))


async def test_start_workflow_is_one_search_away_together_with_its_workflow_list():
    context = _context()
    offered = defer_chat_tools(_offered(), families=(), history=[], context=context)
    sent = sent_chat_tool_definitions(offered, context.deferred_tool_catalog, context.discovered_tool_names)

    assert "start_workflow" not in {d["function"]["name"] for d in sent}
    assert "start_workflow" in next(d for d in sent if d["function"]["name"] == "tool_search")["function"]["description"]
    loaded = await chat_tool_search({"query": "select:list_available_workflows,start_workflow"}, context)
    assert loaded["loaded"] == ["list_available_workflows", "start_workflow"]


def test_a_settled_workflow_choice_is_the_composer_or_a_router_decision():
    from app.services.workflow_routing.proposal import (
        direct_agent_selected_resolution,
        user_selected_no_workflow_resolution,
    )
    from app.services.workflow_routing.proposal_states import WORKFLOW_PROPOSAL_KEY, WORKFLOW_PROPOSAL_VERSION
    from app.services.workflow_routing.settled_choice import workflow_choice_settled

    def routed(reason_code):
        return {"source": "workflow_routing_policy", WORKFLOW_PROPOSAL_KEY: {
            "version": WORKFLOW_PROPOSAL_VERSION, "status": "none", "reason_code": reason_code}}

    assert workflow_choice_settled({"source": "explicit_workflow_key", "status": "matched"})
    assert workflow_choice_settled(routed("no_match")) and workflow_choice_settled(routed("offered_not_requested"))
    assert workflow_choice_settled(user_selected_no_workflow_resolution())
    assert workflow_choice_settled(direct_agent_selected_resolution())
    assert not workflow_choice_settled(routed("timeout")), "an undecided router leaves the catalog to the model"
    assert not workflow_choice_settled(routed("model_unavailable"))
    assert not workflow_choice_settled({"source": "db", "status": "matched"})
    assert not workflow_choice_settled(None)


def test_skill_and_runtime_sections_ride_only_with_their_tools():
    from app.services.chat_deferred_tools import drop_unused_prompt_sections

    system = ("Base.\n\n## Skill Discovery\nCall skill_search.\n\n## Agent Blueprint\nGoal.\n"
              "## Runtime Environment\n- Shell: bash\n\nThe person has confirmed the write plan wp_1.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "## Skill Discovery stays"}]

    lean = drop_unused_prompt_sections(messages, {"knowledge_search"})
    assert lean[0]["content"] == ("Base.\n\n## Agent Blueprint\nGoal.\n\nThe person has confirmed the write plan wp_1."), (
        "a note appended after a section stays")
    assert lean[1] == messages[1], "only system messages lose sections"
    loaded = drop_unused_prompt_sections(messages, {"skill_search", "run_cli_command"})
    assert loaded[0]["content"] == system


def test_only_a_really_shortened_result_offers_load_tool_artifact():
    from app.services.tool_artifact.summary import build_tool_artifact_envelope, result_was_shortened

    page = "Releases are cut every second Thursday. Steps: merge via PR, tag, CI deploys, promote after a soak."
    raw = {"id": "100003", "content": f"<p>{page}</p>", "created_by": {"email": "x"}, "storage_sha256": "f" * 64}
    whole = {"id": "100003", "excerpt": page, "text_length": len(page)}
    cut = {"id": "100003", "excerpt": page[:40] + "...", "text_length": len(page)}
    issues = {"issues": [{"key": f"CHEF-{n}"} for n in range(16)]}

    assert not result_was_shortened(raw, whole), "the compact page kept the whole text"
    assert result_was_shortened(raw, cut)
    assert result_was_shortened(issues, {"issues": issues["issues"][:5]})
    fresh = build_tool_artifact_envelope(artifact_id="a", tool_name="get_confluence_page", payload=whole,
                                         include_result=True, shortened=False)
    assert "detail_available" not in fresh and "detail_hint" not in fresh
    shortened = build_tool_artifact_envelope(artifact_id="a", tool_name="get_confluence_page", payload=cut,
                                             include_result=True, shortened=True)
    assert "only if the answer needs what is left out" in shortened["detail_hint"]
