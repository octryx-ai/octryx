"""AWS evidence salvage for runs that exhaust their loop budget.

Connector-owned: the loop core calls this through the generic salvage hook in
``app.agent.loops.control._loop_salvage_hooks`` and carries no AWS knowledge
itself.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .aws_evidence_summaries import summarize_tool_result

_AWS_TERMS = (
    "aws",
    "bedrock",
    "cloudtrail",
    "cloudwatch",
    "codepipeline",
    "ec2",
    "eks",
    "iam",
    "lambda",
    "rds",
    "s3",
    "security group",
    "subnet",
    "vpc",
    "waf",
)


def _tool_value(tool_call: Any, key: str, default: Any = None) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(key, default)
    return getattr(tool_call, key, default)


def _tool_name(tool_call: Any) -> str:
    return str(_tool_value(tool_call, "tool_name", "") or "").strip()


def _tool_status(tool_call: Any) -> str:
    result = _tool_value(tool_call, "result", None)
    explicit_status = str(_tool_value(tool_call, "status", "") or "").strip().lower()
    if explicit_status:
        return explicit_status
    if isinstance(result, dict):
        return "error" if result.get("error") else "success"
    return "unknown"


def _tool_result(tool_call: Any) -> Any:
    return _tool_value(tool_call, "result", None)


def _tool_parameters(tool_call: Any) -> dict[str, Any]:
    value = _tool_value(tool_call, "parameters", None)
    if not isinstance(value, dict):
        value = _tool_value(tool_call, "params", None)
    return value if isinstance(value, dict) else {}


def _is_aws_request(user_request: str) -> bool:
    text = str(user_request or "").lower()
    return any(term in text for term in _AWS_TERMS)


def _is_aws_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return lowered.startswith("aws_") or "_aws_" in lowered or lowered.startswith(("list_aws_", "get_aws_"))


def build_runtime_salvage_aws_evidence_message(
    *,
    user_request: str,
    recent_tool_calls: list[Any],
) -> str:
    if not _is_aws_request(user_request):
        return ""

    aws_calls = [tool_call for tool_call in recent_tool_calls if _is_aws_tool(_tool_name(tool_call))]
    if not aws_calls:
        return ""

    chronological_calls = list(reversed(aws_calls))
    successes = [tool_call for tool_call in chronological_calls if _tool_status(tool_call) in {"success", "ok"}]
    failures = [tool_call for tool_call in chronological_calls if tool_call not in successes]
    status_counts = Counter(f"{_tool_name(tool_call)}:{_tool_status(tool_call)}" for tool_call in chronological_calls)

    lines = [
        "The run reached its AWS tool budget or tool-iteration limit before a safe model synthesis.",
        "AWS evidence gathered before the stop (only captured tool-result fields, no inferred values):",
    ]
    for tool_call in successes[:24]:
        summary = summarize_tool_result(_tool_name(tool_call), _tool_result(tool_call), _tool_parameters(tool_call))
        if summary:
            lines.append(f"- {summary}")

    if failures:
        lines.append("AWS calls that did not complete successfully or were budget-blocked:")
        for key, count in sorted(status_counts.items()):
            if key.endswith(":success") or key.endswith(":ok"):
                continue
            lines.append(f"- {key}: {count}")

    lines.append(
        "Treat this as a partial evidence report. Missing services or fields are unknown, not healthy or unhealthy. "
        "Do not infer operational conclusions from naming patterns or failed follow-up calls."
    )
    lines.append(
        "Residual risk: AWS domains not listed above, fields omitted by compact tool results, denied calls, and "
        "duplicate/budget-stopped follow-up checks still require targeted validation before making operational claims."
    )
    return "\n".join(lines)


__all__ = ["build_runtime_salvage_aws_evidence_message"]
