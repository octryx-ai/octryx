"""The work item fields a field condition of a decision can compare."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.secure_work import WorkItem

KIND_ENUM, KIND_TEXT, KIND_NUMBER, KIND_LIST = "enum", "text", "number", "list"
OPERATORS_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_ENUM: ("is", "is_not"),
    KIND_TEXT: ("is", "is_not", "contains"),
    KIND_LIST: ("contains",),
    KIND_NUMBER: ("is", "is_not", "greater_than", "less_than"),
}
TEST_RESULT = "test_result"
TEST_PASSED, TEST_FAILED = "passed", "failed"
MAX_ENUM_VALUES = 50


@dataclass(frozen=True, slots=True)
class WorkItemField:
    key: str
    label: str
    kind: str
    # The ``WorkItem`` column it reads; ``None``: the value comes from the run (``test_result``).
    column: str | None
    values: tuple[str, ...] = ()


WORK_ITEM_FIELDS: tuple[WorkItemField, ...] = (
    WorkItemField("type", "Type", KIND_ENUM, "issue_type"),
    WorkItemField("priority", "Priority", KIND_ENUM, "priority"),
    WorkItemField("status", "Status", KIND_ENUM, "source_status"),
    WorkItemField("labels", "Labels", KIND_LIST, "labels_json"),
    WorkItemField("components", "Components", KIND_LIST, "components_json"),
    WorkItemField("assignee", "Assignee", KIND_TEXT, "assignee"),
    WorkItemField(TEST_RESULT, "Test result", KIND_ENUM, None, (TEST_PASSED, TEST_FAILED)),
)
FIELDS_BY_KEY = {field.key: field for field in WORK_ITEM_FIELDS}


def work_item_field(key: Any) -> WorkItemField | None:
    return FIELDS_BY_KEY.get(str(key or "").strip())


async def _column_values(db: AsyncSession, column: Any, project_id: str | None) -> list[str]:
    stmt = select(distinct(column)).where(column.isnot(None), column != "")
    if project_id:
        stmt = stmt.where(WorkItem.project_id == project_id)
    values = (await db.execute(stmt.order_by(column).limit(MAX_ENUM_VALUES))).scalars().all()
    return [str(value) for value in values if str(value or "").strip()]


async def work_item_fields(db: AsyncSession | None = None, *, project_id: str | None = None) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field in WORK_ITEM_FIELDS:
        entry: dict[str, Any] = {"key": field.key, "label": field.label, "kind": field.kind}
        values = list(field.values)
        if not values and field.kind == KIND_ENUM and field.column and db is not None:
            values = await _column_values(db, getattr(WorkItem, field.column), project_id)
        if values:
            entry["values"] = values
        fields.append(entry)
    return fields


def _test_result(run: WorkflowRun) -> str | None:
    runs = dict(dict(run.context or {}).get("tests") or {}).get("runs") or []
    if not runs or not isinstance(runs[-1], dict) or not isinstance(runs[-1].get("all_green"), bool):
        return None
    return TEST_PASSED if runs[-1]["all_green"] else TEST_FAILED


def field_value(field: WorkItemField, run: WorkflowRun, item: WorkItem | None) -> Any:
    if field.key == TEST_RESULT:
        return _test_result(run)
    return getattr(item, field.column, None) if item is not None and field.column else None


def _fold(value: Any) -> str:
    return str(value if value is not None else "").strip().casefold()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare(field: WorkItemField, operator: str, actual: Any, expected: Any) -> bool:
    if field.kind == KIND_LIST:
        entries = actual if isinstance(actual, list) else []
        return operator == "contains" and _fold(expected) in {_fold(entry) for entry in entries}
    if field.kind == KIND_NUMBER:
        left, right = _number(actual), _number(expected)
        if left is None or right is None:
            return operator == "is_not"
        return {"is": left == right, "is_not": left != right, "greater_than": left > right,
                "less_than": left < right}.get(operator, False)
    if operator == "is":
        return actual is not None and _fold(actual) == _fold(expected)
    if operator == "is_not":
        return actual is None or _fold(actual) != _fold(expected)
    if operator == "contains" and field.kind == KIND_TEXT:
        return actual is not None and _fold(expected) in _fold(actual)
    return False


__all__ = [
    "FIELDS_BY_KEY",
    "OPERATORS_BY_KIND",
    "TEST_RESULT",
    "WORK_ITEM_FIELDS",
    "WorkItemField",
    "compare",
    "field_value",
    "work_item_field",
    "work_item_fields",
]
