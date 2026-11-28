"""Explicit non-success outcomes of a governed agent run: ``failed``, ``needs_configuration``, ``denied``."""

from __future__ import annotations

from decimal import Decimal

STATUS_FAILED = "failed"
STATUS_NEEDS_CONFIGURATION = "needs_configuration"
STATUS_DENIED = "denied"


class RunRefusal(Exception):  # noqa: N818 - a control-flow outcome, not an error
    def __init__(
        self,
        status: str,
        error_code: str,
        *,
        cost_usd: Decimal = Decimal("0"),
        tokens_in: int = 0,
        tokens_out: int = 0,
        detail: str = "",
    ) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code
        self.detail = detail
        self.cost_usd = cost_usd
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


def failed(code: str, *, detail: str = "") -> RunRefusal:
    return RunRefusal(STATUS_FAILED, code, detail=detail)


def needs_configuration(code: str) -> RunRefusal:
    return RunRefusal(STATUS_NEEDS_CONFIGURATION, code)


def denied(code: str) -> RunRefusal:
    return RunRefusal(STATUS_DENIED, code)


__all__ = ["RunRefusal", "denied", "failed", "needs_configuration"]
