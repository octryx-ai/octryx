"""The typed refusal of an Action's workflow phase that cannot run its turn."""

from __future__ import annotations

from .action_admission import ActionAdmissionError


class WorkflowPhasePreparationError(ActionAdmissionError):
    def __init__(self, code: str, *, reason: str | None = None) -> None:
        super().__init__(code)
        self.reason = reason

    def as_metadata(self) -> dict[str, str]:
        result = {"code": self.code, "message": "The Action's workflow phase could not prepare its turn."}
        if self.reason:
            result["reason"] = self.reason
        return result


__all__ = ["WorkflowPhasePreparationError"]
