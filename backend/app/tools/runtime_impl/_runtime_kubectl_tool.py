"""The ``run_kubectl`` tool: read-only kubectl with the project's kubeconfig, context and namespace."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.change_preview import build_command_change_preview
from ...services.execution_runtime import workspace_mount_for_path
from ...services.process_output_redaction import redact_process_output
from ..kubernetes_kubectl_argv import NAMESPACE_OUT_OF_SCOPE, kubectl_is_read_only, kubectl_scope_refusal
from ..kubernetes_kubectl_flags import READ_LEAVES
from ._runtime_cli_helpers import _resolve_tool_path, _truncate, _workspace_root
from ._runtime_command_policy import _policy_block_result
from ._runtime_execution_resolution import _resolve_execute_with_runtime, _resolve_runtime_execution_config

# Inside a container runtime a kubeconfig outside the workspace is mounted read-only at this path.
_KUBECONFIG_MOUNT_PATH = "/runtime-mounts/kubeconfig"


def _validate_kubectl_args(args: list[str]) -> tuple[bool, str]:
    """``run_kubectl`` runs read-only kubectl commands only; ``(ok, error_message)``. Secret contents,
    ConfigMap data and template formats on resources with containers are refused like in the Kubernetes tools."""
    from ..kubernetes_env_mask import kubectl_env_template_refusal
    from ..kubernetes_kubectl_argv import kubectl_secret_read_refusal

    if kubectl_is_read_only(args):
        refusal = kubectl_secret_read_refusal(args) or kubectl_env_template_refusal(args)
        if refusal:
            return False, refusal
        return True, ""
    shown = " ".join(args[:2]) or "(none)"
    return False, (
        f"kubectl command '{shown}' is not a read-only kubectl command; run_kubectl runs only "
        f"{', '.join(sorted(READ_LEAVES))}, with their read options and no connection overrides. "
        "A change to the cluster needs its own governed tool with an approval."
    )


def _kubectl_command_args(args: Any) -> list[str]:
    if isinstance(args, str):
        return shlex.split(args)
    return [str(arg) for arg in (args or [])]


async def _alert_scope_refusal(
    params: dict, context: ToolContext, command_args: list[str]
) -> tuple[dict[str, Any] | None, str | None]:
    """Under a run's alert scope only the target's namespace, and no Secret read: ``(refusal, scoped_namespace)``."""
    from ..alert_scope import run_alert_scope

    scope = await run_alert_scope(context)
    scoped_namespace = scope.namespace if scope is not None else None
    if scoped_namespace:
        requested = str(params.get("namespace") or "").strip()
        refusal = kubectl_scope_refusal(command_args, namespace=scoped_namespace) or (
            NAMESPACE_OUT_OF_SCOPE if requested and requested != scoped_namespace else None)
        if refusal:
            return {"error": refusal, "code": refusal, "command": command_args,
                    "scope_namespace": scoped_namespace}, scoped_namespace
    return None, scoped_namespace


def _kubeconfig_mounts(command: list[str], kubeconfig_path: Any, workspace_root: Path) -> list[Any]:
    """Mount a kubeconfig outside the workspace read-only and point ``--kubeconfig`` at the mount (in place)."""
    mounts = []
    if kubeconfig_path:
        kubeconfig_resolved = Path(str(kubeconfig_path)).expanduser()
        if not kubeconfig_resolved.is_absolute():
            kubeconfig_resolved = (workspace_root / kubeconfig_resolved).resolve()
        else:
            kubeconfig_resolved = kubeconfig_resolved.resolve()
        if workspace_root not in kubeconfig_resolved.parents and kubeconfig_resolved != workspace_root:
            mounts.append(
                workspace_mount_for_path(
                    host_path=kubeconfig_resolved,
                    container_path=_KUBECONFIG_MOUNT_PATH,
                    read_only=True,
                )
            )
            kubeconfig_index = command.index("--kubeconfig") + 1
            command[kubeconfig_index] = _KUBECONFIG_MOUNT_PATH
    return mounts


def _kubectl_runtime_result(runtime_result: Any, *, command: list[str], command_args: list[str],
                            timeout_sec: int) -> dict[str, Any]:
    # A timeout or an unavailable runtime carries runtime/exception text in stderr: fixed facts only.
    if runtime_result.timed_out:
        return {
            "error": f"kubectl_timed_out timeout_sec={timeout_sec}",
            "error_code": "kubectl_timed_out",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }
    if runtime_result.exit_code is None:
        return {
            "error": "kubectl_not_started",
            "error_code": "kubectl_not_started",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }

    # The output of the kubectl command the agent ran is its product result: kept, redacted.
    from ..kubernetes_env_mask import mask_kubectl_output

    stdout_text = _truncate(redact_process_output(mask_kubectl_output(command_args, runtime_result.stdout)))
    stderr_text = _truncate(redact_process_output(runtime_result.stderr))
    return {
        "command": command,
        "exit_code": runtime_result.exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "execution_runtime": runtime_result.metadata,
    }


class RunKubectlCommandTool:
    name = "run_kubectl"
    description = "Run kubectl with the configured kubeconfig/context for the active project."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        command_args = _kubectl_command_args(params.get("args"))
        command = [_resolve_tool_path(context, context.project_config.get("kubectl_path")) or "kubectl"]
        namespace = params.get("namespace") or context.project_config.get("k8s_namespace")
        if namespace:
            command.extend(["-n", str(namespace)])
        command.extend(command_args)
        preview = build_command_change_preview(self.name, command, cwd=str(_workspace_root(context)))
        preview["namespace"] = str(namespace or "")
        return preview

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        args = params.get("args")
        if not args:
            return {"error": "args is required"}
        command_args = _kubectl_command_args(args)

        # Validate the kubectl subcommand before execution
        ok, msg = _validate_kubectl_args(command_args)
        if not ok:
            return {"error": msg, "command": command_args}
        scope_refusal, scoped_namespace = await _alert_scope_refusal(params, context, command_args)
        if scope_refusal is not None:
            return scope_refusal

        runtime_config = await _resolve_runtime_execution_config()(
            context.db,
            project_config=context.project_config,
        )
        if runtime_config.provider == "docker":
            command = [str(context.project_config.get("kubectl_container_path") or "kubectl").strip() or "kubectl"]
        else:
            command = [_resolve_tool_path(context, context.project_config.get("kubectl_path")) or "kubectl"]
        kubeconfig_path = context.project_config.get("kubeconfig_path")
        k8s_context = context.project_config.get("k8s_context")
        namespace = scoped_namespace or params.get("namespace") or context.project_config.get("k8s_namespace")
        if kubeconfig_path:
            # Path traversal check for kubeconfig_path — resolve and validate
            raw_kubeconfig = str(kubeconfig_path).strip()
            if ".." in raw_kubeconfig:
                return {"error": "kubeconfig_path may not contain path traversal sequences"}
            resolved_kubeconfig = _resolve_tool_path(
                context,
                raw_kubeconfig,
            ) or str(Path(raw_kubeconfig).expanduser())
            command.extend(["--kubeconfig", resolved_kubeconfig])
        if k8s_context:
            command.extend(["--context", str(k8s_context)])
        if namespace:
            command.extend(["-n", str(namespace)])
        command.extend(command_args)
        return await self._run(command, command_args, params, context, kubeconfig_path)

    async def _run(self, command: list[str], command_args: list[str], params: dict, context: ToolContext,
                   kubeconfig_path: Any) -> dict[str, Any]:
        blocked = await _policy_block_result(self.name, command, context)
        if blocked is not None:
            return blocked

        workspace_root = _workspace_root(context)
        mounts = _kubeconfig_mounts(command, kubeconfig_path, workspace_root)
        runtime_result = await _resolve_execute_with_runtime()(
            db=context.db,
            project_config=context.project_config,
            command=command,
            cwd=workspace_root,
            workspace_root=workspace_root,
            timeout_sec=int(params.get("timeout_sec") or 20),
            mounts=mounts,
            guard_foreign_build=False,  # the configured kubectl binary, read-only verbs only
        )
        timeout_sec = int(params.get("timeout_sec") or 20)
        return _kubectl_runtime_result(runtime_result, command=command, command_args=command_args,
                                       timeout_sec=timeout_sec)


__all__ = [name for name in vars() if not name.startswith("_")]
