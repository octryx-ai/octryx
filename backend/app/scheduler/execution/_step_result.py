"""The result of one task step: its status, output, sessions and fix attempts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    step_id: str
    position: int
    name: str
    step_type: str
    status: str  # success | error | skipped
    output: dict = field(default_factory=dict)
    error: str | None = None
    fix_attempts: int = 0
    session_ids: list[str] = field(default_factory=list)
    #Typed explicit refusal, e.g. an agent definition the platform cannot
    #: execute. Identifiers and codes only, so it is safe in the persisted step log.
    refusal: dict | None = None

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "position": self.position,
            "name": self.name,
            "step_type": self.step_type,
            "status": self.status,
            "error": self.error,
            "fix_attempts": self.fix_attempts,
            "session_ids": self.session_ids,
            "refusal": self.refusal,
            # keep output lightweight in the log
            "output_keys": list(self.output.keys()) if self.output else [],
        }
