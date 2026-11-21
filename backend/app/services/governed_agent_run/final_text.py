"""Drive a governed harness run to its final answer."""

from __future__ import annotations

from typing import Any

from .refusals import RunRefusal, failed


async def harness_final_text(runtime: Any, task: str) -> str:
    """The run's final text; any failure of the run itself is ``agent_runtime_error``."""
    try:
        output = await runtime.run(task)
    except RunRefusal:
        raise
    except Exception as exc:  # noqa: BLE001 - the run's own errors stay behind the harness boundary
        raise failed("agent_runtime_error") from exc
    if not isinstance(output, str):
        raise failed("agent_runtime_error")
    return output


__all__ = ["harness_final_text"]
