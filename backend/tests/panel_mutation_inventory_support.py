"""The approved principal guards and the guard placement rule shared by the panel mutation gate tests."""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass

#: Guards a panel mutation route may open with. Each one is proven below to reach
#: :data:`ACTIVE_PRINCIPAL_OWNER`.
APPROVED_PRINCIPAL_GUARDS = frozenset(
    {
        "_require_api_user",
        "_require_active_api_user",
        "_require_admin_api",
        "_require_admin_permission_api",
    }
)


#: Ways of getting a principal that skip the active check or the API status
#: code. A mutation route using one of these is authenticating by hand.
FORBIDDEN_PRINCIPAL_SOURCES = frozenset(
    {
        "_require_user",
        "_get_user_from_cookie",
        "principal_id_from_request",
        "load_active_principal",
        "require_active_page_principal",
    }
)


# --- the placement rule ------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Where the principal guard sits in one handler."""

    guard: str | None
    problem: str

    @property
    def ok(self) -> bool:
        return not self.problem


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _awaited_guard(statement: ast.stmt) -> str | None:
    """Guard name when *statement* is exactly ``[x =] await <guard>(...)``.

    Deliberately shallow: the guard has to be the awaited call of the statement
    itself. A guard reached only inside an ``if``, a ``try``, a loop, a ``with``,
    a nested function, or a comprehension is not this shape, and must not count.
    """
    value = statement.value if isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign) else None
    if not isinstance(value, ast.Await) or not isinstance(value.value, ast.Call):
        return None
    func = value.value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name if name in APPROVED_PRINCIPAL_GUARDS else None


def guard_placement(source: str) -> Placement:
    """Whether *source*'s handler opens with an awaited approved guard.

    ``source`` is the handler's own source, decorators included. The rule is the
    strongest form the surface actually satisfies: the guard call is the first
    executable statement of the function body, and it is awaited there. That is
    what "before any authorization decision, service call, audit attribution or
    persistence" means as a structural property — nothing can run first, so
    nothing can be conditioned on, skipped, or done before the refusal.
    """
    definition = ast.parse(textwrap.dedent(source)).body[0]
    if not isinstance(definition, ast.AsyncFunctionDef | ast.FunctionDef):
        return Placement(None, "not a function definition")

    body = list(definition.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return Placement(None, "empty handler body")

    forbidden = _call_names(definition) & FORBIDDEN_PRINCIPAL_SOURCES
    if forbidden:
        return Placement(None, f"resolves a principal by hand via {sorted(forbidden)}")

    guard = _awaited_guard(body[0])
    if guard:
        return Placement(guard, "")
    if _call_names(definition) & APPROVED_PRINCIPAL_GUARDS:
        return Placement(
            None,
            "an approved guard is called, but not as the first executable statement "
            f"of the handler; the handler opens with: {ast.unparse(body[0])[:80]!r}",
        )
    return Placement(None, "no approved principal guard")
