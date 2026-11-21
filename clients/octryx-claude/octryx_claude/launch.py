"""The launcher: one governed Claude Code session through Octryx.

Everything is per session: the model env and headers here, the generated settings and MCP config
(``launch_settings``), the OS sandbox (``launch_sandbox``) and the process argv and environment lists
(``launch_process``). ``CLAUDE_CONFIG_DIR`` points at the octryx state, so ``~/.claude`` and plain ``claude``
are never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import model_picker
from .launch_process import (
    PROFILE_GOVERNED,
    PROVIDER_SWITCHES,
    SCRUBBED_ENV,
    LaunchRefusedError,
)
from .launch_sandbox import (
    TEST_RUN_SHIM_ENV,
)
from .launch_settings import (
    _policy_rules,
)
from .platform import (
    ENV_BASE_URL,
    ENV_PROFILE,
    ENV_SESSION_KEY,
    ENV_WORK_ITEM,
    ENV_WORKFLOW_RUN,
    ENV_WORKSPACE_ID,
    HEADER_SESSION,
    HEADER_WORK_ITEM,
    HEADER_WORKFLOW_RUN,
    HEADER_WORKSPACE,
)
from .state import HOME_ENV

MODEL_GATEWAY_PATH = "/api/v1/model-gateway/anthropic"
# ``--profile seat``: Claude Code's own subscription login, model calls through the gateway's seat
# route to Anthropic. The Octryx identity is the session-bound seat credential in a custom header.
SEAT_MODEL_GATEWAY_PATH = f"{MODEL_GATEWAY_PATH}/seat"
HEADER_SEAT_CREDENTIAL = "X-Octryx-Seat-Credential"
_SEAT_CREDENTIAL = re.compile(r"^[A-Za-z0-9_-]{40,200}$")
# octryx-claude sessions use Sonnet and Opus only; Sonnet also serves Claude Code's small/fast background calls,
# and the main model defaults to Opus.
DEFAULT_ALIASES = {"main": "claude-opus-5-5", "opus": "claude-opus-5-5", "small_fast": "claude-sonnet-5"}
API_KEY_HELPER_TTL_MS = 10 * 60 * 1000


def custom_headers(session_key: str, workspace_id: str, work_item: str, seat_credential: str = "",
                   workflow_run: str = "") -> str:
    """``ANTHROPIC_CUSTOM_HEADERS``: newline-separated ``Name: value`` pairs."""
    lines = [f"{HEADER_SESSION}: {session_key}", f"{HEADER_WORKSPACE}: {workspace_id}"]
    if work_item:
        lines.append(f"{HEADER_WORK_ITEM}: {work_item}")
    if workflow_run:
        lines.append(f"{HEADER_WORKFLOW_RUN}: {workflow_run}")
    if seat_credential:
        lines.append(f"{HEADER_SEAT_CREDENTIAL}: {seat_credential}")
    return "\n".join(lines)


def valid_seat_credential(value: object) -> bool:
    """A credential as the platform mints it (URL-safe base64); anything else is never put into a header."""
    return isinstance(value, str) and bool(_SEAT_CREDENTIAL.match(value))


def model_env(*, base_url: str, session_key: str, workspace_id: str, work_item: str,
              aliases: Mapping[str, str], seat_credential: str = "", workflow_run: str = "") -> dict[str, str]:
    """The model env of the child. With ``seat_credential`` the session runs the ``seat`` profile."""
    main = str(aliases.get("main") or DEFAULT_ALIASES["main"])
    small = str(aliases.get("small_fast") or DEFAULT_ALIASES["small_fast"])
    opus = str(aliases.get("opus") or DEFAULT_ALIASES["opus"])
    path = SEAT_MODEL_GATEWAY_PATH if seat_credential else MODEL_GATEWAY_PATH
    env = {
        "ANTHROPIC_BASE_URL": f"{base_url}{path}",
        "ANTHROPIC_CUSTOM_HEADERS": custom_headers(session_key, workspace_id, work_item, seat_credential,
                                                   workflow_run),
        "ANTHROPIC_MODEL": main,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": main,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": opus,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": small,
        "ANTHROPIC_SMALL_FAST_MODEL": small,
        "CLAUDE_CODE_SUBAGENT_MODEL": main,
        "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": str(API_KEY_HELPER_TTL_MS),
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
    }
    if seat_credential:
        # No apiKeyHelper in seat mode: the subscription login owns Authorization.
        env.pop("CLAUDE_CODE_API_KEY_HELPER_TTL_MS")
        # Seat sessions reach Anthropic itself through the seat proxy, so Claude Code keeps its betas there. The
        # governed route keeps stripping them: LiteLLM and the company models reject unknown betas.
        env.pop("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS")
    env.update(model_picker.discovery_env(seat=bool(seat_credential)))
    env.update({name: "" for name in PROVIDER_SWITCHES})
    # A workflow run's turns keep Claude Code's own compaction: a forced small window compacts again and again and
    # loses the planning each time.
    return env


def run_attribution(model: str, contract: Mapping[str, Any] | None) -> dict[str, str]:
    """Claude Code's commit attribution for a workflow run's session: the AI-output trailers (EU AI Act Art. 50(2),
    ) instead of Claude Code's own; pull requests are written by the platform, which marks them."""
    run = dict((contract or {}).get("run") or {}) if isinstance((contract or {}).get("run"), Mapping) else {}
    key = re.sub(r"[^A-Za-z0-9._-]", "", str(run.get("ticket_key") or run.get("id") or ""))[:40]
    name = re.sub(r"[^A-Za-z0-9._:/-]", "", str(model or "unknown"))[:80] or "unknown"
    lines = [f"AI-Generated-By-octryx: {name}"] + ([f"Octryx-Run: {key}"] if key else [])
    return {"commit": "\n".join(lines), "pr": ""}




def build_child_env(parent: Mapping[str, str], *, model: Mapping[str, str], state_root: Path,
                    claude_config_dir: Path, base_url: str, session_key: str, workspace_id: str,
                    work_item: str, profile: str = PROFILE_GOVERNED, workflow_run: str = "",
                    shim: Path | None = None) -> dict[str, str]:
    dropped = set(SCRUBBED_ENV) | set(PROVIDER_SWITCHES)
    env = {k: v for k, v in parent.items() if k not in dropped}
    # Provider switches stay unset in the process; the settings env blanks them.
    env.update({k: v for k, v in model.items() if k not in dropped})
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(claude_config_dir),
            HOME_ENV: str(state_root),
            ENV_BASE_URL: base_url,
            ENV_SESSION_KEY: session_key,
            ENV_WORKSPACE_ID: workspace_id,
            ENV_PROFILE: profile,
        }
    )
    if work_item:
        env[ENV_WORK_ITEM] = work_item
    else:
        env.pop(ENV_WORK_ITEM, None)
    if workflow_run:
        env[ENV_WORKFLOW_RUN] = workflow_run
    else:
        env.pop(ENV_WORKFLOW_RUN, None)
    if shim is not None:
        env[TEST_RUN_SHIM_ENV] = str(shim)  # the hook wraps a test run for exactly this excludedCommands entry
    from . import tools  # noqa: PLC0415

    # The tools the style gate runs (ruff, ast-grep, gitleaks …) are the agent's too, so it can fix what the gate
    # names (attempt 4, "ruff format" was red and the session had no ruff). Last on PATH: the project's
    # own interpreters and tools come first.
    known = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
    env["PATH"] = os.pathsep.join([*known, *[item for item in tools.bin_dirs(state_root) if item not in known]])
    return env


# Where Claude Code's installers put ``claude``; a background service (launchd, systemd, a logon task) starts
# with a minimal PATH, so these are searched after PATH.
CLAUDE_FALLBACK_DIRS = (
    "~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin", "/usr/bin",
)


def resolve_claude() -> str:
    explicit = os.environ.get("OCTRYX_CLAUDE_EXECUTABLE", "").strip()
    found = explicit or shutil.which("claude") or ""
    if not found:
        fallback_path = os.pathsep.join(os.path.expanduser(item) for item in CLAUDE_FALLBACK_DIRS)
        found = shutil.which("claude", path=fallback_path) or ""
    if not found:
        raise LaunchRefusedError("claude_not_found")
    return found


def policy_summary(policy: Mapping[str, Any]) -> str:
    verification = policy.get("verification")
    verification_state = verification.get("state") if isinstance(verification, Mapping) else None
    return json.dumps(
        {
            "policy_source": policy.get("policy_source"),
            "deny_rules": len(_policy_rules(policy, "deny")),
            "ask_rules": len(_policy_rules(policy, "ask")),
            "verification": verification_state,
        }
    )


__all__ = [
    "API_KEY_HELPER_TTL_MS",
    "CLAUDE_FALLBACK_DIRS",
    "DEFAULT_ALIASES",
    "HEADER_SEAT_CREDENTIAL",
    "build_child_env",
    "custom_headers",
    "model_env",
    "policy_summary",
    "resolve_claude",
    "run_attribution",
    "valid_seat_credential",
]
