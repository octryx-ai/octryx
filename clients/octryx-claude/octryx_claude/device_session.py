"""One device job turn as an ordinary octryx-claude session: only the prompt source changes.

The same steps as an interactive launch (``cli_launch._launch``), with the device credential instead of the user's
login: the Workspace's client policy (fail closed), the seat refusal, ``/sessions/register`` as
``octryx-claude-device``, the generated settings (hooks, deny/ask rules, sandbox with ``failIfUnavailable`` and
``disableBypassPermissionsMode``), the knowledge MCP config, the child env (``OCTRYX_CREDENTIAL_SET=device`` so the
hooks, ``apiKeyHelper`` and MCP headers use the device grant) and the hook key with its signer.

Nothing in the platform's ``job_offer`` reaches these settings: the offer only names the prompt, the folder
(already checked against the local allowlist), the Workspace, the profile and the model. A requested model must be
one of the profile's ``/model`` rows in this session's client policy (``model_not_offered`` otherwise); it is
passed to Claude Code as ``--model`` for this turn, empty keeps the launcher's ``main`` alias.

Parity with the terminal:

- the run the job carries goes with every control-plane call (``SessionContext.workflow_run``), so registration binds
  the session to it under the attach rule; a registration that does not attach refuses the turn
  (``registration_denied_<attach reason>``, or ``workflow_run_not_attached``), and the run contract is remembered
  for the hooks exactly as at a terminal launch (``run_contract.remember``);
- the job folder's repository is bound and snapshotted by the terminal's own code intelligence
  (``snapshot.run_code_intelligence``): remote, HEAD and the repository root the server checks against the device's
  allowed folders and the run's repository. A device session for a run starts only with that binding (else
  ``repository_<code>``); a root outside the allowed folders refuses any turn;
- before that, the folder is prepared for the run (``workspace_prep``, "Environment readiness"): the run's branch
  checked out, the repository's declared test environment verified (its declared setup run in the folder when
  needed) and reported; a folder that is not ready refuses the turn (``environment_not_ready`` /
  ``workspace_dirty``, the run pauses with the reason), and the declared ``path`` goes first on the agent's ``PATH``.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from octryx_claude import contract_notices, launch_process, launch_settings

from . import launch, run_contract, signer, workspace_prep
from .device_session_steps import (
    TIMEOUT,
    _aliases,
    _codes,
    child_env,
    policy_refusal,
    register,
    session_extra,
    session_settings,
)
from .platform import SessionContext, call_control_plane, valid_header_value
from .snapshot import run_code_intelligence
from .state import CREDENTIAL_SET_DEVICE, LocalState

logger = logging.getLogger("octryx_claude.device")
# The server's refusals of a reported repository that end any device turn (``agent_gateway.repository_root``).
REPOSITORY_REFUSALS = frozenset({"folder_not_allowed_on_device", "repository_root_missing"})
# A workflow run id (UUID) a device job carries.
_RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


PIPELINE_DONE = "pipeline_done"
HANDS_ON_DONE = "hands_on_done"
# The job ran the run's git work in the main folder (``work_git``: item worktrees, merges); no agent turn follows.
WORK_GIT_DONE = "work_git_done"


class SessionRefusedError(Exception):
    """The turn cannot start; ``code`` is fixed and goes back to the chat as the rejection reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class PreparedSession:
    session_key: str
    cli_path: str
    settings_path: Path
    mcp_path: Path
    env: dict[str, str]
    profile: str
    model: str = ""
    signer: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        if self.signer is not None:
            self.signer.close()
            self.signer = None


def prepare_local(state: LocalState, name: str) -> PreparedSession:
    """A take-over turn in a Claude Code profile outside octryx (P6c): that profile's own settings, MCP servers and
    login, nothing of octryx's (no platform hooks, no gateway). Approvals still come to the person: the SDK asks
    ``can_use_tool`` where Claude Code would prompt."""
    from . import launch, local_profiles  # noqa: PLC0415

    profile = local_profiles.find(state, name)
    if profile is None:
        raise SessionRefusedError("profile_unavailable_on_device")
    cli_path = launch.resolve_claude()
    if not cli_path:
        raise SessionRefusedError("claude_not_installed")
    return PreparedSession(session_key=str(uuid.uuid4()), cli_path=cli_path, settings_path=Path(),
                           mcp_path=Path(), env=local_profiles.profile_env(profile), profile=f"local:{name}",
                           extra={"local": True, "state_root": str(state.root)})


def _bind_repository(state: LocalState, context: SessionContext, folder: str, http: httpx.Client) -> None:
    """The terminal's code intelligence for the job folder; a run-bound turn needs the binding."""
    out = io.StringIO()
    outcome = run_code_intelligence(state, context, folder, http=http, out=out)
    logger.info("%s", out.getvalue().strip())
    if outcome.state == "off" and (context.workflow_run or outcome.code in REPOSITORY_REFUSALS):
        code = outcome.code or "unbound"
        raise SessionRefusedError((code if code.startswith(("repository_", "folder_")) else f"repository_{code}")[:80])


SUBAGENT_MODEL_ENV = "CLAUDE_CODE_SUBAGENT_MODEL"


def subagents_follow_the_turn(model_vars: dict[str, str], *, model: str, workflow_run: str) -> dict[str, str]:
    """A workflow run's turn with a model of its own runs its Claude Code sub-agents on that model too.

    Otherwise ``CLAUDE_CODE_SUBAGENT_MODEL`` is the device's "main" alias (Opus), and a Haiku story session's
    sub-agents would run on the more expensive model. It goes into the session's settings ``env``, which outranks the
    child's own environment."""
    if workflow_run and model:
        return {**model_vars, SUBAGENT_MODEL_ENV: model}
    return model_vars


CLAUDE_MODEL_PREFIX = "claude-"


def _resolve_engine(state: LocalState, *, profile: str, model: str, engine: str) -> tuple[str, str]:
    """The coding CLI of this turn (Claude Code, or Codex for ``engine`` ``codex``) and the model it runs."""
    if engine == "codex":
        from .codex_driver import CodexUnavailableError, resolve_codex  # noqa: PLC0415

        try:
            claude = resolve_codex()
        except CodexUnavailableError as exc:
            raise SessionRefusedError(exc.code) from exc
        from .codex_seat import logged_in  # noqa: PLC0415

        # Codex's seat is the person's own ChatGPT login (``codex_seat``), never a Claude subscription.
        if profile == launch_process.PROFILE_SEAT and not logged_in(claude, state.root):
            raise SessionRefusedError("codex_seat_not_logged_in")
        if profile == launch_process.PROFILE_SEAT and (not model or model.startswith(CLAUDE_MODEL_PREFIX)):
            # A phase's fixed Claude model (epic-delivery implements on claude-haiku-5-5) means nothing to ChatGPT:
            # the Codex seat runs on the device's own choice (``codex_seat_model`` in the launcher config), else on
            # Codex's default model.
            model = str(state.config().get("codex_seat_model") or "")
        return claude, model
    try:
        return launch.resolve_claude(), model
    except launch.LaunchRefusedError as exc:
        raise SessionRefusedError(exc.code) from exc


def _platform_work(device_creds: LocalState, context: SessionContext, contract: Any, folder: str, *,
                   http: httpx.Client, model: str) -> Any:
    """The run's work before an agent turn, each when the platform asks for it: the folder's readiness, the git work,
    the CI pipeline and the hands-on test. A step that was the job's whole work ends the turn with its code."""
    # The run's branch and test environment in the job folder before the agent starts (the platform decides).
    contract, refused = workspace_prep.prepare_for_session(device_creds, context, contract, folder, http=http,
                                                           runtime="device", timeout=TIMEOUT)
    if refused:
        raise SessionRefusedError(refused)
    # The run's git work in the main folder (item worktrees, merges), when the platform asks for it: no agent.
    from . import work_git  # noqa: PLC0415

    if work_git.pending(contract) is not None:
        trailer = launch.run_attribution(model, contract)["commit"]
        work_git.run_for_session(device_creds, context, contract, folder, http=http, trailer=trailer)
        raise SessionRefusedError(WORK_GIT_DONE)
    # The run's CI pipeline, when the platform waits for it: the declared commands, no agent (``pipeline``).
    from . import pipeline  # noqa: PLC0415

    ran = pipeline.pending(contract) is not None
    try:
        contract = pipeline.run_for_session(device_creds, context, contract, folder, http=http)
    except pipeline.ReportLostError as lost:
        raise SessionRefusedError(lost.code) from None  # transient: the platform offers the turn once more
    if ran and not (contract or {}).get("phase"):
        # The pipeline was this job's work; the run went on to a server step (the review). No agent turn with the
        # stale prompt ("nothing to do" turns after every pipeline); a red pipeline's next building
        # pass starts as its own continuation.
        raise SessionRefusedError(PIPELINE_DONE)
    # The run's hands-on test: the built app used in Chrome from the platform's scenarios, no agent.
    from . import hands_on  # noqa: PLC0415

    tested = hands_on.pending(contract) is not None
    try:
        contract = hands_on.run_for_session(device_creds, context, contract, folder, http=http)
    except pipeline.ReportLostError as lost:
        raise SessionRefusedError(lost.code) from None
    if tested and not (contract or {}).get("phase"):
        raise SessionRefusedError(HANDS_ON_DONE)  # green: the run went on to the review
    return contract


def _start_signer(state: LocalState, device_creds: LocalState, context: SessionContext, session_key: str,
                  folder: str, http: httpx.Client) -> Any:
    """The hook key registered with the platform, the job folder's repository bound, then the hook signer."""
    hook_key = signer.new_hook_key()
    keyed = call_control_plane(device_creds, context, "POST", "/sessions/hook-key", http=http, timeout=TIMEOUT,
                               body={"hook_key": signer.encode_hook_key(hook_key), "state_root": str(state.root)})
    if keyed.outcome != "ok" or keyed.state != "registered":
        raise SessionRefusedError(f"hook_key_{_codes(keyed)}"[:80])
    _bind_repository(device_creds, context, folder, http)
    try:
        return signer.start_signer(state, session_key, hook_key)
    except signer.SignerUnavailableError as exc:
        raise SessionRefusedError(f"hook_signer_{exc.code}"[:80]) from exc


def prepare_session(state: LocalState, *, base_url: str, workspace_id: str, profile: str, folder: str,
                    http: httpx.Client, shim: Path, model: str = "", workflow_run: str = "",
                    job_id: str = "", engine: str = "") -> PreparedSession:
    """One device turn's session. ``engine``: ``codex`` runs the turn on Codex CLI (``codex_driver``), which needs
    Codex instead of Claude Code installed; the platform part (registration, contract, hooks, MCP) is the same."""
    if profile not in launch_process.PROFILES:
        raise SessionRefusedError("profile_invalid")
    if workflow_run and not _RUN_ID.match(workflow_run):
        raise SessionRefusedError("workflow_run_invalid")
    if not valid_header_value(workspace_id):
        raise SessionRefusedError("workspace_id_invalid")
    claude, model = _resolve_engine(state, profile=profile, model=model, engine=engine)
    device_creds = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    session_key = str(uuid.uuid4())
    context = SessionContext(base_url, session_key, workspace_id, "", workflow_run)
    policy = call_control_plane(device_creds, context, "GET", "/client-policy", http=http, timeout=TIMEOUT)
    if refused := policy_refusal(policy, profile=profile, model=model, engine=engine):
        raise SessionRefusedError(refused)
    registered = register(state, device_creds, context, profile=profile, job_id=job_id, engine=engine, http=http)
    if registered.outcome != "ok" or registered.state != "registered":
        raise SessionRefusedError(f"registration_{_codes(registered)}"[:80])
    contract = run_contract.remember(device_creds, session_key, registered.body) if workflow_run else None
    contract_notices.remember_platform_agent(device_creds, session_key, registered.body)
    if workflow_run and not contract:
        raise SessionRefusedError("workflow_run_not_attached")
    contract = _platform_work(device_creds, context, contract, folder, http=http, model=model)
    seat_credential = ""
    if profile == launch_process.PROFILE_SEAT:
        seat_credential = registered.body.get("seat_credential")
        if not launch.valid_seat_credential(seat_credential):
            raise SessionRefusedError("registration_invalid_response")
    model_vars = subagents_follow_the_turn(launch.model_env(
        base_url=base_url, session_key=session_key, workspace_id=workspace_id, work_item="", aliases=_aliases(state),
        seat_credential=seat_credential, workflow_run=workflow_run), model=model, workflow_run=workflow_run)
    settings, trailer = session_settings(shim=shim, state=state, model_vars=model_vars, policy=policy,
                                         base_url=base_url, profile=profile, model=model, workflow_run=workflow_run,
                                         contract=contract)
    mcp = launch_settings.build_mcp_config(shim=shim, base_url=base_url)
    settings_path, mcp_path = launch_process.write_session_files(state.session_dir(session_key), settings, mcp)
    env = child_env(state=state, model_vars=model_vars, profile=profile, base_url=base_url, session_key=session_key,
                    workspace_id=workspace_id, workflow_run=workflow_run, shim=shim, contract=contract, folder=folder)
    hook_signer = _start_signer(state, device_creds, context, session_key, folder, http)
    extra = session_extra(state=state, device_creds=device_creds, context=context, policy=policy, settings=settings,
                          trailer=trailer, base_url=base_url, session_key=session_key, workspace_id=workspace_id,
                          workflow_run=workflow_run, shim=shim, engine=engine, profile=profile,
                          seat_credential=seat_credential)
    return PreparedSession(session_key=session_key, cli_path=claude, settings_path=settings_path, mcp_path=mcp_path,
                           env=env, profile=profile, model=model, signer=hook_signer, extra=extra)


__all__ = [
    "PreparedSession",
    "SessionRefusedError",
    "prepare_session",
]
