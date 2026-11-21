"""The run contract's "tools to call" in Codex's own names (Codex as second engine).

The contract tells a device model which tools to call (``phase.tools.on_device``) in Claude Code's names (``Write``,
``Read``, ``mcp__octryx-knowledge__*``). Codex has none of them: it reads with the shell, changes files
with ``apply_patch`` and sees the platform's MCP tools as ``mcp__octryx_knowledge__*`` (without this the model
looks for ``write_workspace_file`` and loops). The evidence side maps Codex's calls back in the gateway
(``model_gateway.inbound.openai_view.evidence_names``).
"""

from __future__ import annotations

_ON_DEVICE = {"Read": "shell (cat, sed -n, head)", "Grep": "shell (rg, grep)", "Glob": "shell (find, ls)",
              "LS/Glob": "shell (ls, find)", "LS": "shell (ls)", "Write": "apply_patch", "Edit": "apply_patch",
              "MultiEdit/Edit": "apply_patch", "Bash": "shell"}
CLAUDE_MCP_PREFIX = "mcp__octryx-knowledge__"
CODEX_MCP_PREFIX = "mcp__octryx_knowledge__"
# Without an apply_patch tool (a model Codex does not know, e.g. Gemma 4) the model writes with the
# shell helper; it guesses JSON arguments and "*** Create File" until the run pauses. The exact form goes along.


def codex_on_device(names: list[str]) -> list[str]:
    """The contract's ``on_device`` list in Codex's own tool names."""
    out: list[str] = []
    for item in names:
        if item.startswith(CLAUDE_MCP_PREFIX):
            out.append(CODEX_MCP_PREFIX + item.removeprefix(CLAUDE_MCP_PREFIX))
            continue
        native, _, rest = item.partition(" (")
        mapped = _ON_DEVICE.get(native)
        out.append(f"{mapped} ({rest}" if mapped and rest else mapped or item)
    return out


__all__ = ["codex_on_device"]
