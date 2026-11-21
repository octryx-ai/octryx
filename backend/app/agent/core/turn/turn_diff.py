"""Track turn-level side effects such as commands and file changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....tools.tool_names import ToolName


@dataclass
class TurnDiffTracker:
    commands: list[dict[str, Any]] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    policy_events: list[dict[str, Any]] = field(default_factory=list)

    def record_tool_call(self, tool_name: str, params: dict[str, Any], result: Any) -> None:
        if not isinstance(result, dict):
            return

        self._record_policy_event(tool_name, result)
        self._record_command(tool_name, result)
        self._record_file_change(tool_name, params, result)

    def _record_policy_event(self, tool_name: str, result: dict[str, Any]) -> None:
        action = result.get("exec_policy_action")
        if not action:
            return
        self.policy_events.append(
            {
                "tool_name": tool_name,
                "action": action,
                "reason": result.get("exec_policy_reason") or "",
                "risk_level": result.get("exec_policy_risk") or "",
                "approval_required": bool(result.get("approval_required")),
                "command": result.get("command") or "",
            }
        )

    def _record_command(self, tool_name: str, result: dict[str, Any]) -> None:
        if tool_name not in {"bash", "run_cli_command", "run_kubectl"}:
            return
        command_value = result.get("command")
        if isinstance(command_value, list):
            command_text = " ".join(str(part) for part in command_value)
        else:
            command_text = str(command_value or "").strip()
        if not command_text:
            return
        self.commands.append(
            {
                "tool_name": tool_name,
                "command": command_text,
                "cwd": result.get("cwd") or "",
                "exit_code": result.get("exit_code", result.get("returncode")),
                "status": "error" if result.get("error") else "success",
            }
        )

    def _record_file_change(self, tool_name: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        if tool_name == ToolName.WRITE_WORKSPACE_FILE and result.get("path"):
            self.file_changes.append(
                {
                    "path": result["path"],
                    "action": "write",
                    "bytes_written": result.get("bytes_written"),
                }
            )
            return

        if tool_name == ToolName.EDIT_WORKSPACE_FILE and result.get("path"):
            self.file_changes.append(
                {
                    "path": result["path"],
                    "action": "update",
                    "lines_delta": result.get("lines_delta"),
                    "strategy": result.get("strategy"),
                }
            )
            return

        if tool_name == ToolName.MULTI_EDIT_WORKSPACE_FILE and result.get("path"):
            self.file_changes.append(
                {
                    "path": result["path"],
                    "action": "update",
                    "edits_applied": result.get("edits_applied"),
                }
            )
            return

        if tool_name == ToolName.APPLY_PATCH_WORKSPACE:
            for entry in result.get("files") or []:
                path = entry.get("path")
                if not path:
                    continue
                self.file_changes.append(
                    {
                        "path": path,
                        "action": entry.get("action") or "update",
                    }
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_count": len(self.commands),
            "file_change_count": len(self.file_changes),
            "policy_event_count": len(self.policy_events),
            "commands": list(self.commands),
            "file_changes": list(self.file_changes),
            "policy_events": list(self.policy_events),
        }
