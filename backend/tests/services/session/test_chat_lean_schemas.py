"""A chat request sends its full schemas lean (fewer input tokens per task)."""

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
    assert "start_workflow" in context.deferred_tool_catalog
    loaded = await chat_tool_search({"query": "select:list_available_workflows,start_workflow"}, context)
    assert loaded["loaded"] == ["list_available_workflows", "start_workflow"]




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


