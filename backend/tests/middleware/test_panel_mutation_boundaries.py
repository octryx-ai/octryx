"""Approved guards reach the single active-principal owner, the CSRF boundary is installed in place, and audit cannot attribute a refusal."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware

from app.main import app
from app.middleware.security.multipart_admission import MultipartAdmissionMiddleware
from app.middleware.security.panel_csrf import PanelCsrfBoundaryMiddleware
from app.middleware.security.trusted_proxy import TrustedProxyBoundaryMiddleware
from app.web._helpers import api_guards
from tests.support.panel_mutation_inventory_support import APPROVED_PRINCIPAL_GUARDS, _call_names

API_GUARDS_MODULE = Path(api_guards.__file__).resolve()


#: The single owner of "this principal exists and is still active".
ACTIVE_PRINCIPAL_OWNER = "require_active_api_principal"


def test_every_approved_guard_reaches_the_single_active_principal_owner():
    tree = ast.parse(API_GUARDS_MODULE.read_text(encoding="utf-8"), filename=str(API_GUARDS_MODULE))
    calls_by_function: dict[str, set[str]] = {}
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            calls_by_function[node.name] = _call_names(node)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            target = node.targets[0]
            if isinstance(target, ast.Name):
                aliases[target.id] = node.value.id

    def reaches(name: str, seen: frozenset[str] = frozenset()) -> bool:
        if name in seen:
            return False
        name = aliases.get(name, name)
        calls = calls_by_function.get(name, set())
        if ACTIVE_PRINCIPAL_OWNER in calls:
            return True
        return any(reaches(callee, seen | {name}) for callee in calls & APPROVED_PRINCIPAL_GUARDS)

    detached = sorted(guard for guard in APPROVED_PRINCIPAL_GUARDS if not reaches(guard))
    assert detached == [], (
        f"approved guards that no longer reach {ACTIVE_PRINCIPAL_OWNER}: {detached}. "
        "The inventory gate would then pass on routes with no active check."
    )
    # The explicit name and the default guard must stay the same object, so no
    # future edit can make one stricter than the other.
    assert api_guards._require_active_api_user is api_guards._require_api_user


def test_the_csrf_boundary_is_installed_where_the_guarantee_needs_it():
    stack = [entry.cls for entry in app.user_middleware]
    assert PanelCsrfBoundaryMiddleware in stack, "the panel CSRF boundary is not installed"
    # ``user_middleware`` is ordered outermost first.
    position = stack.index(PanelCsrfBoundaryMiddleware)
    assert position > stack.index(TrustedProxyBoundaryMiddleware), (
        "the CSRF boundary must run inside the trusted-proxy boundary, or the "
        "expected origin would be built from an unvalidated scheme"
    )
    assert position > stack.index(CORSMiddleware), "a refusal must still be labelled by CORS"
    assert position < stack.index(MultipartAdmissionMiddleware), (
        "the CSRF boundary must run outside the multipart boundary, so a cross-site "
        "upload is refused before its body is parsed"
    )


def test_the_request_audit_cannot_attribute_anything_before_a_refusal():
    from app.middleware.audit import audit_middleware

    names = [getattr(entry.cls, "__name__", "") for entry in app.user_middleware]
    dispatchers = [
        getattr(entry.kwargs.get("dispatch"), "__name__", "") for entry in app.user_middleware
    ]
    assert "audit_middleware" in dispatchers, "the generic request audit is not installed"
    assert dispatchers.index("audit_middleware") < names.index("PanelCsrfBoundaryMiddleware")

    body = ast.parse(textwrap.dedent(inspect.getsource(audit_middleware))).body[0]
    statements = [s for s in body.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    first_await = next(
        i for i, statement in enumerate(statements) if any(isinstance(n, ast.Await) for n in ast.walk(statement))
    )
    assert "call_next" in ast.unparse(statements[first_await]), (
        "the request audit must await the downstream response before it writes anything"
    )
    writes = [i for i, statement in enumerate(statements) if "AuditLog(" in ast.unparse(statement)]
    assert writes and min(writes) > first_await
