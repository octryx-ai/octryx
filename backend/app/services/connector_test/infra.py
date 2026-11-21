from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.services.connector_test.failure import command_failure, connection_success, runtime_facts
from app.services.connector_test.runtime import binary_is_available_for_runtime, run_runtime_probe

ResolveRuntimeConfigFn = Callable[..., Awaitable[Any]]
ExecuteWithRuntimeFn = Callable[..., Awaitable[Any]]
WhichFn = Callable[[str], str | None]


def _resolve_workspace_target(configured_root: str, workspace_root: Path) -> Path:
    if not configured_root:
        return workspace_root
    configured_path = Path(configured_root)
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (workspace_root / configured_path).resolve()


def _validate_workspace_target(root: Path, workspace_root: Path, *, field_name: str) -> dict[str, Any] | None:
    if workspace_root not in root.parents and root != workspace_root:
        return {"ok": False, "summary": f"{field_name} must stay inside the workspace root."}
    if not root.exists():
        return {"ok": False, "summary": f"{field_name} does not exist."}
    return None


def _probe_failure(service: str, returncode: int, runtime_meta: Any) -> dict[str, Any]:
    return {**command_failure(service, returncode), "execution_runtime": runtime_facts(runtime_meta)}


async def test_terraform_connection(
    config: dict[str, Any],
    *,
    resolve_runtime_config_fn: ResolveRuntimeConfigFn,
    execute_with_runtime_fn: ExecuteWithRuntimeFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    workspace_root = Path.cwd().resolve()
    configured_root = str(config.get("terraform_root") or "").strip()
    binary = str(
        config.get("terraform_binary") or ("tofu" if config.get("terraform_use_opentofu") else "terraform")
    ).strip()
    if not binary:
        return {"ok": False, "summary": "terraform_binary is required."}
    if not await binary_is_available_for_runtime(
        config,
        binary,
        resolve_runtime_config_fn=resolve_runtime_config_fn,
        which_fn=which_fn,
    ):
        return {"ok": False, "summary": "The configured terraform_binary is not available on PATH."}
    root = _resolve_workspace_target(configured_root, workspace_root)
    invalid = _validate_workspace_target(root, workspace_root, field_name="terraform_root")
    if invalid:
        return invalid
    env = dict(os.environ)
    plugin_cache_dir = str(config.get("terraform_plugin_cache_dir") or "").strip()
    if plugin_cache_dir:
        env["TF_PLUGIN_CACHE_DIR"] = plugin_cache_dir
    returncode, stdout, _stderr, runtime_meta = await run_runtime_probe(
        config=config,
        command=[binary, "version", "-json"],
        cwd=root,
        env=env,
        execute_with_runtime_fn=execute_with_runtime_fn,
    )
    if returncode != 0:
        return _probe_failure("Terraform", returncode, runtime_meta)
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    version = payload.get("terraform_version") or payload.get("opentofu_version")
    return connection_success("Terraform probe succeeded.", version=version, execution_runtime=runtime_meta)


async def test_ldap_connection(
    config: dict[str, Any],
    *,
    resolve_runtime_config_fn: ResolveRuntimeConfigFn,
    execute_with_runtime_fn: ExecuteWithRuntimeFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    server_url = str(config.get("ldap_server_url") or "").strip()
    base_dn = str(config.get("ldap_base_dn") or "").strip()
    binary = str(config.get("ldapsearch_binary") or "ldapsearch").strip()
    if not server_url or not base_dn:
        return {"ok": False, "summary": "ldap_server_url and ldap_base_dn are required."}
    if not binary:
        return {"ok": False, "summary": "ldapsearch_binary is required."}
    if not await binary_is_available_for_runtime(
        config,
        binary,
        resolve_runtime_config_fn=resolve_runtime_config_fn,
        which_fn=which_fn,
    ):
        return {"ok": False, "summary": "The configured ldapsearch_binary is not available on PATH."}
    returncode, _stdout, _stderr, runtime_meta = await run_runtime_probe(
        config=config,
        command=[binary, "-VVV"],
        cwd=Path.cwd().resolve(),
        execute_with_runtime_fn=execute_with_runtime_fn,
    )
    if returncode != 0:
        return _probe_failure("LDAP", returncode, runtime_meta)
    # ``-VVV`` only proves the client runs; its banner line is tool text and is never kept.
    return connection_success("LDAP client probe succeeded.", execution_runtime=runtime_meta)


async def test_ansible_connection(
    config: dict[str, Any],
    *,
    resolve_runtime_config_fn: ResolveRuntimeConfigFn,
    execute_with_runtime_fn: ExecuteWithRuntimeFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    inventory_path = str(config.get("ansible_inventory_path") or "").strip()
    binary = str(config.get("ansible_inventory_binary") or "ansible-inventory").strip()
    workspace_root = Path.cwd().resolve()
    if not inventory_path:
        return {"ok": False, "summary": "ansible_inventory_path is required."}
    if not binary:
        return {"ok": False, "summary": "ansible_inventory_binary is required."}
    if not await binary_is_available_for_runtime(
        config,
        binary,
        resolve_runtime_config_fn=resolve_runtime_config_fn,
        which_fn=which_fn,
    ):
        return {"ok": False, "summary": "The configured ansible_inventory_binary is not available on PATH."}
    candidate = Path(inventory_path)
    resolved_inventory = (workspace_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    invalid = _validate_workspace_target(resolved_inventory, workspace_root, field_name="ansible_inventory_path")
    if invalid:
        return invalid
    returncode, stdout, _stderr, runtime_meta = await run_runtime_probe(
        config=config,
        command=[binary, "-i", str(resolved_inventory), "--list", "--json"],
        cwd=workspace_root,
        execute_with_runtime_fn=execute_with_runtime_fn,
    )
    if returncode != 0:
        return _probe_failure("Ansible", returncode, runtime_meta)
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    groups = [key for key, value in payload.items() if isinstance(value, dict) and key not in {"_meta"}]
    return connection_success(
        "Connected to Ansible inventory.", counts={"groups": len(groups)}, execution_runtime=runtime_meta
    )


async def test_helm_connection(
    config: dict[str, Any],
    *,
    resolve_runtime_config_fn: ResolveRuntimeConfigFn,
    execute_with_runtime_fn: ExecuteWithRuntimeFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    workspace_root = Path.cwd().resolve()
    configured_root = str(config.get("helm_workspace_root") or "").strip()
    binary = str(config.get("helm_binary") or "helm").strip()
    if not binary:
        return {"ok": False, "summary": "helm_binary is required."}
    if not await binary_is_available_for_runtime(
        config,
        binary,
        resolve_runtime_config_fn=resolve_runtime_config_fn,
        which_fn=which_fn,
    ):
        return {"ok": False, "summary": "The configured helm_binary is not available on PATH."}
    root = _resolve_workspace_target(configured_root, workspace_root)
    invalid = _validate_workspace_target(root, workspace_root, field_name="helm_workspace_root")
    if invalid:
        return invalid
    env = dict(os.environ)
    kubeconfig = str(config.get("helm_kubeconfig") or "").strip()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    returncode, stdout, _stderr, runtime_meta = await run_runtime_probe(
        config=config,
        command=[binary, "version", "--short"],
        cwd=root,
        env=env,
        execute_with_runtime_fn=execute_with_runtime_fn,
    )
    if returncode != 0:
        return _probe_failure("Helm", returncode, runtime_meta)
    # ``--short`` prints ``v3.14.0+g3fc9f4b``: the semver build metadata after ``+`` is cut, and the
    # rest must still pass the strict validator, so any other output yields no version.
    output = (stdout or "").strip()
    return connection_success(
        "Helm probe succeeded.", version=output.split("+", 1)[0], execution_runtime=runtime_meta
    )
