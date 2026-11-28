"""Changed signatures of a pull request, and whether a call still fits one (Python, ``ast``)."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Signature:
    positional: tuple[tuple[str, bool], ...]  # (name, has a default), positional-only and positional-or-keyword
    vararg: bool
    keyword_only: tuple[tuple[str, bool], ...]
    varkw: bool

    def render(self) -> str:
        parts = [name + ("=…" if default else "") for name, default in self.positional]
        if self.vararg:
            parts.append("*args")
        elif self.keyword_only:
            parts.append("*")
        parts += [name + ("=…" if default else "") for name, default in self.keyword_only]
        if self.varkw:
            parts.append("**kwargs")
        return f"({', '.join(parts)})"


@dataclass(frozen=True, slots=True)
class Change:
    name: str  # ``vat``, ``Invoice``, ``Invoice.total``
    old: Signature
    new: Signature | None  # ``None``: removed

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef, drop_first: bool) -> Signature:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [False] * (len(positional) - len(args.defaults)) + [True] * len(args.defaults)
    pairs = list(zip((arg.arg for arg in positional), defaults, strict=True))
    if drop_first and pairs:
        pairs = pairs[1:]
    keyword_only = tuple((arg.arg, default is not None) for arg, default in zip(args.kwonlyargs, args.kw_defaults,
                                                                                strict=True))
    return Signature(tuple(pairs), args.vararg is not None, keyword_only, args.kwarg is not None)


def _is_static(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(item, ast.Name) and item.id == "staticmethod" for item in node.decorator_list)


def public_callables(source: str) -> dict[str, Signature] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    found: dict[str, Signature] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            found[node.name] = _signature(node, drop_first=False)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            found[node.name] = Signature((), False, (), False)  # no __init__: called without arguments
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name == "__init__":
                    found[node.name] = _signature(item, drop_first=True)
                elif not item.name.startswith("_"):
                    found[f"{node.name}.{item.name}"] = _signature(item, drop_first=not _is_static(item))
    return found


def changed_signatures(base: str, head: str) -> list[Change]:
    before, after = public_callables(base), public_callables(head)
    if before is None or after is None:
        return []
    return [Change(name, signature, after.get(name)) for name, signature in sorted(before.items())
            if after.get(name) != signature]


def call_problem(call: ast.Call, signature: Signature) -> str:
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(item.arg is None for item in call.keywords):
        return ""
    names = [name for name, _default in signature.positional]
    if len(call.args) > len(names) and not signature.vararg:
        return f"passes {len(call.args)} positional arguments, the new signature takes {len(names)}"
    bound = set(names[:len(call.args)])
    keywords = [item.arg for item in call.keywords]
    allowed = set(names) | {name for name, _default in signature.keyword_only}
    for keyword in keywords:
        if keyword in bound:
            return f"passes '{keyword}' twice"
        if keyword not in allowed and not signature.varkw:
            return f"passes the keyword '{keyword}', which the new signature does not take"
    missing = [name for name, default in (*signature.positional, *signature.keyword_only)
               if not default and name not in bound and name not in keywords]
    return f"misses the required argument '{missing[0]}'" if missing else ""


__all__ = ["Change", "Signature", "call_problem", "changed_signatures", "public_callables"]
