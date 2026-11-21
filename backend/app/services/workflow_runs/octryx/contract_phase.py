"""What ``run_contract`` adds to the base contract: the phase's details, its test wording, the decision, Codex names."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..states import STATUS_PAUSED, STATUS_WAITING
from .phase_view import _text, how_to_run_tests


async def with_phase_details(db: AsyncSession, run: WorkflowRun, graph: Any, node: Any, contract: dict[str, Any], *,
                             item: Any, principal: Any) -> None:
    """Complete ``contract["phase"]`` (the run is at a phase) in the order the enforcement points read it."""
    from ..specification.integration import projected_phase_facts, source_backed_phase

    if await source_backed_phase(db, run, node):
        projected = await projected_phase_facts(db, run, node, principal=principal)
        contract["phase"].update(projected)
        if projected.get("source_status"):
            tools = contract["phase"]["tools"]
            tools["deny"] = sorted({*tools["deny"], *tools["allow"]})
            tools["allow"] = []
    await _with_code_style(db, run, contract)
    _with_system_tests(run, graph, node, contract, item=item)
    await _with_phase_agent(db, node, contract)
    # What the enforcement points decide, in a few lines before the agent starts.
    from ..run_texts import run_texts as brief_texts
    from .phase_brief import phase_brief

    async with brief_texts(db, run):
        contract["phase"]["brief"] = phase_brief(run, contract)


async def _with_code_style(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any]) -> None:
    # The code style for a changing phase (``code_limits.phase_style``).
    from .code_limits import phase_style

    style = await phase_style(db, run, str(contract["phase"].get("capability_class") or ""))
    if style:
        from ...code_style.brief import agent_brief

        contract["phase"]["code_style"] = style
        contract["phase"]["code_style_brief"] = agent_brief(style)


def _with_system_tests(run: WorkflowRun, graph: Any, node: Any, contract: dict[str, Any], *, item: Any) -> None:
    """The phase's system tests, its environment file rule and the CI pipeline after it."""
    from ..size_class.pipeline_scope import agent_runs_system_test
    from .contract import environment_file_rule, plain_brief
    from .system_tests import phase_system_tests

    # a web app is tested running, like CI (``system_tests``).

    system = phase_system_tests(str(contract["phase"].get("capability_class") or ""),
                                dict(contract.get("preparation") or {}).get("environment"),
                                write=list(dict(contract["phase"].get("path_rules") or {}).get("write") or []),
                                role=str((item or {}).get("role") or ""), plain=plain_brief(node),
                                protects_tests=bool(dict(contract["phase"].get("path_rules") or {})
                                                    .get("protect_confirmed_tests")),
                                by_pipeline=not agent_runs_system_test(run))
    if system:
        contract["phase"]["system_tests"] = system
    file_rule = environment_file_rule(str(contract["phase"].get("capability_class") or ""),
                                      dict(contract.get("preparation") or {}).get("environment"))
    if file_rule:
        contract["phase"]["environment_file"] = file_rule
    # the CI pipeline after a building phase is the one judge of tests and task proofs; the
    # phase's Stop does not police how the agent ran them (``pipeline.follows``, ``stop``, ``tool_policy``).
    from ..pipeline import follows

    if follows(graph, node.id, dict(contract.get("preparation") or {}).get("environment")):
        contract["phase"]["pipeline_after"] = _text("pipeline_after")


async def _with_phase_agent(db: AsyncSession, node: Any, contract: dict[str, Any]) -> None:
    """The phase's agent and its instructions (a version without one: ``None``); its tools deny narrows the phase."""
    from .agent_view import phase_agent_view
    from .contract import plain_agent, plain_brief

    agent, refused = await phase_agent_view(db, node)
    contract["phase"]["agent"] = plain_agent(agent) if plain_brief(node) else agent
    if refused:
        # A named agent without a runnable published revision is an explicit state, and the device gets
        # no tools for the phase (fail closed), never the phase without its agent.
        from ..phase_agents import phase_agent_key
        from .agent_view import agent_refusal_state

        contract["phase"]["agent_refusal"] = agent_refusal_state(phase_agent_key(node.config), refused)
        contract["phase"]["tools"] = {"allow": [], "deny": sorted({*contract["phase"]["tools"]["allow"],
                                                                  *contract["phase"]["tools"]["deny"]})}
    denied = set((agent or {}).get("tools_deny") or [])
    if denied:
        # The published agent's tools deny narrows the device's phase tools too (PreToolUse reads these lists).
        tools = contract["phase"]["tools"]
        tools["allow"] = [tool for tool in tools["allow"] if tool not in denied]
        tools["deny"] = sorted({*tools["deny"], *denied})


async def with_test_runs(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any]) -> None:
    """How the phase runs its tests, worded for the run's declared environment and size class."""
    from ..run_texts import run_texts

    async with run_texts(db, run):  # the run's catalog versions; the runner of its declared environment
        contract["phase"]["how_to_run_tests"] = how_to_run_tests(
            dict(contract.get("preparation") or {}).get("environment"))
        from ..run_texts import run_text
        from ..size_class.tests_scope import agent_tests

        if agent_tests(run) == "affected":  # the class leaves the whole suite to the pipeline (lever 1)
            contract["phase"]["how_to_run_tests"] += " " + run_text("tests.affected")
        from ..size_class.pipeline_scope import agent_runs_system_test

        if not agent_runs_system_test(run):  # the pipeline runs the system test on every pass
            contract["phase"]["how_to_run_tests"] += " " + run_text("tests.system_by_pipeline")


async def with_decision(db: AsyncSession, run: WorkflowRun, contract: dict[str, Any], *, state: dict[str, Any],
                         link: str | None, principal: Any) -> None:
    """What a waiting or paused run waits for, and who decides it."""
    if run.status == STATUS_WAITING:
        waiting = dict(state.get("waiting") or {})
        contract["waiting"] = {"kind": run.waiting_kind, "title": waiting.get("title"),
                               "question": waiting.get("question"), "decide_in": link}
    if run.status == STATUS_PAUSED:
        pause = dict(state.get("pause") or {})
        contract["paused"] = {"reason": run.pause_reason, "detail": pause.get("message"), "decide_in": link}
    if run.status in (STATUS_WAITING, STATUS_PAUSED):
        from ..specification.integration import protected_waiting
        from .decisions import pending_decision

        if await protected_waiting(db, run):
            contract["decision"] = await pending_decision(db, run, principal=principal)
        else:
            contract["decision"] = await pending_decision(db, run)


async def _runs_codex(db: AsyncSession, session: Any) -> bool:
    """Whether the session runs on Codex: the gateway session its launcher registered as Codex, or the platform
    session of a Codex device job (``devices.job_engine``)."""
    from ...agent_gateway.engine_keys import ENGINE_CODEX, SESSION_ENGINE_KEY

    metadata = getattr(session, "metadata_", None)
    if isinstance(metadata, dict) and metadata.get(SESSION_ENGINE_KEY) == ENGINE_CODEX:
        return True
    session_id = getattr(session, "id", None)
    if not session_id:
        return False
    from sqlalchemy import select

    from ....models import DeviceJob

    engine = (await db.execute(select(DeviceJob.engine).where(DeviceJob.session_id == session_id).order_by(
        DeviceJob.created_at.desc()).limit(1))).scalar_one_or_none()
    return engine == "codex"


def _for_codex(contract: dict[str, Any]) -> None:
    """A Codex session calls Codex's own tools: the contract names them (``codex_names``; otherwise the
    model looks for ``write_workspace_file`` / ``Write``, which Codex does not have, and loops)."""
    from .codex_names import codex_on_device

    tools = (contract.get("phase") or {}).get("tools")
    if isinstance(tools, dict) and isinstance(tools.get("on_device"), list):
        tools["on_device"] = codex_on_device(tools["on_device"])
        tools["on_device_note"] = _text("codex_tools_note")  # a Codex session's own tools
