"""AST scan for provider-dispatch sites (structural gate support).

The pinned owner inventory (``app/services/model_gateway/dispatch_owners.py``) is
only worth something if a new dispatch consumer cannot appear without being
registered. The first version of that gate matched lines with a regular
expression, so it was only "a gate, not a proof":
a multi-line call, a client handed to a helper, or a ``driver=`` keyword built
from a constant all slipped through.

This module parses each source file instead and reports four things per module:

``client_construction``
    A call to a provider-client factory — a name imported from
    ``agent.providers``, or a parameter the module receives as its factory (the
    injected ``provider_factory`` / ``get_provider_func`` shape used across this
    codebase). Constructing the client is the governed act, so this catches an
    owner that builds a client and lets a *different* module dispatch it.
``gateway_construction``
    Such a call carrying ``driver=`` resolved to the governed gateway, whether
    written as a string literal or as the ``LITELLM_GATEWAY_DRIVER`` constant, plus
    any direct ``LiteLLMGatewayClient(...)``.
``chat_dispatch``
    Any ``<expr>.chat(...)`` call, however the receiver was spelled or wrapped,
    and any bare ``<expr>.chat`` reference handed elsewhere as a callable.
``factory_handoff``
    A factory name passed *as an argument* to another call. Such a module builds
    nothing itself; it is transport into an owner that does.

A ``chat`` method definition, a comment and a docstring are not dispatch sites,
which the mutation controls in ``test_dispatch_owner_inventory.py`` pin from both
directions.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

KIND_CLIENT_CONSTRUCTION = "client_construction"
KIND_GATEWAY_CONSTRUCTION = "gateway_construction"
KIND_CHAT_DISPATCH = "chat_dispatch"
KIND_FACTORY_HANDOFF = "factory_handoff"

# The provider package that owns client construction, and the one factory it
# exports. A name counts as a factory only when it is *that* name imported from
# *that* package — so the unrelated ``_get_provider`` helpers returning database
# rows, and the registry/readiness helpers re-exported next to the factory, are not
# mistaken for it — or when it is one of the injected factory parameters below.
_PROVIDER_MODULE_SUFFIXES = ("agent.providers", "agent.providers.factory", "providers", "providers.factory")
_PROVIDER_FACTORY_EXPORTS = frozenset({"get_provider"})

_INJECTED_FACTORY_PARAMETERS = frozenset(
    {"provider_factory", "provider_factory_func", "get_provider_func", "get_provider"}
)

_GATEWAY_DRIVER_VALUE = "litellm_gateway"
_GATEWAY_DRIVER_CONSTANTS = frozenset({"LITELLM_GATEWAY_DRIVER"})
_GATEWAY_CLIENT_NAMES = frozenset({"LiteLLMGatewayClient"})


@dataclass(frozen=True, slots=True)
class DispatchSite:
    module: str
    line: int
    kind: str
    detail: str


def _import_is_provider_package(node: ast.ImportFrom) -> bool:
    module = (node.module or "").strip()
    return any(module == suffix or module.endswith(f".{suffix}") for suffix in _PROVIDER_MODULE_SUFFIXES)


class _DispatchVisitor(ast.NodeVisitor):
    def __init__(self, module: str):
        self.module = module
        self.sites: list[DispatchSite] = []
        self.factory_names: set[str] = set()

    # --- name resolution ----------------------------------------------------

    def collect_imported_names(self, node: ast.ImportFrom) -> None:
        if _import_is_provider_package(node):
            for alias in node.names:
                if alias.name in _PROVIDER_FACTORY_EXPORTS:
                    self.factory_names.add(alias.asname or alias.name)
        for alias in node.names:
            if alias.name in _GATEWAY_CLIENT_NAMES:
                self.factory_names.add(alias.asname or alias.name)

    def collect_factory_parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if arg.arg in _INJECTED_FACTORY_PARAMETERS:
                self.factory_names.add(arg.arg)

    # --- dispatch sites -----------------------------------------------------

    def _is_factory_reference(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.factory_names
        if isinstance(node, ast.Attribute):
            return node.attr in self.factory_names
        return False

    def _is_gateway_client_reference(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in _GATEWAY_CLIENT_NAMES
        if isinstance(node, ast.Attribute):
            return node.attr in _GATEWAY_CLIENT_NAMES
        return False

    @staticmethod
    def _names_the_gateway_driver(node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return str(node.value).strip().lower() == _GATEWAY_DRIVER_VALUE
        if isinstance(node, ast.Name):
            return node.id in _GATEWAY_DRIVER_CONSTANTS
        if isinstance(node, ast.Attribute):
            return node.attr in _GATEWAY_DRIVER_CONSTANTS
        return False

    def _record(self, node: ast.AST, kind: str, detail: str) -> None:
        self.sites.append(
            DispatchSite(module=self.module, line=getattr(node, "lineno", 0), kind=kind, detail=detail)
        )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "chat":
            self._record(node, KIND_CHAT_DISPATCH, f"{ast.unparse(node.func)}(...)")
        if self._is_gateway_client_reference(node.func):
            self._record(node, KIND_GATEWAY_CONSTRUCTION, f"{ast.unparse(node.func)}(...)")
        elif self._is_factory_reference(node.func):
            self._record(node, KIND_CLIENT_CONSTRUCTION, f"{ast.unparse(node.func)}(...)")
            if any(
                keyword.arg == "driver" and self._names_the_gateway_driver(keyword.value)
                for keyword in node.keywords
            ):
                self._record(node, KIND_GATEWAY_CONSTRUCTION, f"{ast.unparse(node.func)}(driver=...)")
        # A factory passed *into* another call builds nothing here, but it is how a
        # client reaches a module that never imports the factory itself.
        for argument in [*node.args, *[keyword.value for keyword in node.keywords]]:
            if self._is_factory_reference(argument) and not isinstance(argument, ast.Call):
                self._record(node, KIND_FACTORY_HANDOFF, ast.unparse(argument))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # ``client.chat`` referenced without calling it: the dispatch happens
        # wherever that callable is awaited, so the module still owns it.
        if node.attr == "chat" and isinstance(node.ctx, ast.Load):
            self._record(node, KIND_CHAT_DISPATCH, f"{ast.unparse(node)} (reference)")
        self.generic_visit(node)


def scan_source(source: str, *, module: str) -> tuple[DispatchSite, ...]:
    """Every dispatch site in one module's source, in source order."""

    visitor = _DispatchVisitor(module)
    tree = ast.parse(source)
    # Imports and factory parameters must be known before the calls that use them
    # are judged, and a lazy import inside a function body is the norm in this
    # codebase — so names are collected in a first pass over the whole tree.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            visitor.collect_imported_names(node)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            visitor.collect_factory_parameters(node)
    visitor.visit(tree)
    return tuple(visitor.sites)


def _relative(path: Path) -> str:
    return path.relative_to(APP_ROOT.parent).as_posix()


@lru_cache(maxsize=1)
def scan_app() -> tuple[DispatchSite, ...]:
    """Scan every module under ``app/`` once per session."""

    sites: list[DispatchSite] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if not path.is_file():
            continue
        sites.extend(scan_source(path.read_text(encoding="utf-8"), module=_relative(path)))
    return tuple(sites)


def modules_with_kinds(*kinds: str, exclude_prefixes: tuple[str, ...] = ()) -> dict[str, DispatchSite]:
    """First site per module for the given kinds, outside the excluded prefixes."""

    found: dict[str, DispatchSite] = {}
    for site in scan_app():
        if site.kind not in kinds or site.module in found:
            continue
        if site.module.startswith(exclude_prefixes):
            continue
        found[site.module] = site
    return found


__all__ = [
    "APP_ROOT",
    "KIND_CHAT_DISPATCH",
    "KIND_CLIENT_CONSTRUCTION",
    "KIND_FACTORY_HANDOFF",
    "KIND_GATEWAY_CONSTRUCTION",
    "DispatchSite",
    "modules_with_kinds",
    "scan_app",
    "scan_source",
]
