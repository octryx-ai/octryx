"""A run turn's permission mode and model: the run's settings, the phase's model and the Workspace's refusal."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import NODE_PHASE, PhasedNode

PERMISSIONS_KEY = "permissions"
PERMISSIONS_BYPASS = "bypass"
MODE_BYPASS = "bypassPermissions"


async def _run_turn_mode(db: AsyncSession, run: WorkflowRun, node: PhasedNode | None = None,
                         user_id: str | None = None) -> str:
    """``acceptEdits`` for the run's own turns unless the Workspace asks before each edit (device_runs key
    ``run_turns_ask_before_edits``): the platform's hooks decide every change; nobody has to sit at the device.

    A phase whose node says ``config.permissions: "bypass"`` (epic-delivery's story session) runs in
    ``bypassPermissions`` when the run's owner may use bypass in the Workspace (``role_modes.session_ceiling``: their
    role and the Workspace's ``bypass_permissions``). The story session runs in bypass inside its own
    branch: otherwise there were 29-34 of Claude Code's own approval prompts per epic in
    ``acceptEdits`` (compound shell forms, sandbox network), each waiting for a person; plain Claude Code ran with
    ``--dangerously-skip-permissions``. Bypass skips only Claude Code's own prompts: the platform's PreToolUse hook
    (the phase contract, the hard-deny list, the browser's loopback rule) and the settings' deny rules still decide
    every call, and the sandbox still holds every shell command."""
    from ...agent_gateway.policy import load_workspace_policy
    from ...agent_gateway.role_modes import CEILING_BYPASS, session_ceiling
    from ...devices.device_runs_keys import device_runs_section

    if not run.project_id:
        return ""
    loaded = await load_workspace_policy(db, run.project_id)
    section = device_runs_section(loaded.policy.raw) if loaded.policy is not None else {}
    if section.get("run_turns_ask_before_edits") is True:
        return ""
    if node is not None and dict(node.config or {}).get(PERMISSIONS_KEY) == PERMISSIONS_BYPASS and \
            await session_ceiling(db, user_id=user_id, workspace_id=run.project_id) == CEILING_BYPASS:
        return MODE_BYPASS
    return "acceptEdits"


def _phase_model(node: PhasedNode) -> str:
    """The model the workflow's designer set on the phase (``config.model``), ``""`` when none."""
    return str(dict(node.config or {}).get("model") or "").strip() if node.kind == NODE_PHASE else ""


def turn_phase_model(run: WorkflowRun, node: PhasedNode) -> str:
    """The model the phase itself decides for its turn (its explicit ``model``), ``""`` when it leaves it to the
    profile."""
    return _phase_model(node)


async def _with_run_settings(db: AsyncSession, run: WorkflowRun, node: PhasedNode,
                             target: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    """The run's own permission mode and the turn's model on ``target``.

    The phase's explicit model wins on every profile, also over a model chosen on the thread: team-delivery runs each
    role on its own model (coordinate Sonnet, builders Haiku); otherwise the seat skips it
    and every role runs on the seat's thread model (:func:`turn_phase_model`). Without one, a governed turn takes the
    Workspace's model for the phase's class unless the thread chose one; the seat keeps the thread's (the person's
    subscription choice) unless a model class default applies (``seat_models``)."""
    target = {**target, "permission_mode": await _run_turn_mode(db, run, node, user_id)}
    if target.get("profile") == "seat":
        # The seat's model by the phase's model class (``seat_models``): node > run start > workflow > Workspace >
        # installation > device default, one event per change.
        from .seat_models import note_choice, seat_choice

        choice = await seat_choice(db, run, node, str(target.get("model") or ""))
        note_choice(db, run, node.id, choice)
        return {**target, "model": choice.model} if choice.model else target
    decided = turn_phase_model(run, node)
    if decided:
        return {**target, "model": decided}
    if target.get("profile") != "seat" and not str(target.get("model") or ""):
        return {**target, "model": await _run_turn_model(db, run, node)}
    return target


async def _run_turn_model(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> str:
    """The model of the run's own governed turn: the phase's ``model`` (designer), else the Workspace's
    ``device_runs.run_turn_models`` for the phase's capability class; ``""`` (device default) when the Workspace
    does not admit it for the governed profile."""
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import DEFAULTS, device_runs_section
    from ..phase_contract import phase_definition

    definition = phase_definition(run, node) if node.kind == NODE_PHASE else {}
    contract = dict(definition.get("workflow_contract") or {})
    chosen = str(dict(node.config or {}).get("model") or "").strip()
    if not chosen and run.project_id:
        loaded = await load_workspace_policy(db, run.project_id)
        section = device_runs_section(loaded.policy.raw) if loaded.policy is not None else DEFAULTS
        models = {**DEFAULTS["run_turn_models"], **dict(section.get("run_turn_models") or {})}
        chosen = str(models.get(str(contract.get("capability_class") or "read_only")) or "")
    return chosen
