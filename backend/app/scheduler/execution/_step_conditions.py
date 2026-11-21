from __future__ import annotations

import ast
import operator
from typing import Any

_SAFE_EXPR_FUNCTIONS = {
    "len": len,
    "str": str,
    "int": int,
    "bool": bool,
    "list": list,
    "dict": dict,
    "any": any,
    "all": all,
    "min": min,
    "max": max,
    "sum": sum,
}
_SAFE_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_SAFE_UNARY_OPERATORS = {
    ast.Not: operator.not_,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_SAFE_COMPARATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def normalize_condition_value(value: Any, step_result_type: type) -> Any:
    if isinstance(value, step_result_type):
        return {
            "step_id": value.step_id,
            "position": value.position,
            "name": value.name,
            "step_type": value.step_type,
            "status": value.status,
            "output": normalize_condition_value(value.output, step_result_type),
            "error": value.error,
            "fix_attempts": value.fix_attempts,
            "session_ids": list(value.session_ids),
        }
    if isinstance(value, dict):
        return {str(key): normalize_condition_value(item, step_result_type) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_condition_value(item, step_result_type) for item in value]
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def eval_condition_ast(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return eval_condition_ast(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        if node.id in names:
            return names[node.id]
        if node.id in _SAFE_EXPR_FUNCTIONS:
            return _SAFE_EXPR_FUNCTIONS[node.id]
        raise ValueError(f"Unsupported name '{node.id}'")
    if isinstance(node, ast.BoolOp):
        values = [eval_condition_ast(value, names) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError("Unsupported boolean operator")
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_UNARY_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported unary operator")
        return op(eval_condition_ast(node.operand, names))
    if isinstance(node, ast.BinOp):
        op = _SAFE_BINARY_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError("Unsupported binary operator")
        return op(
            eval_condition_ast(node.left, names),
            eval_condition_ast(node.right, names),
        )
    if isinstance(node, ast.Compare):
        left = eval_condition_ast(node.left, names)
        for comparator, right_node in zip(node.ops, node.comparators):
            right = eval_condition_ast(right_node, names)
            compare = _SAFE_COMPARATORS.get(type(comparator))
            if compare is None or not compare(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if eval_condition_ast(node.test, names) else node.orelse
        return eval_condition_ast(branch, names)
    if isinstance(node, ast.Call):
        func = eval_condition_ast(node.func, names)
        if func not in _SAFE_EXPR_FUNCTIONS.values():
            raise ValueError("Unsupported function call")
        if node.keywords:
            raise ValueError("Keyword arguments are not supported")
        return func(*(eval_condition_ast(arg, names) for arg in node.args))
    if isinstance(node, ast.Subscript):
        value = eval_condition_ast(node.value, names)
        index = eval_condition_ast(node.slice, names)
        return value[index]
    if isinstance(node, ast.Slice):
        lower = eval_condition_ast(node.lower, names) if node.lower else None
        upper = eval_condition_ast(node.upper, names) if node.upper else None
        step = eval_condition_ast(node.step, names) if node.step else None
        return slice(lower, upper, step)
    if isinstance(node, ast.List):
        return [eval_condition_ast(elt, names) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(eval_condition_ast(elt, names) for elt in node.elts)
    if isinstance(node, ast.Set):
        return {eval_condition_ast(elt, names) for elt in node.elts}
    if isinstance(node, ast.Dict):
        return {
            eval_condition_ast(key, names): eval_condition_ast(value, names)
            for key, value in zip(node.keys, node.values)
        }
    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def evaluate_condition_expression(expr: str, context: dict[str, Any], step_result_type: type) -> bool:
    parsed = ast.parse(expr, mode="eval")
    safe_context = normalize_condition_value(context, step_result_type)
    names = {
        "context": safe_context,
        "steps": safe_context.get("steps", {}),
    }
    return bool(eval_condition_ast(parsed, names))
