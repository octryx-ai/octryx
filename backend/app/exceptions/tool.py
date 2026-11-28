"""Tool and provider-level exceptions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .base import OctryxError


class ToolExecutionError(OctryxError):
    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(f"Tool '{tool_name}' failed: {message}")
        self.tool_name = tool_name


class ProviderError(OctryxError):
    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"Provider '{provider}': {message}")
        self.provider = provider


class BudgetLimitExceededError(OctryxError):
    def __init__(
        self,
        *,
        policy_name: str,
        metric_name: str,
        projected_value: Decimal,
        limit_value: Decimal,
        threshold_level: str,
    ) -> None:
        from decimal import ROUND_HALF_UP

        def _fmt(value: Decimal) -> str:
            return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        super().__init__(
            f"Budget policy '{policy_name}' exceeded for {metric_name}: "
            f"projected {_fmt(projected_value)} versus limit {_fmt(limit_value)} ({threshold_level})."
        )
        self.policy_name = policy_name
        self.metric_name = metric_name
        self.projected_value = projected_value
        self.limit_value = limit_value
        self.threshold_level = threshold_level
        self.runtime_attempts: list[dict[str, Any]] = []
