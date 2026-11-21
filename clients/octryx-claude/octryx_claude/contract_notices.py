"""The run contract's lines for the person and the model (``run_contract``): the summary, the launch banner, where a
pending decision is taken, the first prompt's workflow proposal and the platform agent the session works as."""

from __future__ import annotations

from typing import Any

from .contract_change import _clean
from .state import LocalState, read_json, write_private_json

SHOWN_FILE = "workflow_run_shown.json"
PLATFORM_AGENT_FILE = "platform_agent.json"
AGENT_SHOWN_FILE = "platform_agent_shown.json"
MAX_INSTRUCTIONS = 6000


def summary(contract: dict[str, Any]) -> str:
    run = contract.get("run") or {}
    key = _clean(run.get("workflow_key"), 120)
    for name in ("paused", "waiting"):
        pending = contract.get(name)
        if isinstance(pending, dict):
            what = _clean(pending.get("reason") or pending.get("question") or pending.get("kind"))
            state = "is paused" if name == "paused" else "waits"
            hint = decide_hint(contract)
            return f"Workflow run {key} {state}: {what}. {hint[:1].upper() + hint[1:]}."
    phase = contract.get("phase")
    prep = contract.get("preparation") if isinstance(contract.get("preparation"), dict) else {}
    if not isinstance(phase, dict) and prep.get("state") == "pending" and prep.get("runtime") == "terminal":
        return (f"Workflow run {key} waits for its folder's preparation (branch {_clean(prep.get('branch'), 200)}): "
                "exit and start octryx-claude again in the repository folder; it prepares the folder first.")
    if isinstance(phase, dict):
        loops = "; ".join(f"{_clean(loop.get('title'), 80)} {loop.get('iteration')}/{loop.get('of')}"
                          for loop in contract.get("loop") or [] if isinstance(loop, dict))
        return (f"Workflow run {key}: phase '{_clean(phase.get('title'), 120)}' "
                f"({_clean(phase.get('capability_class'), 20)}){'; ' + loops if loops else ''}. "
                "workflow_run_status shows the contract.")
    return f"Workflow run {key}: {_clean(run.get('status'), 20)}."


def banner(contract: dict[str, Any]) -> list[str]:
    """The run banner the launcher prints at start: workflow, phase or what the run waits for, loop i/n."""
    run = contract.get("run") or {}
    head = f"workflow run {_clean(run.get('workflow_key'), 120)} v{_clean(run.get('workflow_version'), 10)}"
    ticket = _clean(run.get("ticket_key"), 40)
    lines = [f"{head} ({_clean(run.get('status'), 20)}){' | ' + ticket if ticket else ''}"]
    phase = contract.get("phase")
    if isinstance(phase, dict):
        lines.append(f"phase: {_clean(phase.get('title'), 120)} ({_clean(phase.get('capability_class'), 20)})")
    for loop in contract.get("loop") or []:
        if isinstance(loop, dict):
            lines.append(f"loop: {_clean(loop.get('title'), 80)} {loop.get('iteration')}/{loop.get('of')}")
    for name in ("waiting", "paused"):
        pending = contract.get(name)
        if isinstance(pending, dict):
            what = _clean(pending.get("question") or pending.get("title") or pending.get("reason")
                          or pending.get("kind"))
            lines.append(f"{'waiting for' if name == 'waiting' else 'paused'}: {what}")
            lines.append(decide_hint(contract))
    return lines


def decide_hint(contract: dict[str, Any]) -> str:
    """Where the pending decision is taken: here (the decision tool, the user's permission prompt) or the platform."""
    decision = contract.get("decision") if isinstance(contract.get("decision"), dict) else {}
    pending = contract.get("waiting") or contract.get("paused") or {}
    link = _clean(contract.get("link") or (pending.get("decide_in") if isinstance(pending, dict) else ""))
    where = f"in Octryx{': ' + link if link else ''}"
    if decision.get("in_terminal"):
        actions = ", ".join(_clean(action, 20) for action in decision.get("actions") or [])
        return (f"decide here ({actions}: tell the agent, then confirm in the permission prompt; payload "
                f"{_clean(decision.get('payload_hash'), 80)}) or {where}")
    if decision.get("kind") in ("watch", "review", "sub_workflow"):
        return f"nobody decides: the run continues when the external state is reached ({where})"
    return f"decide {where}"


def proposal_notice(proposal: dict[str, Any]) -> tuple[str, str]:
    """``(model context, user line)`` for the first prompt's workflow proposal; empty strings when there is none."""
    state = proposal.get("state")
    key = _clean(proposal.get("workflow_key"), 120)
    title = _clean(proposal.get("workflow_title"), 120) or key
    reason = _clean(proposal.get("reason"))
    if state == "selected" and key:
        return (f"Octryx selected the read-only workflow '{key}' for this Work item ({reason}). "
                "workflow_select with it returns its contract; follow it.",
                f"Workflow '{title}' selected (read-only).")
    if state == "proposed" and key:
        work_item = _clean(((proposal.get("next") or {}).get("arguments") or {}).get("work_item"), 120)
        kind = "phased workflow run" if proposal.get("phased") else "change workflow"
        return (f"Octryx proposes the {kind} '{key}' for this Work item ({reason}). It needs the user's "
                f"confirmation: ask the user whether to start it; only if they agree call workflow_select with "
                f"workflow_key='{key}' and work_item='{work_item}', then workflow_confirm (the user confirms in the "
                "permission prompt). Never start it without asking.",
                f"Proposed workflow: '{title}' ({kind}, needs your confirmation). {reason}")
    return "", ""


def changed_notice(state: LocalState, session_key: str, contract: dict[str, Any] | None) -> str:
    """One line when the contract changed since it was last shown; ``""`` otherwise."""
    if not contract:
        return ""
    path = state.session_dir(session_key) / SHOWN_FILE
    if read_json(path).get("digest") == contract.get("digest"):
        return ""
    write_private_json(path, {"digest": contract.get("digest")})
    return summary(contract)


LIFTED_FILE = "platform-agent-lifted.json"
LIFTED_DIGEST = "lifted"
LIFTED_NOTICE = ("Octryx: this session is no longer read-only. Earlier instructions that changes happen only "
                 "inside a workflow run no longer apply: work like Claude Code in this project, within the person's "
                 "permission mode. Octryx still checks every tool call and refuses what its rules forbid.")


def remember_platform_agent(state: LocalState, session_key: str, body: dict[str, Any] | None) -> None:
    """Keep the registration answer's outside-run agent (the read-only Assistant of a strict Workspace).

    Without one (sessions follow the permission mode), a kept one is removed and the model is told
    once that the session is no longer read-only, so a resumed conversation does not keep refusing changes."""
    agent = (body or {}).get("platform_agent")
    path = state.session_dir(session_key) / PLATFORM_AGENT_FILE
    if isinstance(agent, dict) and agent.get("digest"):
        write_private_json(path, agent)
    elif path.exists():
        path.unlink(missing_ok=True)
        write_private_json(state.session_dir(session_key) / AGENT_SHOWN_FILE, {"digest": LIFTED_DIGEST})
        write_private_json(state.session_dir(session_key) / LIFTED_FILE, {"pending": True})


def agent_notice(state: LocalState, session_key: str, contract: dict[str, Any] | None) -> str:
    """The agent's instructions for the model when they changed since last shown; ``""`` otherwise."""
    phase = contract.get("phase") if isinstance(contract, dict) else None
    agent = phase.get("agent") if isinstance(phase, dict) else None
    outside_run = contract is None
    lifted = state.session_dir(session_key) / LIFTED_FILE
    if outside_run and read_json(lifted).get("pending"):
        write_private_json(lifted, {"pending": False})
        return LIFTED_NOTICE
    if outside_run:
        agent = read_json(state.session_dir(session_key) / PLATFORM_AGENT_FILE)
    if not isinstance(agent, dict) or not agent.get("digest"):
        return ""
    path = state.session_dir(session_key) / AGENT_SHOWN_FILE
    if read_json(path).get("digest") == agent.get("digest"):
        return ""
    write_private_json(path, {"digest": agent.get("digest")})
    version = agent.get("version")
    head = f"You work as the Octryx {_clean(agent.get('name'), 80)} agent" + (
        f" (v{_clean(version, 10)})" if version else "")
    scope = (" — this session is read-only: changes happen only inside a workflow run." if outside_run
             else " in this workflow phase.")
    instructions = str(agent.get("instructions") or "")[:MAX_INSTRUCTIONS]
    return f"{head}{scope}\n{instructions}".strip()
