"""Seeds of the research delegation prompts: the delegated child agents and tasks of spawn_sub_agent,
sub-agent group resume prompts and coordinator continue prompts.

The only code copy of these texts.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "research"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="research.spawn.blocked_error",
        area=AREA,
        title="Spawn refused: migration delegation consolidated",
        seed=(
            "Java/Spring migration delegation was already consolidated or implementation gates have started. Continue "
            "in the parent session with the existing sub-thread context, migration changes, tests, diff review, and "
            "final gate summary instead of spawning another sub-agent group."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.spawn.blocked_next_step",
        area=AREA,
        title="Spawn refused: recommended next step",
        seed=(
            "Call get_context_from_subthreads only if existing child evidence still needs consolidation; otherwise run "
            "or summarize the remaining OpenRewrite, test, git diff, and finalization gates."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.spawn.spawned_message",
        area=AREA,
        title="Sub-agents spawned",
        seed=(
            "Spawned {count} sub-agents. Wait for them to finish, then consolidate with "
            "`get_context_from_subthreads`."
        ),
        placeholders=frozenset({"count"}),
    ),
    PromptKeySpec(
        key="research.child.preamble",
        area=AREA,
        title="Delegated child task: migration preamble",
        seed="Parent coding-migration context. Stay within this repository and migration target.",
    ),
    PromptKeySpec(
        key="research.child.parent_request_line",
        area=AREA,
        title="Delegated child task: parent request",
        seed="Parent request: {parent_request}",
        placeholders=frozenset({"parent_request"}),
    ),
    PromptKeySpec(
        key="research.child.task_header",
        area=AREA,
        title="Delegated child task: task header",
        seed="Delegated sub-task:",
    ),
    PromptKeySpec(
        key="research.child.coding.prompt",
        area=AREA,
        title="Delegated coding worker: prompt",
        seed=(
            "Focus only on the delegated coding sub-task. Your first assistant response must be an allowed repository "
            "tool call with no greeting, planning prose, or progress narration. Use only the allowed tools, do not "
            "edit files unless an edit tool is explicitly allowed, do not spawn further sub-agents, and return concise "
            "repository-grounded findings with concrete file paths, risks, and validation gates."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.child.coding.instructions",
        area=AREA,
        title="Delegated coding worker: step instructions",
        seed=(
            "Use only the allowed repository tools for the delegated coding sub-task. Your first response in this step "
            "must be an allowed tool call. Inspect the repository surface that matches the sub-task, then return "
            "concrete findings, relevant file paths, and explicit gaps. Do not inspect unrelated systems and do not "
            "spawn further sub-agents."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.child.coding.success",
        area=AREA,
        title="Delegated coding worker: success criteria",
        seed=(
            "You used at least one allowed repository tool, then returned concise findings or explicit evidence gaps "
            "for the delegated coding sub-task."
        ),
    ),
    PromptKeySpec(
        key="research.child.source_goal.multiple",
        area=AREA,
        title="Delegated research worker: source goal (several)",
        seed=(
            "Collect and ingest at least {min_sources_per_child} credible archived sources before stopping when "
            "possible. If fewer credible sources are available after bounded attempts, state the exact evidence gap."
        ),
        placeholders=frozenset({"min_sources_per_child"}),
    ),
    PromptKeySpec(
        key="research.child.source_goal.single",
        area=AREA,
        title="Delegated research worker: source goal (one)",
        seed=(
            "Once you have one credible authoritative source, use `ingest_document_source` to ground your findings in "
            "actual source material, then stop unless you still need one more source to close a concrete gap."
        ),
    ),
    PromptKeySpec(
        key="research.child.success_goal.multiple",
        area=AREA,
        title="Delegated research worker: success goal (several)",
        seed="gathered at least {min_sources_per_child} credible archived sources",
        placeholders=frozenset({"min_sources_per_child"}),
    ),
    PromptKeySpec(
        key="research.child.success_goal.single",
        area=AREA,
        title="Delegated research worker: success goal (one)",
        seed="gathered at least one source-grounded piece of evidence",
    ),
    PromptKeySpec(
        key="research.child.search_first_guidance",
        area=AREA,
        title="Delegated research worker: search-first guidance",
        seed=(
            " If the delegated task includes one or more explicit authoritative URLs, call `ingest_document_source` on "
            "each listed URL until the source target is met before searching. Otherwise start with `web_search` or "
            "`codesearch` on the delegated topic before writing any prose. Use quoted topic terms together with "
            "phrases like 'developer documentation', 'API reference', or 'REST API'. If the topic names a technical "
            "category rather than a single product, choose representative enterprise platforms and search their "
            "official docs/support references first. Prefer official developer documentation, API reference pages, and "
            "support knowledge-base articles over blogs, vendor marketing posts, or generic 'best practices' articles. "
            "If results drift toward product marketing pages, login pages, or generic blogs, reformulate using a "
            "developer portal hostname or a product plus API-reference phrase instead of repeating the same generic "
            "query. {source_goal}"
        ),
        placeholders=frozenset({"source_goal"}),
        risk=RISK_HIGH,
        description="Used when web_search or codesearch is allowed; {source_goal} is one of the source-goal keys.",
    ),
    PromptKeySpec(
        key="research.child.research.prompt",
        area=AREA,
        title="Delegated research worker: prompt",
        seed=(
            "Focus only on the delegated sub-task. Your first assistant response must be an allowed tool call and must "
            "not contain greeting text, planning prose, or progress narration.{search_first_guidance} Use only the "
            "allowed tools, do not inspect repositories, do not spawn further sub-agents, and return concise "
            "source-grounded findings or explicit evidence gaps."
        ),
        placeholders=frozenset({"search_first_guidance"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.child.research.instructions",
        area=AREA,
        title="Delegated research worker: step instructions",
        seed=(
            "Use only the allowed tools for the delegated sub-task. Your first response in this step must be an "
            "allowed tool call with no greeting, transition narration, or plan summary before it. If the delegated "
            "task includes one or more explicit authoritative URLs and `ingest_document_source` is allowed, ingest the "
            "listed URLs until the source target is met before searching or writing prose. Otherwise, if `web_search` "
            "or `codesearch` is allowed, use one of them first to identify a credible source for the delegated topic, "
            "prefer official developer documentation, API reference pages, and support knowledge-base articles over "
            "blogs or vendor marketing posts, and if the results drift toward marketing or login pages, switch to a "
            "developer portal hostname or a product-plus-API-reference query. If a search returns zero or irrelevant "
            "results, your next response must be another allowed tool call with a reformulated official-doc query; do "
            "not answer with product names, summaries, or platform lists before either ingesting a concrete source or "
            "exhausting the bounded retries. then use `ingest_document_source` to capture source-grounded evidence "
            "from a concrete result. {source_goal} Do not inspect repositories. Do not spawn further sub-agents. If "
            "evidence stays weak after bounded attempts, stop and return the best partial findings plus explicit gaps."
        ),
        placeholders=frozenset({"source_goal"}),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="research.child.research.success",
        area=AREA,
        title="Delegated research worker: success criteria",
        seed=(
            "You used the allowed tools immediately, {success_goal} when possible, then returned concise findings or "
            "explicit evidence gaps for the delegated sub-task."
        ),
        placeholders=frozenset({"success_goal"}),
    ),
    PromptKeySpec(
        key="research.sub_agent_group.waiting",
        area=AREA,
        title="Sub-agent group: all finished",
        seed=(
            "All spawned sub-agents for this thread have finished. Call `get_context_from_subthreads` to consolidate "
            "the child sessions, then continue the parent task and finish with one final answer."
        ),
        risk=RISK_HIGH,
        description="Resume prompt of the parent when every child finished.",
    ),
    PromptKeySpec(
        key="research.sub_agent_group.timeout",
        area=AREA,
        title="Sub-agent group: timed out",
        seed=(
            "Some spawned sub-agents timed out before finishing. Call `get_context_from_subthreads` to consolidate the "
            "available child sessions, explicitly call out any missing coverage, then continue the parent task and "
            "finish."
        ),
        risk=RISK_HIGH,
        description="Resume prompt of the parent when children timed out.",
    ),
    PromptKeySpec(
        key="research.coordinator.continue",
        area=AREA,
        title="Coordinator: continue",
        seed="Continue from the current coordinator state in this same session. Do not restart from scratch.",
        description="Continue prompt of a coordinator session.",
    ),
    PromptKeySpec(
        key="research.coordinator.continue_worker_delegation",
        area=AREA,
        title="Coordinator: continue after worker delegation",
        seed=(
            "Continue from the completed worker delegation results in this same coordinator session. Do not restart "
            "from scratch."
        ),
    ),
)
