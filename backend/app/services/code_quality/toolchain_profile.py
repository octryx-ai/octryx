from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.code_quality.repo_files import _deep_merge_dicts


def _runtime_toolchain_profile_from_project_config(
    *,
    project_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    resolution = config.get("engineering_knowledge_runtime_resolution")
    if not isinstance(resolution, dict):
        return {}
    prompt_contract = resolution.get("prompt_contract")
    pack = resolution.get("engineering_knowledge_pack")
    if not isinstance(prompt_contract, dict) or not isinstance(pack, dict):
        return {}
    policy = pack.get("toolchain_policy")
    if not isinstance(policy, dict):
        return {}
    stack_key = str(prompt_contract.get("stack_key") or "").strip()
    profiles = policy.get("profiles")
    if isinstance(profiles, dict):
        profile = profiles.get(stack_key) or profiles.get("default")
        if isinstance(profile, dict):
            return _sanitize_toolchain_profile(profile, pack=pack)
    default_profile = policy.get("default")
    if isinstance(default_profile, dict):
        return _sanitize_toolchain_profile(default_profile, pack=pack)
    return _sanitize_toolchain_profile(policy, pack=pack)


def _sanitize_toolchain_profile(profile: dict[str, Any], *, pack: dict[str, Any]) -> dict[str, Any]:
    reserved_keys = {"repo_root", "source", "project_override_applied"}
    sanitized = {key: value for key, value in profile.items() if key not in reserved_keys}
    if not sanitized:
        return {}
    sanitized["engineering_knowledge_pack_id"] = pack.get("pack_id")
    sanitized["engineering_knowledge_pack_version_id"] = pack.get("version_id")
    sanitized["engineering_knowledge_pack_key"] = pack.get("pack_key")
    return sanitized


def _finalize_code_quality_config(
    base_payload: dict[str, Any],
    *,
    project_config: dict[str, Any] | None,
    project_overrides: dict[str, Any],
    repo_local_config: bool,
) -> dict[str, Any]:
    toolchain_profile = _runtime_toolchain_profile_from_project_config(project_config=project_config)
    if toolchain_profile:
        merged = (
            _deep_merge_dicts(toolchain_profile, base_payload)
            if repo_local_config
            else _deep_merge_dicts(base_payload, toolchain_profile)
        )
        merged["engineering_knowledge_toolchain_profile_applied"] = True
    else:
        merged = dict(base_payload)
    if project_overrides:
        merged = _deep_merge_dicts(merged, project_overrides)
        merged["project_override_applied"] = True
    return merged


def _repo_quality_overrides_from_project_config(
    *,
    project_config: dict[str, Any] | None,
    repo_root: Path,
) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    raw_quality = config.get("repo_code_quality")
    if not isinstance(raw_quality, dict):
        return {}

    merged: dict[str, Any] = {}
    default_overrides = raw_quality.get("default")
    if isinstance(default_overrides, dict):
        merged = _deep_merge_dicts(merged, default_overrides)

    repo_entries = raw_quality.get("repos")
    if isinstance(repo_entries, dict):
        for key, override in repo_entries.items():
            if not isinstance(override, dict):
                continue
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            if normalized_key == repo_root.name or str(repo_root).endswith(normalized_key):
                merged = _deep_merge_dicts(merged, override)
    elif isinstance(repo_entries, list):
        for entry in repo_entries:
            if not isinstance(entry, dict):
                continue
            match_value = str(entry.get("match") or entry.get("repo") or entry.get("repo_slug") or "").strip()
            override = entry.get("config")
            if not match_value or not isinstance(override, dict):
                continue
            if match_value == repo_root.name or str(repo_root).endswith(match_value):
                merged = _deep_merge_dicts(merged, override)
    return merged
