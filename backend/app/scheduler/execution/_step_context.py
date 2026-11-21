from __future__ import annotations

import json
import re
from typing import Any


def resolve_field(ref: str, context: dict[str, Any], step_result_type: type) -> Any:
    parts = ref.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, step_result_type):
            current = getattr(current, part, None)
        else:
            return None
        if current is None:
            return None
    return current


_EXACT_REF_RE = re.compile(r"^\s*\{\{([^}]+)\}\}\s*$")


def render_template_str(template: str, context: dict[str, Any], step_result_type: type) -> str:
    def _replace(match: re.Match[str]) -> str:
        ref = match.group(1).strip()
        value = resolve_field(ref, context, step_result_type)
        return str(value) if value is not None else match.group(0)

    return re.sub(r"\{\{([^}]+)\}\}", _replace, template)


def render_template_value(value: Any, context: dict[str, Any], step_result_type: type) -> Any:
    if isinstance(value, str):
        exact_match = _EXACT_REF_RE.match(value)
        if exact_match:
            resolved = resolve_field(exact_match.group(1).strip(), context, step_result_type)
            return value if resolved is None else resolved
        return render_template_str(value, context, step_result_type)
    if isinstance(value, list):
        return [render_template_value(item, context, step_result_type) for item in value]
    if isinstance(value, dict):
        return {key: render_template_value(item, context, step_result_type) for key, item in value.items()}
    return value


def render_template_params(params: dict[str, Any], context: dict[str, Any], step_result_type: type) -> dict[str, Any]:
    return {key: render_template_value(value, context, step_result_type) for key, value in params.items()}


def build_step_prompt(
    step: Any,
    context: dict[str, Any],
    step_result_type: type,
    item: Any = None,
) -> str:
    lines: list[str] = [
        f"# Task: {context.get('task_name', '')}",
        f"## Step {step.position}: {step.name}",
    ]

    if step.instructions:
        lines.append(f"\n### Instructions\n{step.instructions}")

    ctx_data: dict[str, Any] = {}
    for field_ref in step.context_fields:
        value = resolve_field(field_ref, context, step_result_type)
        if value is not None:
            ctx_data[field_ref] = value

    if ctx_data:
        lines.append("\n### Context from previous steps")
        lines.append(json.dumps(ctx_data, ensure_ascii=False, default=str, indent=2))

    if item is not None:
        lines.append("\n### Item to process")
        lines.append(json.dumps(item, ensure_ascii=False, default=str, indent=2))

    return "\n".join(lines)


def extract_items_for_spawn(step: Any, context: dict[str, Any], step_result_type: type) -> list[Any]:
    for ref in step.context_fields:
        value = resolve_field(ref, context, step_result_type)
        if isinstance(value, list) and value:
            return value

    for pos_key in sorted(context.get("steps", {}).keys(), key=int, reverse=True):
        step_result = context["steps"][pos_key]
        if step_result.step_type == "connector_fetch" and step_result.status == "success":
            items = step_result.output.get("new_items") or step_result.output.get("results") or []
            if items:
                return items

    return []
