"""Runtime environment prompt helpers for stable full-prompt assembly."""

from __future__ import annotations


def build_runtime_environment_section(system_context: dict[str, object] | None) -> str:
    if not system_context:
        return ""

    binaries = system_context.get("available_binaries") or {}
    binary_lines = [f"- {name}: {path}" for name, path in binaries.items()]
    hints = system_context.get("command_hints") or {}
    binary_section = "\n".join(binary_lines) if binary_lines else "- Available binaries: none detected"
    return (
        "\n## Runtime Environment\n"
        f"- Operating system: {system_context.get('os_name')} {system_context.get('os_release')}\n"
        f"- Shell: {system_context.get('shell') or 'unknown'}\n"
        f"- Workspace root: {system_context.get('workspace_root')}\n"
        f"- Date command hint: {hints.get('recent_date', '-')}\n"
        f"- Platform note: {hints.get('notes', '-')}\n"
        f"{binary_section}"
    )
